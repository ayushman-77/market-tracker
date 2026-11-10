"""Real-time market feed generator and engine updater for live API push."""

import asyncio
import logging
import random
from datetime import UTC, datetime

import numpy as np

from market_tracker.api.delta_stream import stream_manager
from market_tracker.api.state import state
from market_tracker.common.types import Side, Trade, TradeSource

logger = logging.getLogger("market_tracker.feed")


class MarketFeedEngine:
    """Generates continuous real-time market data ticks and drives all internal engines."""

    def __init__(self):
        self._running = False
        self._task: asyncio.Task | None = None
        self._cur_price = 0.520
        self._wallets = [f"0x{i:04x}a78942b109e451b689c32f810e74b34{i:02x}" for i in range(1, 41)]
        self._trade_counter = 0
        self._event_counter = 0

    def prime_initial_state(self):
        """Populate initial orderbook and positions so the UI immediately has rich data."""
        logger.info("Priming initial orderbook and wallet positions...")
        book = state.orderbooks[state.default_asset_id]

        # Seed L2 book with 25 levels of bids and 25 levels of asks
        for offset in range(1, 26):
            p_bid = round(self._cur_price - (offset * 0.001), 3)
            p_ask = round(self._cur_price + (offset * 0.001), 3)
            size_bid = round(float(np.random.uniform(50.0, 800.0)), 1)
            size_ask = round(float(np.random.uniform(50.0, 800.0)), 1)
            book.apply_delta(Side.BUY, p_bid, size_bid)
            book.apply_delta(Side.SELL, p_ask, size_ask)

        # Seed initial wallet trades in PnLEngine
        now = datetime.now(UTC)
        for i, wallet in enumerate(self._wallets):
            # Give each wallet an initial trade history with realistic PnL spread
            asset_id = state.default_asset_id if i % 2 == 0 else "tok_btc_100k_no"
            is_buy = i % 3 != 0
            price = round(0.40 + (i * 0.005), 3)
            size = float(random.choice([100.0, 250.0, 500.0, 1000.0, 2000.0]))
            usd_val = price * size
            fee = round(usd_val * 0.001, 4)

            state.pnl_engine.apply_trade(
                wallet=wallet,
                asset_id=asset_id,
                is_buy=is_buy,
                price=price,
                qty=size,
                fee=fee,
                timestamp=now.timestamp() - (100 - i) * 60,
            )
            # Record initial sparkline history
            pos = state.pnl_engine.get_position(wallet, asset_id)
            if pos:
                state.record_wallet_snapshot(wallet, now.timestamp() - 60, pos.total_pnl)

        # Mark all positions to current price
        state.pnl_engine.mark_price(asset_id=state.default_asset_id, price=self._cur_price)
        state.pnl_engine.mark_price(
            asset_id="tok_btc_100k_no", price=round(1.0 - self._cur_price, 3)
        )
        stream_manager.mark_leaderboard_dirty()

    async def _feed_loop(self):
        """High-frequency background simulation loop driving the engine at 40-60 ticks/sec."""
        logger.info("MarketFeedEngine simulation loop running.")
        book = state.orderbooks[state.default_asset_id]

        while self._running:
            try:
                now_dt = datetime.now(UTC)
                now_ts = now_dt.timestamp()
                state.last_tick_timestamp = now_dt

                # Random walk price bounded in [0.20, 0.85]
                drift = np.random.normal(0, 0.0008)
                self._cur_price = round(max(0.200, min(0.850, self._cur_price + drift)), 3)

                # 70% Book deltas, 30% Trade ticks
                if random.random() < 0.30:
                    # Generate Trade tick
                    self._trade_counter += 1
                    maker = random.choice(self._wallets)
                    taker = random.choice([w for w in self._wallets if w != maker])
                    side = Side.BUY if random.random() < 0.52 else Side.SELL
                    qty = float(random.choice([25.0, 50.0, 100.0, 250.0, 500.0]))
                    usd_val = round(self._cur_price * qty, 2)
                    fee = round(self._cur_price * qty * 0.001 * 0.5, 4)

                    tr = Trade(
                        event_id=f"tr_{self._trade_counter:08d}",
                        condition_id=state.markets[state.default_asset_id].condition_id,
                        asset_id=state.default_asset_id,
                        outcome_idx=0,
                        maker_wallet=maker,
                        taker_wallet=taker,
                        side=side,
                        price=self._cur_price,
                        size=qty,
                        usd_value=usd_val,
                        fee=fee,
                        source=TradeSource.WS_CLOB,
                        tx_hash=f"0x{random.randint(10**10, 10**15):016x}",
                        timestamp=now_dt,
                    )

                    # Update PnL Engine for both maker and taker
                    state.pnl_engine.apply_trade(
                        wallet=taker,
                        asset_id=state.default_asset_id,
                        is_buy=(side == Side.BUY),
                        price=self._cur_price,
                        qty=qty,
                        fee=fee,
                        timestamp=now_ts,
                    )
                    state.pnl_engine.apply_trade(
                        wallet=maker,
                        asset_id=state.default_asset_id,
                        is_buy=(side != Side.BUY),
                        price=self._cur_price,
                        qty=qty,
                        fee=fee,
                        timestamp=now_ts,
                    )

                    # Fast-path MTM pass
                    state.pnl_engine.mark_price(
                        asset_id=state.default_asset_id, price=self._cur_price
                    )

                    # Circular buffer for UI
                    state.recent_trades.appendleft(tr)
                    state.wallet_trade_history.setdefault(taker, []).append(tr)
                    state.wallet_trade_history.setdefault(maker, []).append(tr)

                    # Record history for sparklines
                    pos_taker = state.pnl_engine.get_position(taker, state.default_asset_id)
                    if pos_taker:
                        state.record_wallet_snapshot(taker, now_ts, pos_taker.total_pnl)

                    # Update paper trading broker for passive fills
                    state.paper_broker.process_trade_tick(tr, book)

                    # Signal evaluation (Smart Money flow)
                    decision = state.smart_money_signal.evaluate(
                        trade=tr,
                        book=book,
                        timestamp=now_dt,
                    )
                    if decision and decision.action.value in ("BUY", "SELL"):
                        state.recent_decisions.appendleft(decision)
                        # Paper broker executes on signal
                        if decision.action.value == "BUY":
                            state.paper_broker.execute_market_order(
                                state.default_asset_id,
                                Side.BUY,
                                decision.order_size,
                                timestamp=now_ts,
                            )
                        elif decision.action.value == "SELL":
                            state.paper_broker.execute_market_order(
                                state.default_asset_id,
                                Side.SELL,
                                decision.order_size,
                                timestamp=now_ts,
                            )
                        stream_manager.queue_paper_update(
                            "signal",
                            {
                                "signal": decision.signal_name,
                                "action": decision.action.value,
                                "reason": decision.reason,
                                "price": decision.target_price,
                                "size": decision.order_size,
                            },
                        )

                    # Queue deltas
                    stream_manager.queue_trade(tr)
                    stream_manager.mark_leaderboard_dirty()
                    state.total_trades_processed += 1

                else:
                    # Generate Book Delta tick
                    self._event_counter += 1
                    side = Side.BUY if random.random() < 0.50 else Side.SELL
                    # Offset within +/- 15 ticks from mid
                    tick_offset = random.randint(-15, 15)
                    target_price = round(
                        max(0.010, min(0.990, self._cur_price + (tick_offset * 0.001))), 3
                    )

                    # 80% update/replenish, 20% cancel/depth reduction
                    if random.random() > 0.20:
                        size = round(float(random.uniform(20.0, 400.0)), 1)
                    else:
                        size = 0.0

                    book.apply_delta(side, target_price, size)
                    stream_manager.queue_book_delta(
                        state.default_asset_id, side, target_price, size
                    )

                    # Evaluate imbalance signal periodically
                    if self._event_counter % 5 == 0:
                        decision = state.imbalance_signal.evaluate(book, now_ts)
                        if decision and decision.action.value in ("BUY", "SELL"):
                            state.recent_decisions.appendleft(decision)
                            if decision.action.value == "BUY":
                                state.paper_broker.execute_market_order(
                                    state.default_asset_id,
                                    Side.BUY,
                                    decision.order_size,
                                    timestamp=now_ts,
                                )
                            elif decision.action.value == "SELL":
                                state.paper_broker.execute_market_order(
                                    state.default_asset_id,
                                    Side.SELL,
                                    decision.order_size,
                                    timestamp=now_ts,
                                )
                            stream_manager.queue_paper_update(
                                "signal",
                                {
                                    "signal": decision.signal_name,
                                    "action": decision.action.value,
                                    "reason": decision.reason,
                                    "price": decision.target_price,
                                    "size": decision.order_size,
                                },
                            )

                    state.total_deltas_processed += 1

                state.total_ticks_processed += 1

            except Exception as e:
                logger.exception(f"Error in MarketFeedEngine loop: {e}")

            # Sleep 15ms ~ 65 updates/sec
            await asyncio.sleep(0.015)

    def start(self):
        if not self._running:
            self.prime_initial_state()
            self._running = True
            self._task = asyncio.create_task(self._feed_loop())

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()


# Global feed engine instance
feed_engine = MarketFeedEngine()
