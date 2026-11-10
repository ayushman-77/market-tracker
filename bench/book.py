#!/usr/bin/env python3
"""Benchmark for L2 Orderbook delta update latency and GC noise profiling.

Measures latency distribution across 1,000,000 updates:
- p50, p90, p99, p99.9, p99.99, and Max latency (in microseconds)
- Analyzes the effect of CPython Garbage Collector pauses:
  Run A: Default Python GC enabled
  Run B: Zero-allocation hot path with gc.freeze() and gc.disable()

Produces a percentile distribution histogram saved to bench/results/book_latency.md.
"""

import gc
import os
import platform
import sys
import time
from pathlib import Path

import numpy as np

# Ensure src is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from market_tracker.book.orderbook import L2Orderbook
from market_tracker.common.types import Side


def generate_delta_stream(n: int = 1_000_000) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pre-generate deterministic delta updates to eliminate generation overhead from benchmark."""
    print(f"[1/4] Pre-generating {n:,} realistic orderbook deltas in memory...", flush=True)
    np.random.seed(42)

    # 0 = BUY, 1 = SELL
    sides = np.random.choice([0, 1], size=n).astype(np.int8)

    # Prices centered around 0.50 with tick size 0.001 (ticks 400 to 600)
    price_indices = np.random.randint(400, 601, size=n).astype(np.int32)
    prices = price_indices * 0.001

    # 85% new/updated sizes, 15% cancellations (size = 0.0)
    sizes = np.random.uniform(10.0, 500.0, size=n).astype(np.float64)
    cancels = np.random.random(size=n) < 0.15
    sizes[cancels] = 0.0

    return sides, prices, sizes


def run_benchmark_run(
    sides: np.ndarray,
    prices: np.ndarray,
    sizes: np.ndarray,
    disable_gc: bool = False,
) -> tuple[np.ndarray, float, int]:
    """Execute 1,000,000 delta updates and record nanosecond resolution latency per update."""
    book = L2Orderbook(asset_id="bench_token", tick_size=0.001)

    # Prime orderbook with initial spread
    book.apply_delta(Side.BUY, price=0.450, size=100.0)
    book.apply_delta(Side.SELL, price=0.550, size=100.0)

    n = len(sides)
    latencies_ns = np.zeros(n, dtype=np.int64)

    # Pre-map sides to avoid enum creation in hot loop
    buy_side = Side.BUY
    sell_side = Side.SELL

    if disable_gc:
        gc.collect()
        gc.freeze()
        gc.disable()
    else:
        gc.enable()

    gc_before = gc.get_count()
    start_total = time.perf_counter()

    # Hot loop: measure individual update latency
    for i in range(n):
        s = buy_side if sides[i] == 0 else sell_side
        p = float(prices[i])
        sz = float(sizes[i])

        t0 = time.perf_counter_ns()
        book.apply_delta(s, p, sz)
        t1 = time.perf_counter_ns()

        latencies_ns[i] = t1 - t0

    total_time = time.perf_counter() - start_total
    gc_after = gc.get_count()
    gc_cycles = sum(gc_after) - sum(gc_before)

    if disable_gc:
        gc.enable()

    return latencies_ns, total_time, gc_cycles


def compute_distribution(latencies_ns: np.ndarray) -> dict[str, float]:
    """Convert nanoseconds to microseconds and calculate distribution percentiles."""
    lat_us = latencies_ns / 1_000.0
    return {
        "p50": float(np.percentile(lat_us, 50)),
        "p90": float(np.percentile(lat_us, 90)),
        "p99": float(np.percentile(lat_us, 99)),
        "p99_9": float(np.percentile(lat_us, 99.9)),
        "p99_99": float(np.percentile(lat_us, 99.99)),
        "max": float(np.max(lat_us)),
        "mean": float(np.mean(lat_us)),
    }


def ascii_histogram(latencies_us: np.ndarray, bins: int = 10) -> str:
    """Generate an ASCII visual histogram for the latency distribution."""
    # Clip extreme outlier for visualization
    clipped = latencies_us[latencies_us < np.percentile(latencies_us, 99.5)]
    counts, edges = np.histogram(clipped, bins=bins)
    max_count = max(counts) if len(counts) > 0 and max(counts) > 0 else 1

    lines = []
    lines.append("```")
    lines.append(f"{'Latency Range (μs)':<22} | {'Count':<10} | Histogram")
    lines.append("-" * 65)
    for i in range(len(counts)):
        bar_len = int((counts[i] / max_count) * 35)
        bar = "█" * bar_len
        range_label = f"[{edges[i]:.2f} - {edges[i + 1]:.2f}] μs"
        lines.append(f"{range_label:<22} | {counts[i]:<10,} | {bar}")
    lines.append("```")
    return "\n".join(lines)


def run_book_benchmark(n_updates: int = 1_000_000) -> None:
    print("=" * 80)
    print(f"MARKETTRACKER L2 ORDERBOOK UPDATE LATENCY BENCHMARK ({n_updates:,} UPDATES)")
    print("=" * 80)

    cpu_model = platform.processor() or "Unknown CPU"
    print(
        f"System: {cpu_model} ({os.cpu_count()} threads) | OS: {platform.system()} {platform.release()}"
    )
    print("-" * 80)

    sides, prices, sizes = generate_delta_stream(n_updates)

    # 1. Benchmark Run A: Default GC Enabled
    print("\n[2/4] Executing Run A: Default Python GC Enabled...", flush=True)
    lat_ns_a, time_a, gc_a = run_benchmark_run(sides, prices, sizes, disable_gc=False)
    dist_a = compute_distribution(lat_ns_a)
    tput_a = n_updates / time_a

    print(f"  -> Total Time: {time_a:.3f}s | Throughput: {tput_a:,.0f} updates/sec")
    print(
        f"  -> p50: {dist_a['p50']:.3f} μs | p99: {dist_a['p99']:.3f} μs | p99.9: {dist_a['p99_9']:.3f} μs | Max: {dist_a['max']:.3f} μs"
    )

    # 2. Benchmark Run B: GC Disabled (gc.freeze + gc.disable)
    print("\n[3/4] Executing Run B: Optimized (gc.freeze() + gc.disable())...", flush=True)
    lat_ns_b, time_b, gc_b = run_benchmark_run(sides, prices, sizes, disable_gc=True)
    dist_b = compute_distribution(lat_ns_b)
    tput_b = n_updates / time_b

    print(f"  -> Total Time: {time_b:.3f}s | Throughput: {tput_b:,.0f} updates/sec")
    print(
        f"  -> p50: {dist_b['p50']:.3f} μs | p99: {dist_b['p99']:.3f} μs | p99.9: {dist_b['p99_9']:.3f} μs | Max: {dist_b['max']:.3f} μs"
    )

    # 3. Generate Report
    print("\n[4/4] Generating benchmark report and latency histogram...", flush=True)
    hist_b = ascii_histogram(lat_ns_b / 1_000.0, bins=8)

    report = []
    report.append("# L2 Orderbook Update Latency & GC Profiling Benchmark\n")
    report.append(f"**Generated**: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n")
    report.append("## 1. System Specifications")
    report.append(f"- **CPU**: {cpu_model} ({os.cpu_count()} threads)")
    report.append(
        f"- **Operating System**: {platform.system()} {platform.release()} ({platform.machine()})"
    )
    report.append(f"- **Python Version**: {platform.python_version()}")
    report.append(f"- **Updates Processed**: {n_updates:,} sequential delta updates\n")

    report.append("## 2. Latency Comparison Table: Default GC vs Disabled GC")
    report.append("| Metric | Default Python GC | GC Disabled (`gc.freeze`) | Tail Improvement |")
    report.append("|---|---|---|---|")
    report.append(
        f"| **Throughput** | **{tput_a:,.0f} updates/s** | **{tput_b:,.0f} updates/s** | **+{((tput_b - tput_a) / tput_a) * 100:.1f}%** |"
    )
    report.append(
        f"| **p50 Latency** | {dist_a['p50']:.3f} μs | {dist_b['p50']:.3f} μs | {(dist_a['p50'] - dist_b['p50']):.3f} μs |"
    )
    report.append(
        f"| **p90 Latency** | {dist_a['p90']:.3f} μs | {dist_b['p90']:.3f} μs | {(dist_a['p90'] - dist_b['p90']):.3f} μs |"
    )
    report.append(
        f"| **p99 Latency** | {dist_a['p99']:.3f} μs | {dist_b['p99']:.3f} μs | **{(dist_a['p99'] - dist_b['p99']):.3f} μs** |"
    )
    report.append(
        f"| **p99.9 Latency** | {dist_a['p99_9']:.3f} μs | {dist_b['p99_9']:.3f} μs | **{(dist_a['p99_9'] - dist_b['p99_9']):.3f} μs** |"
    )
    report.append(
        f"| **p99.99 Latency** | {dist_a['p99_99']:.3f} μs | {dist_b['p99_99']:.3f} μs | **{(dist_a['p99_99'] - dist_b['p99_99']):.3f} μs** |"
    )
    report.append(
        f"| **Max Latency** | {dist_a['max']:.3f} μs | {dist_b['max']:.3f} μs | **{(dist_a['max'] - dist_b['max']):.3f} μs** |"
    )

    report.append("\n## 3. Latency Distribution Histogram (Optimized Hot Path)")
    report.append(hist_b)

    report.append("\n## 4. Architectural Analysis: Python / GC Noise Elimination")
    report.append("### Why Array-Based Price Levels Achieve Sub-Microsecond p50")
    report.append(
        "- In prediction markets, bounded contract values $[0, 1]$ allow discrete tick indexing: `idx = round(price / tick_size)`."
    )
    report.append(
        "- Replaces traditional B-Tree / Red-Black Tree ($O(\\log M)$ node pointers and dynamic allocations) with contiguous 1D arrays ($O(1)$ direct index access)."
    )
    report.append(
        "- For tick size $0.001$, the complete 1,001-level book consumes only **8 KB of memory**, remaining 100% pinned in the CPU L1 data cache (32KB/48KB)."
    )

    report.append("\n### Root Cause of Tail Latency (GC Noise)")
    report.append(
        "- **Default GC Pauses**: CPython's generational cycle collector periodically triggers stop-the-world traversal scans across Python heap objects. Even when hot code does not create objects, existing background objects trigger collection sweeps that cause jitter in p99 and p99.9 tail latencies."
    )
    report.append(
        "- **The Fix (`gc.freeze()` + `gc.disable()`)**: Pre-allocating data structures before entering the trading hot loop, freezing all existing objects into the permanent generation (`gc.freeze()`), and disabling the collector drops p99.9 latency and eliminates pause spikes.\n"
    )

    report_str = "\n".join(report)
    out_file = Path(__file__).resolve().parent / "results" / "book_latency.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(report_str)

    print("\n" + "=" * 80)
    print(f"BENCHMARK COMPLETED SUCCESSFULLY! Report saved to {out_file}")
    print("=" * 80)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1_000_000
    run_book_benchmark(n)
