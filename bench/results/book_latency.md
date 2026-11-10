# L2 Orderbook Update Latency & GC Profiling Benchmark

**Generated**: 2026-11-09 11:38:21 UTC

## 1. System Specifications
- **CPU**: Intel64 Family 6 Model 154 Stepping 4, GenuineIntel (8 threads)
- **Operating System**: Windows 11 (AMD64)
- **Python Version**: 3.12.12
- **Updates Processed**: 1,000,000 sequential delta updates

## 2. Latency Comparison Table: Default GC vs Disabled GC
| Metric | Default Python GC | GC Disabled (`gc.freeze`) | Tail Improvement |
|---|---|---|---|
| **Throughput** | **853,070 updates/s** | **1,271,781 updates/s** | **+49.1%** |
| **p50 Latency** | 0.400 μs | 0.400 μs | 0.000 μs |
| **p90 Latency** | 0.600 μs | 0.500 μs | 0.100 μs |
| **p99 Latency** | 0.900 μs | 0.800 μs | **0.100 μs** |
| **p99.9 Latency** | 4.600 μs | 2.500 μs | **2.100 μs** |
| **p99.99 Latency** | 32.300 μs | 20.000 μs | **12.300 μs** |
| **Max Latency** | 241296.500 μs | 369.700 μs | **240926.800 μs** |

## 3. Latency Distribution Histogram (Optimized Hot Path)
```
Latency Range (μs)     | Count      | Histogram
-----------------------------------------------------------------
[0.30 - 0.36] μs       | 113,430    | █████
[0.36 - 0.42] μs       | 741,781    | ███████████████████████████████████
[0.42 - 0.49] μs       | 0          | 
[0.49 - 0.55] μs       | 91,895     | ████
[0.55 - 0.61] μs       | 13,069     | 
[0.61 - 0.68] μs       | 0          | 
[0.68 - 0.74] μs       | 14,622     | 
[0.74 - 0.80] μs       | 15,429     | 
```

## 4. Architectural Analysis: Python / GC Noise Elimination
### Why Array-Based Price Levels Achieve Sub-Microsecond p50
- In prediction markets, bounded contract values $[0, 1]$ allow discrete tick indexing: `idx = round(price / tick_size)`.
- Replaces traditional B-Tree / Red-Black Tree ($O(\log M)$ node pointers and dynamic allocations) with contiguous 1D arrays ($O(1)$ direct index access).
- For tick size $0.001$, the complete 1,001-level book consumes only **8 KB of memory**, remaining 100% pinned in the CPU L1 data cache (32KB/48KB).

### Root Cause of Tail Latency (GC Noise)
- **Default GC Pauses**: CPython's generational cycle collector periodically triggers stop-the-world traversal scans across Python heap objects. Even when hot code does not create objects, existing background objects trigger collection sweeps that cause jitter in p99 and p99.9 tail latencies.
- **The Fix (`gc.freeze()` + `gc.disable()`)**: Pre-allocating data structures before entering the trading hot loop, freezing all existing objects into the permanent generation (`gc.freeze()`), and disabling the collector drops p99.9 latency and eliminates pause spikes.
