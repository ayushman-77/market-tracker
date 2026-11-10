import time

from market_tracker.common.logging import logger
from market_tracker.common.types import Trade
from market_tracker.ingest.data_client import DataClient
from market_tracker.ingest.dedupe import DedupeFilter
from market_tracker.ingest.gap_detector import GapWindow
from market_tracker.store.batch_writer import BatchWriter


class RESTBackfillEngine:
    """Self-healing backfill coordinator.

    When GapDetector identifies a disconnection or timestamp discontinuity,
    this engine queries the Polymarket Data API for the missing time window,
    filters duplicates, and enqueues missing records to ClickHouse.
    """

    def __init__(
        self,
        data_client: DataClient,
        batch_writer: BatchWriter,
        dedupe_filter: DedupeFilter,
    ):
        self.data_client = data_client
        self.batch_writer = batch_writer
        self.dedupe = dedupe_filter

        self.gaps_handled = 0
        self.trades_recovered = 0
        self.total_backfill_time = 0.0

    async def handle_gap(self, gap: GapWindow, condition_id: str | None = None) -> list[Trade]:
        start_t = time.monotonic()
        self.gaps_handled += 1
        logger.info(
            f"[Self-Healing] Reconciling gap window: [{gap.start_time:.2f} -> {gap.end_time:.2f}] "
            f"(reason: {gap.reason})"
        )

        recovered_trades = await self.data_client.get_trades_backfill(
            condition_id=condition_id,
            start_ts=gap.start_time,
            end_ts=gap.end_time,
            limit=500,
        )

        enqueued_count = 0
        for trade in recovered_trades:
            if not self.dedupe.is_duplicate(trade.event_id):
                await self.batch_writer.enqueue_trade(trade)
                enqueued_count += 1

        elapsed = time.monotonic() - start_t
        self.total_backfill_time += elapsed
        self.trades_recovered += enqueued_count

        logger.info(
            f"[Self-Healing] Gap window resolved in {elapsed * 1000:.1f}ms: "
            f"{len(recovered_trades)} retrieved, {enqueued_count} new trades backfilled "
            f"({len(recovered_trades) - enqueued_count} duplicate fills discarded)."
        )
        return recovered_trades
