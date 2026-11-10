import asyncio
import time
from typing import Any

from market_tracker.common.config import settings
from market_tracker.common.logging import logger
from market_tracker.common.types import BookEvent, Trade
from market_tracker.store.client import ClickHouseStore


class BatchWriter:
    """High-throughput asynchronous batch writer for ClickHouse with backpressure.

    Buffers rows in an asyncio.Queue, never blocking the upstream ingest socket.
    Flushes when batch size is reached or when flush interval timer fires.
    """

    def __init__(
        self,
        store: ClickHouseStore,
        batch_size: int | None = None,
        flush_interval_ms: int | None = None,
        queue_max_size: int | None = None,
    ):
        self.store = store
        self.batch_size = batch_size or settings.batch_size
        self.flush_interval = (flush_interval_ms or settings.flush_interval_ms) / 1000.0
        self.queue: asyncio.Queue[tuple[str, list[Any]]] = asyncio.Queue(
            maxsize=queue_max_size or settings.queue_max_size
        )
        self._running = False
        self._worker_task: asyncio.Task | None = None
        self._trade_buffer: list[list[Any]] = []
        self._book_buffer: list[list[Any]] = []

        # Metrics
        self.total_rows_inserted = 0
        self.total_flushes = 0
        self.last_flush_time = time.monotonic()
        self.start_time = time.monotonic()

    async def start(self) -> None:
        self._running = True
        self.start_time = time.monotonic()
        self._worker_task = asyncio.create_task(self._flush_loop())
        logger.info(
            f"BatchWriter started (batch_size={self.batch_size}, interval={self.flush_interval}s)"
        )

    async def stop(self) -> None:
        self._running = False
        try:
            await self.queue.put(("__STOP__", []))
            if self._worker_task:
                await asyncio.wait_for(self._worker_task, timeout=5.0)
        except (TimeoutError, asyncio.CancelledError):
            if self._worker_task and not self._worker_task.done():
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except asyncio.CancelledError:
                    pass

        self._worker_task = None
        logger.info(f"BatchWriter stopped. Total inserted: {self.total_rows_inserted} rows.")

    async def enqueue_trade(self, trade: Trade) -> None:
        row = [
            trade.event_id,
            trade.condition_id,
            trade.asset_id,
            trade.outcome_idx,
            trade.maker_wallet,
            trade.taker_wallet,
            trade.side.value,
            trade.price,
            trade.size,
            trade.usd_value,
            trade.fee,
            trade.source.value,
            trade.tx_hash,
            trade.timestamp,
        ]
        await self.queue.put(("trades", row))

    async def enqueue_book_event(self, event: BookEvent) -> None:
        row = [
            event.event_id,
            event.asset_id,
            event.event_type.value,
            event.side.value,
            event.price,
            event.size,
            event.best_bid,
            event.best_ask,
            event.book_hash,
            event.timestamp,
        ]
        await self.queue.put(("book_events", row))

    async def _flush_loop(self) -> None:
        last_flush = time.monotonic()
        try:
            while True:
                timeout = max(0.005, self.flush_interval - (time.monotonic() - last_flush))
                try:
                    table, row = await asyncio.wait_for(self.queue.get(), timeout=timeout)
                    if table == "__STOP__":
                        self.queue.task_done()
                        break
                    elif table == "trades":
                        self._trade_buffer.append(row)
                    elif table == "book_events":
                        self._book_buffer.append(row)
                    self.queue.task_done()

                    # Rapidly drain queued items up to batch size without timer overhead
                    while (
                        not self.queue.empty()
                        and len(self._trade_buffer) < self.batch_size
                        and len(self._book_buffer) < self.batch_size
                    ):
                        try:
                            table, row = self.queue.get_nowait()
                            if table == "__STOP__":
                                self.queue.task_done()
                                return
                            elif table == "trades":
                                self._trade_buffer.append(row)
                            elif table == "book_events":
                                self._book_buffer.append(row)
                            self.queue.task_done()
                        except asyncio.QueueEmpty:
                            break
                except TimeoutError:
                    if not self._running and self.queue.empty():
                        break

                now = time.monotonic()
                should_flush_size = (
                    len(self._trade_buffer) >= self.batch_size
                    or len(self._book_buffer) >= self.batch_size
                )
                should_flush_time = (now - last_flush) >= self.flush_interval

                if (should_flush_size or should_flush_time) and (
                    self._trade_buffer or self._book_buffer
                ):
                    to_flush_trades = self._trade_buffer[:]
                    to_flush_books = self._book_buffer[:]
                    self._trade_buffer.clear()
                    self._book_buffer.clear()
                    await self._flush_buffers(to_flush_trades, to_flush_books)
                    last_flush = now
        finally:
            # Drain any remaining queue items into buffers
            while not self.queue.empty():
                try:
                    table, row = self.queue.get_nowait()
                    if table == "trades":
                        self._trade_buffer.append(row)
                    elif table == "book_events":
                        self._book_buffer.append(row)
                    self.queue.task_done()
                except asyncio.QueueEmpty:
                    break

            # Guaranteed final synchronous flush of all buffered records (safe on cancellation)
            if self._trade_buffer or self._book_buffer:
                to_flush_trades = self._trade_buffer[:]
                to_flush_books = self._book_buffer[:]
                self._trade_buffer.clear()
                self._book_buffer.clear()

                client = self.store.connect()
                if to_flush_trades:
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
                    client.insert("market_tracker.trades", to_flush_trades, column_names=trade_cols)
                    self.total_rows_inserted += len(to_flush_trades)

                if to_flush_books:
                    book_cols = [
                        "event_id",
                        "asset_id",
                        "event_type",
                        "side",
                        "price",
                        "size",
                        "best_bid",
                        "best_ask",
                        "book_hash",
                        "timestamp",
                    ]
                    client.insert(
                        "market_tracker.book_events", to_flush_books, column_names=book_cols
                    )
                    self.total_rows_inserted += len(to_flush_books)

                self.total_flushes += 1

    async def _flush_buffers(self, trades: list[list[Any]], books: list[list[Any]]) -> None:
        loop = asyncio.get_running_loop()
        client = self.store.connect()

        if trades:
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
            await loop.run_in_executor(
                None,
                lambda: client.insert("market_tracker.trades", trades, column_names=trade_cols),
            )
            self.total_rows_inserted += len(trades)

        if books:
            book_cols = [
                "event_id",
                "asset_id",
                "event_type",
                "side",
                "price",
                "size",
                "best_bid",
                "best_ask",
                "book_hash",
                "timestamp",
            ]
            await loop.run_in_executor(
                None,
                lambda: client.insert("market_tracker.book_events", books, column_names=book_cols),
            )
            self.total_rows_inserted += len(books)

        self.total_flushes += 1

    @property
    def metrics(self) -> dict[str, Any]:
        elapsed = max(0.001, time.monotonic() - self.start_time)
        return {
            "queue_depth": self.queue.qsize(),
            "total_rows_inserted": self.total_rows_inserted,
            "total_flushes": self.total_flushes,
            "sustained_rows_per_sec": self.total_rows_inserted / elapsed,
        }
