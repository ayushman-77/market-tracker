"""Real-time WebSocket delta-streaming engine with sequence tracking and coalescence."""

import asyncio
import json
import logging
import time
from dataclasses import asdict
from typing import Any

from fastapi import WebSocket

from market_tracker.common.types import Side, Trade

logger = logging.getLogger("market_tracker.delta_stream")


class DeltaStreamManager:
    """Manages WebSocket clients, stream sequence tracking, and coalesced delta broadcasts."""

    def __init__(self, throttle_hz: float = 20.0):
        # Broadcast rate: 20 Hz = 50ms intervals
        self.interval = 1.0 / throttle_hz
        self.active_connections: set[WebSocket] = set()

        # Monotonic sequence counter per stream
        self.seq_numbers: dict[str, int] = {
            "book": 0,
            "leaderboard": 0,
            "trades": 0,
            "paper": 0,
            "candles": 0,
        }

        # Coalescence buffers (accumulated within each 50ms tick window)
        # book_deltas: (asset_id, side_str, price) -> size
        self._pending_book_deltas: dict[tuple[str, str, float], float] = {}
        # leaderboard_dirty: True if leaderboard needs emit
        self._leaderboard_dirty: bool = False
        self._last_leaderboard_flush: float = 0.0
        # pending_trades: list of serialized trade dicts
        self._pending_trades: list[dict[str, Any]] = []
        # pending_paper_events: list of paper updates
        self._pending_paper_events: list[dict[str, Any]] = []
        # pending_candle_updates: asset_id -> bar payload
        self._pending_candle_updates: dict[str, dict[str, Any]] = {}

        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None
        self._running = False

    def next_seq(self, stream: str) -> int:
        self.seq_numbers[stream] += 1
        return self.seq_numbers[stream]

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)
        logger.info(f"WebSocket client connected. Total clients: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
        logger.info(f"WebSocket client disconnected. Total clients: {len(self.active_connections)}")

    def queue_book_delta(self, asset_id: str, side: Side, price: float, size: float):
        """Coalesce book delta: multiple updates to same (asset, side, price) keep latest size."""
        side_str = "BUY" if side == Side.BUY else "SELL"
        self._pending_book_deltas[(asset_id, side_str, round(price, 3))] = size

    def mark_leaderboard_dirty(self):
        """Flag that wallet rankings/PnLs have shifted."""
        self._leaderboard_dirty = True

    def queue_trade(self, trade: Trade):
        """Queue trade event for broadcast."""
        self._pending_trades.append(
            {
                "event_id": trade.event_id,
                "asset_id": trade.asset_id,
                "maker_wallet": trade.maker_wallet,
                "taker_wallet": trade.taker_wallet,
                "side": "BUY" if trade.side == Side.BUY else "SELL",
                "price": trade.price,
                "size": trade.size,
                "usd_value": trade.usd_value,
                "fee": trade.fee,
                "timestamp": trade.timestamp.isoformat(),
            }
        )

    def queue_paper_update(self, event_type: str, data: dict[str, Any]):
        """Queue paper fill, signal, or equity update."""
        self._pending_paper_events.append(
            {
                "type": event_type,
                "data": data,
                "timestamp": time.time(),
            }
        )

    def queue_candle_update(self, asset_id: str, candle: dict[str, Any]):
        """Coalesce latest candle update per asset."""
        self._pending_candle_updates[asset_id] = candle

    async def broadcast_raw(self, payload: dict[str, Any]):
        """Broadcast JSON message to all connected clients; prune dead sockets."""
        if not self.active_connections:
            return

        msg = json.dumps(payload)
        dead = []
        for ws in list(self.active_connections):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    if ws in self.active_connections:
                        self.active_connections.remove(ws)

    async def handle_client_message(self, websocket: WebSocket, text: str, app_state: Any):
        """Handle incoming control messages from UI (resync, subscribe, ping)."""
        try:
            msg = json.loads(text)
            action = msg.get("type")
            stream = msg.get("stream")

            if action == "ping":
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "pong",
                            "client_ts": msg.get("client_ts"),
                            "server_ts": time.time(),
                        }
                    )
                )
                return

            if action in ("subscribe", "resync"):
                asset_id = msg.get("asset_id") or app_state.default_asset_id
                if asset_id in app_state.markets:
                    app_state.active_sim_asset_id = asset_id
                else:
                    asset_id = app_state.default_asset_id

                book = app_state.orderbooks.get(asset_id)

                if stream in ("book", None) and book:
                    ladder = book.get_ladder(depth=25)
                    seq = self.seq_numbers["book"]
                    await websocket.send_text(
                        json.dumps(
                            {
                                "stream": "book",
                                "type": "snapshot",
                                "seq": seq,
                                "asset_id": asset_id,
                                "data": asdict(ladder),
                            }
                        )
                    )

                if stream in ("leaderboard", None):
                    top_wallets = app_state.pnl_engine.get_leaderboard(top_n=100)
                    seq = self.seq_numbers["leaderboard"]
                    await websocket.send_text(
                        json.dumps(
                            {
                                "stream": "leaderboard",
                                "type": "snapshot",
                                "seq": seq,
                                "data": [asdict(w) for w in top_wallets],
                            }
                        )
                    )

                if stream in ("paper", None):
                    seq = self.seq_numbers["paper"]
                    await websocket.send_text(
                        json.dumps(
                            {
                                "stream": "paper",
                                "type": "snapshot",
                                "seq": seq,
                                "data": app_state.get_paper_status_payload(asset_id),
                            }
                        )
                    )
        except Exception as e:
            logger.error(f"Error handling client message: {e}")

    async def _flush_loop(self, app_state: Any):
        """Periodic flush loop coalescing and pushing deltas at the fixed throttle rate."""
        logger.info(f"DeltaStreamManager flush loop started at {1.0 / self.interval:.0f} Hz")
        while self._running:
            t_start = time.perf_counter()
            try:
                # 1. Flush coalesced book deltas (prioritize active sim asset)
                if self._pending_book_deltas and self.active_connections:
                    deltas_copy = self._pending_book_deltas
                    self._pending_book_deltas = {}

                    by_asset: dict[str, list[dict[str, Any]]] = {}
                    for (asset_id, side_str, price), size in deltas_copy.items():
                        by_asset.setdefault(asset_id, []).append(
                            {
                                "side": side_str,
                                "price": price,
                                "size": size,
                            }
                        )

                    for asset_id, deltas in by_asset.items():
                        book = app_state.orderbooks.get(asset_id)
                        best_bid = book.best_bid if book else None
                        best_ask = book.best_ask if book else None
                        mid = book.mid if book else None
                        spread = book.spread if book else None
                        imbalance = book.imbalance(ticks=5) if book else 0.0

                        seq = self.next_seq("book")
                        await self.broadcast_raw(
                            {
                                "stream": "book",
                                "type": "delta",
                                "seq": seq,
                                "asset_id": asset_id,
                                "ts": time.time(),
                                "summary": {
                                    "best_bid": best_bid,
                                    "best_ask": best_ask,
                                    "mid": mid,
                                    "spread": spread,
                                    "imbalance": imbalance,
                                },
                                "deltas": deltas,
                            }
                        )

                # 2. Flush leaderboard updates (1.0s cadence across 100 active traders)
                now_t = time.perf_counter()
                if (
                    self._leaderboard_dirty
                    and (now_t - self._last_leaderboard_flush >= 1.0)
                    and self.active_connections
                ):
                    self._last_leaderboard_flush = now_t
                    self._leaderboard_dirty = False
                    top_wallets = app_state.pnl_engine.get_leaderboard(top_n=100)
                    seq = self.next_seq("leaderboard")
                    await self.broadcast_raw(
                        {
                            "stream": "leaderboard",
                            "type": "delta",
                            "seq": seq,
                            "ts": time.time(),
                            "wallets": [asdict(w) for w in top_wallets],
                        }
                    )

                # 3. Flush trade fills
                if self._pending_trades and self.active_connections:
                    trades_copy = self._pending_trades
                    self._pending_trades = []
                    seq = self.next_seq("trades")
                    await self.broadcast_raw(
                        {
                            "stream": "trades",
                            "type": "delta",
                            "seq": seq,
                            "ts": time.time(),
                            "trades": trades_copy,
                        }
                    )

                # 4. Flush paper trading updates
                if self._pending_paper_events and self.active_connections:
                    paper_copy = self._pending_paper_events
                    self._pending_paper_events = []
                    seq = self.next_seq("paper")
                    await self.broadcast_raw(
                        {
                            "stream": "paper",
                            "type": "delta",
                            "seq": seq,
                            "ts": time.time(),
                            "events": paper_copy,
                        }
                    )

                # 5. Flush live candle bar ticks
                if self._pending_candle_updates and self.active_connections:
                    candles_copy = self._pending_candle_updates
                    self._pending_candle_updates = {}
                    for asset_id, candle in candles_copy.items():
                        seq = self.next_seq("candles")
                        await self.broadcast_raw(
                            {
                                "stream": "candles",
                                "type": "delta",
                                "seq": seq,
                                "asset_id": asset_id,
                                "candle": candle,
                            }
                        )

            except Exception as e:
                logger.exception(f"Error in DeltaStreamManager flush loop: {e}")

            # Sleep remainder of interval
            elapsed = time.perf_counter() - t_start
            sleep_time = max(0.001, self.interval - elapsed)
            await asyncio.sleep(sleep_time)

    def start(self, app_state: Any):
        if not self._running:
            self._running = True
            self._flush_task = asyncio.create_task(self._flush_loop(app_state))

    def stop(self):
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()


# Global delta stream manager
stream_manager = DeltaStreamManager(throttle_hz=20.0)
