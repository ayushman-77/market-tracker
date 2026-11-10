import asyncio
import json
import random
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from market_tracker.common.config import settings
from market_tracker.common.logging import logger
from market_tracker.common.types import (
    BookEvent,
    BookEventType,
    Side,
    Trade,
    TradeSource,
)
from market_tracker.ingest.dedupe import DedupeFilter, make_book_event_id, make_trade_id
from market_tracker.ingest.gap_detector import GapDetector, GapWindow


class ClobWebSocketClient:
    """Async WebSocket client for Polymarket CLOB Market Channel.

    Includes exponential backoff + jitter reconnect, periodic ping keepalives,
    resubscription on reconnect, and gap detection triggering REST backfill.
    """

    def __init__(
        self,
        assets_ids: list[str],
        ws_url: str | None = None,
        on_trade: Callable[[Trade], asyncio.Future | None] | None = None,
        on_book_event: Callable[[BookEvent], asyncio.Future | None] | None = None,
        on_gap: Callable[[GapWindow], asyncio.Future | None] | None = None,
        gap_detector: GapDetector | None = None,
        dedupe_filter: DedupeFilter | None = None,
    ):
        self.ws_url = ws_url or settings.clob_ws_url
        self.assets_ids = list(set(assets_ids))
        self.on_trade = on_trade
        self.on_book_event = on_book_event
        self.on_gap = on_gap
        self.gap_detector = gap_detector or GapDetector()
        self.dedupe = dedupe_filter or DedupeFilter()

        self._running = False
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._ping_task: asyncio.Task | None = None
        self.reconnect_count = 0
        self.messages_received = 0

    async def start(self) -> None:
        self._running = True
        backoff = settings.ws_reconnect_base_delay
        max_backoff = settings.ws_reconnect_max_delay

        while self._running:
            try:
                logger.info(f"Connecting to CLOB WebSocket at {self.ws_url}...")
                async with websockets.connect(self.ws_url, ping_interval=None) as ws:
                    self._ws = ws
                    backoff = settings.ws_reconnect_base_delay
                    logger.info("Connected to Polymarket CLOB WebSocket.")

                    # Handle reconnection gap recovery
                    if self.reconnect_count > 0:
                        gap = self.gap_detector.on_reconnect()
                        if gap and self.on_gap:
                            asyncio.create_task(self._safe_callback(self.on_gap, gap))

                    # Send subscription
                    await self._subscribe(ws)

                    # Start ping loop
                    self._ping_task = asyncio.create_task(self._ping_loop(ws))

                    # Read frames
                    async for message in ws:
                        if not self._running:
                            break
                        await self._handle_frame(message)

            except (TimeoutError, ConnectionClosed, OSError) as e:
                self.reconnect_count += 1
                self.gap_detector.on_disconnect()
                if self._ping_task:
                    self._ping_task.cancel()

                if not self._running:
                    break

                jitter = random.uniform(0.5, 1.5)
                delay = min(max_backoff, backoff * jitter)
                logger.warning(
                    f"WebSocket disconnected ({e}). Reconnect #{self.reconnect_count} in {delay:.2f}s..."
                )
                await asyncio.sleep(delay)
                backoff = min(max_backoff, backoff * 2)
            except Exception as e:
                logger.error(f"Unexpected error in WebSocket loop: {e}", exc_info=True)
                await asyncio.sleep(2.0)

    async def stop(self) -> None:
        self._running = False
        if self._ping_task:
            self._ping_task.cancel()
        if self._ws:
            await self._ws.close()
        logger.info(f"CLOB WebSocket client stopped. Total messages: {self.messages_received}")

    async def _subscribe(self, ws: websockets.WebSocketClientProtocol) -> None:
        sub_payload = {
            "type": "market",
            "assets_ids": self.assets_ids,
            "custom_feature_enabled": True,
        }
        await ws.send(json.dumps(sub_payload))
        logger.info(f"Subscribed to {len(self.assets_ids)} assets on CLOB market channel.")

    async def _ping_loop(self, ws: websockets.WebSocketClientProtocol) -> None:
        """Official Polymarket keepalive: send text frame 'PING' every 10s."""
        try:
            while self._running:
                await asyncio.sleep(settings.ws_ping_interval)
                await ws.send("PING")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"Ping loop terminated: {e}")

    async def _handle_frame(self, raw_message: str | bytes) -> None:
        self.messages_received += 1
        if isinstance(raw_message, bytes):
            raw_message = raw_message.decode("utf-8")

        if raw_message == "PONG":
            return

        try:
            data = json.loads(raw_message)
        except Exception:
            return

        # Notify gap detector of active stream heartbeat
        self.gap_detector.on_message_received()

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    await self._process_event(item)
        elif isinstance(data, dict):
            await self._process_event(data)

    async def _process_event(self, event: dict) -> None:
        event_type = event.get("event_type")

        if event_type == "book":
            await self._process_book_snapshot(event)
        elif event_type == "price_change":
            await self._process_price_change(event)
        elif event_type == "last_trade_price":
            await self._process_trade_price(event)

    async def _process_book_snapshot(self, event: dict) -> None:
        asset_id = str(event.get("asset_id", ""))
        ts_ms = int(event.get("timestamp", time.time() * 1000))
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC)
        book_hash = str(event.get("hash", ""))

        for b in event.get("bids", []):
            price = float(b.get("price", 0.0))
            size = float(b.get("size", 0.0))
            ev_id = make_book_event_id(asset_id, ts_ms, "BUY", price, size)
            if self.dedupe.is_duplicate(ev_id):
                continue
            book_ev = BookEvent(
                event_id=ev_id,
                asset_id=asset_id,
                event_type=BookEventType.SNAPSHOT,
                side=Side.BUY,
                price=price,
                size=size,
                best_bid=price,
                best_ask=0.0,
                book_hash=book_hash,
                timestamp=dt,
            )
            if self.on_book_event:
                await self._safe_callback(self.on_book_event, book_ev)

        for a in event.get("asks", []):
            price = float(a.get("price", 0.0))
            size = float(a.get("size", 0.0))
            ev_id = make_book_event_id(asset_id, ts_ms, "SELL", price, size)
            if self.dedupe.is_duplicate(ev_id):
                continue
            book_ev = BookEvent(
                event_id=ev_id,
                asset_id=asset_id,
                event_type=BookEventType.SNAPSHOT,
                side=Side.SELL,
                price=price,
                size=size,
                best_bid=0.0,
                best_ask=price,
                book_hash=book_hash,
                timestamp=dt,
            )
            if self.on_book_event:
                await self._safe_callback(self.on_book_event, book_ev)

    async def _process_price_change(self, event: dict) -> None:
        ts_ms = int(event.get("timestamp", time.time() * 1000))
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC)

        for change in event.get("price_changes", []):
            asset_id = str(change.get("asset_id", ""))
            price = float(change.get("price", 0.0))
            size = float(change.get("size", 0.0))
            side_str = str(change.get("side", "BUY")).upper()
            side = Side.BUY if side_str == "BUY" else Side.SELL
            best_bid = float(change.get("best_bid", 0.0) or 0.0)
            best_ask = float(change.get("best_ask", 0.0) or 0.0)
            book_hash = str(change.get("hash", ""))

            ev_id = make_book_event_id(asset_id, ts_ms, side.value, price, size)
            if self.dedupe.is_duplicate(ev_id):
                continue

            book_ev = BookEvent(
                event_id=ev_id,
                asset_id=asset_id,
                event_type=BookEventType.DELTA,
                side=side,
                price=price,
                size=size,
                best_bid=best_bid,
                best_ask=best_ask,
                book_hash=book_hash,
                timestamp=dt,
            )
            if self.on_book_event:
                await self._safe_callback(self.on_book_event, book_ev)

    async def _process_trade_price(self, event: dict) -> None:
        asset_id = str(event.get("asset_id", ""))
        price = float(event.get("price", 0.0))
        size = float(event.get("size", 0.0))
        side_str = str(event.get("side", "BUY")).upper()
        side = Side.BUY if side_str == "BUY" else Side.SELL
        fee_bps = int(event.get("fee_rate_bps", 0) or 0)
        fee = (size * price * fee_bps) / 10000.0
        ts_ms = int(event.get("timestamp", time.time() * 1000))
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC)

        ev_id = make_trade_id(
            tx_hash="0xclob_ws",
            identifier=str(ts_ms),
            asset_id=asset_id,
            side=side.value,
            price=price,
            size=size,
        )
        if self.dedupe.is_duplicate(ev_id):
            return

        trade = Trade(
            event_id=ev_id,
            condition_id="",
            asset_id=asset_id,
            outcome_idx=0,
            maker_wallet="",
            taker_wallet="",
            side=side,
            price=price,
            size=size,
            usd_value=price * size,
            fee=fee,
            source=TradeSource.WS_CLOB,
            tx_hash="",
            timestamp=dt,
        )
        if self.on_trade:
            await self._safe_callback(self.on_trade, trade)

    async def _safe_callback(self, cb: Callable, arg: Any) -> None:
        try:
            res = cb(arg)
            if asyncio.iscoroutine(res):
                await res
        except Exception as e:
            logger.error(f"Error in callback: {e}", exc_info=True)
