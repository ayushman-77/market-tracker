#!/usr/bin/env python3
"""High-throughput ingestion benchmark for MarketTracker.

Measures sustained rows/second ingestion throughput into ClickHouse
via bounded queue and asynchronous batch writer.
"""

import asyncio
import sys
import time
from datetime import UTC, datetime

from market_tracker.common.logging import logger
from market_tracker.common.types import BookEvent, BookEventType, Side, Trade, TradeSource
from market_tracker.ingest.dedupe import DedupeFilter, make_book_event_id, make_trade_id
from market_tracker.store.batch_writer import BatchWriter
from market_tracker.store.client import ClickHouseStore


async def run_ingestion_benchmark(total_events: int = 100_000, batch_size: int = 10_000) -> None:
    print("=" * 70)
    print(f"MARKETTRACKER INGESTION BENCHMARK: {total_events:,} events (batch_size={batch_size:,})")
    print("=" * 70)

    store = ClickHouseStore()
    try:
        store.init_schema()
    except Exception as e:
        logger.warning(f"ClickHouse schema init fallback: {e}")

    dedupe_filter = DedupeFilter(capacity=total_events * 2)
    writer = BatchWriter(
        store=store,
        batch_size=batch_size,
        flush_interval_ms=100,
        queue_max_size=total_events,
    )

    await writer.start()

    # Pre-generate stream for pure pipeline throughput measurement
    print(f"[1/3] Generating {total_events:,} trade & orderbook events in memory...")
    events: list[tuple[str, object]] = []
    base_ts = time.time()
    cond_id = "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
    token_id = "71238912739182371982371982371982371982371982371982371982371982371982371982371"

    for i in range(total_events):
        ts = base_ts + (i * 0.001)
        dt = datetime.fromtimestamp(ts, tz=UTC)
        side = Side.BUY if (i % 2 == 0) else Side.SELL
        price = round(0.45 + ((i * 19) % 200) / 1000.0, 4)
        size = round(5.0 + ((i * 43) % 200) / 5.0, 2)

        if i % 3 == 0:
            # Trade event
            tx_hash = f"0xbench_{i:016x}"
            ev_id = make_trade_id(tx_hash, str(i), token_id, side.value, price, size)
            trade = Trade(
                event_id=ev_id,
                condition_id=cond_id,
                asset_id=token_id,
                outcome_idx=i % 2,
                maker_wallet=f"0xmaker_{i % 100:04x}",
                taker_wallet=f"0xtaker_{i % 100:04x}",
                side=side,
                price=price,
                size=size,
                usd_value=price * size,
                fee=round(price * size * 0.001, 6),
                source=TradeSource.WS_CLOB,
                tx_hash=tx_hash,
                timestamp=dt,
            )
            events.append(("trade", trade))
        else:
            # Orderbook level delta event
            ev_id = make_book_event_id(token_id, int(ts * 1000), side.value, price, size)
            book_ev = BookEvent(
                event_id=ev_id,
                asset_id=token_id,
                event_type=BookEventType.DELTA,
                side=side,
                price=price,
                size=size,
                best_bid=price if side == Side.BUY else 0.45,
                best_ask=price if side == Side.SELL else 0.55,
                book_hash="0xhash123",
                timestamp=dt,
            )
            events.append(("book", book_ev))

    print(f"[2/3] Streaming {len(events):,} events through dedupe and bounded batch writer...")
    start_time = time.monotonic()

    for ev_type, ev in events:
        if ev_type == "trade":
            if not dedupe_filter.is_duplicate(ev.event_id):
                await writer.enqueue_trade(ev)
        else:
            if not dedupe_filter.is_duplicate(ev.event_id):
                await writer.enqueue_book_event(ev)

    # Flush all remaining records to ClickHouse
    await writer.stop()
    total_elapsed = max(0.0001, time.monotonic() - start_time)
    sustained_throughput = total_events / total_elapsed

    # Query ClickHouse row counts
    print("[3/3] Querying ClickHouse row count...")
    trade_count_res = store.query("SELECT count() FROM market_tracker.trades")
    book_count_res = store.query("SELECT count() FROM market_tracker.book_events")

    trade_count = trade_count_res.result_rows[0][0] if trade_count_res.result_rows else 0
    book_count = book_count_res.result_rows[0][0] if book_count_res.result_rows else 0
    total_in_db = trade_count + book_count

    print("----------------------------------------------------------------------")
    print(f"  Total Ingested Events:         {total_events:,}")
    print(f"  Elapsed Ingestion Time:        {total_elapsed:.3f} s")
    print(f"  Sustained Ingestion Rate:      {sustained_throughput:,.0f} rows/sec")
    print(f"  ClickHouse Trades Stored:      {trade_count:,}")
    print(f"  ClickHouse Book Events Stored: {book_count:,}")
    print(f"  ClickHouse Total Row Count:    {total_in_db:,}")
    print("----------------------------------------------------------------------")
    print("BENCHMARK COMPLETED SUCCESSFULLY.")
    print("=" * 70)


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000
    batch = int(sys.argv[2]) if len(sys.argv) > 2 else 10_000
    asyncio.run(run_ingestion_benchmark(total_events=count, batch_size=batch))
