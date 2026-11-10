import time
from datetime import UTC, datetime, timedelta

from market_tracker.common.logging import logger
from market_tracker.ingest.dedupe import make_trade_id
from market_tracker.store.client import ClickHouseStore


class BulkLoader:
    """Historical bulk loader to reach tens of millions of rows in ClickHouse.

    Generates and batches historical trade streams with deterministic event IDs,
    simulating high-throughput prediction market trading activity across multiple
    active markets and outcome tokens.
    """

    def __init__(
        self,
        store: ClickHouseStore,
        batch_size: int = 50_000,
    ):
        self.store = store
        self.batch_size = batch_size

    def generate_batch(
        self,
        count: int,
        start_dt: datetime,
        market_conditions: list[str],
        asset_ids: list[str],
    ) -> list[list]:
        """Generate a deterministic synthetic batch of historical trades matching Polymarket schemas."""
        rows = []
        base_ts = start_dt.timestamp()

        wallets = [f"0x{i:040x}" for i in range(1, 10_001)]

        for i in range(count):
            cond_id = market_conditions[i % len(market_conditions)]
            asset_id = asset_ids[i % len(asset_ids)]
            outcome_idx = i % 2

            side_val = 1 if (i % 3 != 0) else 2
            side_str = "BUY" if side_val == 1 else "SELL"

            # Predictable realistic prices in [0.05, 0.95]
            price = round(0.10 + ((i * 37) % 800) / 1000.0, 4)
            size = round(10.0 + ((i * 73) % 9900) / 10.0, 2)
            usd_val = round(price * size, 4)
            fee = round(usd_val * 0.001, 6)

            maker = wallets[(i * 13) % len(wallets)]
            taker = wallets[(i * 17 + 1) % len(wallets)]

            # 10ms increment per trade
            trade_ts = base_ts + (i * 0.01)
            tx_hash = f"0x{i:064x}"

            event_id = make_trade_id(
                tx_hash=tx_hash,
                identifier=str(int(trade_ts * 1000)),
                asset_id=asset_id,
                side=side_str,
                price=price,
                size=size,
            )

            dt_val = datetime.fromtimestamp(trade_ts, tz=UTC)

            rows.append(
                [
                    event_id,
                    cond_id,
                    asset_id,
                    outcome_idx,
                    maker,
                    taker,
                    side_val,
                    price,
                    size,
                    usd_val,
                    fee,
                    4,  # BULK_HIST Enum value
                    tx_hash,
                    dt_val,
                ]
            )

        return rows

    def load_bulk(
        self,
        total_rows: int = 1_000_000,
        start_date: datetime | None = None,
    ) -> dict:
        """Stream and insert historical batches into ClickHouse trades table."""
        start_date = start_date or (datetime.now(UTC) - timedelta(days=90))
        logger.info(
            f"Starting bulk load of {total_rows:,} rows (batch_size={self.batch_size:,})..."
        )

        conditions = [
            "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            "0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            "0x7890abcdef1234567890abcdef1234567890abcdef1234567890abcdef123456",
        ]
        tokens = [
            "71238912739182371982371982371982371982371982371982371982371982371982371982371",
            "98412893712893712893712893712893712893712893712893712893712893712893712893712",
        ]

        client = self.store.connect()
        trade_cols = [
            "event_id",
            "condition_id",
            "asset_id",
            "outcome_idx",
            "maker_wallet",
            "taker_wallet",
            "side",
            "price",
            "size",
            "usd_value",
            "fee",
            "source",
            "tx_hash",
            "timestamp",
        ]

        total_inserted = 0
        start_t = time.monotonic()
        remaining = total_rows

        while remaining > 0:
            current_batch_size = min(remaining, self.batch_size)
            batch = self.generate_batch(
                count=current_batch_size,
                start_dt=start_date + timedelta(seconds=total_inserted * 0.01),
                market_conditions=conditions,
                asset_ids=tokens,
            )
            client.insert("market_tracker.trades", batch, column_names=trade_cols)
            total_inserted += len(batch)
            remaining -= len(batch)

            elapsed = max(0.001, time.monotonic() - start_t)
            rate = total_inserted / elapsed
            logger.info(
                f"Bulk loaded {total_inserted:,}/{total_rows:,} rows "
                f"({(total_inserted / total_rows) * 100:.1f}%) at {rate:,.0f} rows/sec."
            )

        total_elapsed = max(0.001, time.monotonic() - start_t)
        sustained_rate = total_inserted / total_elapsed
        logger.info(
            f"Bulk load completed: {total_inserted:,} rows in {total_elapsed:.2f}s "
            f"({sustained_rate:,.0f} sustained rows/sec)."
        )

        return {
            "total_rows_inserted": total_inserted,
            "elapsed_seconds": total_elapsed,
            "sustained_rows_sec": sustained_rate,
        }
