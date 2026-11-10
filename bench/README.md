# MarketTracker Benchmarks (`bench/`)

Every number quoted in MarketTracker documentation must be reproducible via a script in this directory with a single command.

## Available Benchmarks:
1. `mtm.py`: Mark-to-market pass benchmark ladder (Pure Python, NumPy vectorized, Numba SoA, Numba + prange) over 100k, 1M, and 2M positions.
2. `ingest.py`: High-throughput ingestion benchmark measuring sustained rows/sec into ClickHouse with bounded queues and batch flushing.
3. `book.py`: L2 orderbook delta update latency & Python GC pause profiling across 1,000,000 updates.
4. `strategy_profile.py`: Replay backtest profiler measuring tick-to-order decision latency and generating `results/strategy_hotloop.svg`.

## Running:
```bash
python run.py bench           # Runs MTM benchmark ladder
python run.py bench-ingest    # Runs ingestion throughput benchmark
python run.py bench-book      # Runs L2 orderbook update latency benchmark
python run.py bench-strategy  # Runs strategy latency & flamegraph profiler
```

