"""Real-time market feed generator and engine updater for live API push."""

import asyncio
import logging
import random
from datetime import UTC, datetime

import numpy as np

from market_tracker.api.delta_stream import stream_manager
from market_tracker.api.state import CandleBar, state
from market_tracker.common.types import Side, Trade, TradeSource

logger = logging.getLogger("market_tracker.feed")


class MarketFeedEngine:
    """Generates continuous real-time market data ticks across 50 markets and 100 traders."""

    def __init__(self):
        self._running = False
        self._task: asyncio.Task | None = None
        # 100 distinct simulated EVM trader addresses
        self._wallets = [f"0x{i:04x}a78942b109e451b689c32f810e74b34{i:05x}" for i in range(1, 101)]
        self._prices: dict[str, float] = {
            meta.asset_id: meta.initial_price
            for meta in state.markets.values()
            if meta.outcome_label == "YES"
        }
        self._trade_counter = 0
        self._event_counter = 0
        self._bg_cursor = 0
        self._primed = False

    def _seed_book_around(self, asset_id: str, mid_price: float) -> None:
        book = state.orderbooks[asset_id]
        mid_clamped = max(0.030, min(0.970, mid_price))
        bids: list[tuple[float, float]] = []
        asks: list[tuple[float, float]] = []
        for offset in range(1, 26):
            p_bid = round(mid_clamped - (offset * 0.001), 3)
            p_ask = round(mid_clamped + (offset * 0.001), 3)
            if p_bid >= 0.001:
                bids.append((p_bid, round(float(np.random.uniform(50.0, 800.0)), 1)))
            if p_ask <= 0.999:
                asks.append((p_ask, round(float(np.random.uniform(50.0, 800.0)), 1)))
        book.apply_snapshot(bids, asks)

    def _seed_candles(self) -> None:
        """Seed 1,440 1-minute historical bars (24h) per YES token in vectorized NumPy."""
        n_bars = 1440
        now_ts = int(datetime.now(UTC).timestamp() // 60) * 60
        start_ts = now_ts - ((n_bars - 1) * 60)

        rng = np.random.default_rng(42)
        for ev in state.events.values():
            for cand in ev.candidates:
                y_id = cand.yes_asset_id
                target_end = self._prices.get(y_id, cand.yes_price)

                # Generate zero-mean Brownian bridge ending exactly near initial_yes_price
                steps = rng.normal(0.0, 0.0022, size=n_bars)
                walk = np.cumsum(steps)
                # Shift curve so final close hits target_end while keeping realistic 24h drift
                anchor_drift = rng.uniform(-0.045, 0.045)
                trend = np.linspace(0.0, anchor_drift, n_bars)
                raw_closes = (target_end - anchor_drift) + (walk - walk[-1]) + trend
                closes = np.clip(np.round(raw_closes, 4), 0.015, 0.985)
                closes[-1] = round(target_end, 4)

                opens = np.empty(n_bars, dtype=np.float64)
                opens[0] = np.clip(round(closes[0] - rng.uniform(-0.003, 0.003), 4), 0.015, 0.985)
                opens[1:] = closes[:-1]

                wicks = rng.uniform(0.001, 0.006, size=n_bars)
                highs = np.clip(np.round(np.maximum(opens, closes) + wicks, 4), 0.015, 0.995)
                lows = np.clip(np.round(np.minimum(opens, closes) - wicks, 4), 0.005, 0.985)

                # Realistic wavy intraday volume
                phase = np.linspace(0.0, 6.0 * np.pi, n_bars)
                vols = np.round(
                    (cand.volume_24h / n_bars)
                    * (0.45 + 0.55 * (0.5 + 0.5 * np.sin(phase + rng.uniform(0, 3))))
                    * rng.uniform(0.75, 1.35, size=n_bars),
                    2,
                )

                buf = state.yes_candles[y_id]
                buf.clear()
                for idx in range(n_bars):
                    buf.append(
                        CandleBar(
                            time=start_ts + (idx * 60),
                            open=float(opens[idx]),
                            high=float(highs[idx]),
                            low=float(lows[idx]),
                            close=float(closes[idx]),
                            volume=float(vols[idx]),
                        )
                    )

                cand.open_24h = float(opens[0])
                cand.yes_price = float(closes[-1])

    def prime_initial_state(self, force: bool = False):
        """Populate initial orderbooks, 24h candlesticks, and 100 trader positions."""
        if self._primed and not force:
            return
        self._primed = True

        logger.info(
            "Priming L2 orderbooks across 50 markets, 24h candles, and 100 trader positions..."
        )
        np.random.seed(42)

        # 1. Seed orderbooks for every YES and NO contract across all 50 events
        for ev in state.events.values():
            for cand in ev.candidates:
                yes_p = self._prices[cand.yes_asset_id]
                self._seed_book_around(cand.yes_asset_id, yes_p)
                self._seed_book_around(cand.no_asset_id, round(1.0 - yes_p, 3))

        # 2. Seed 24h OHLCV candles
        self._seed_candles()

        # 3. Seed initial trades for all 100 traders across domains & contracts
        now = datetime.now(UTC)
        seed_rng = random.Random(42)
        popular_assets = [
            "tok_btc_100k_yes",
            "tok_btc_100k_no",
            "tok_fed_cut_q1_yes" if "tok_fed_cut_q1_yes" in state.markets else "tok_fed_cut_yes",
            *state.yes_asset_ids[:30],
        ]
        valid_assets = [a for a in popular_assets if a in state.markets]

        for i, wallet in enumerate(self._wallets):
            # Ensure top trader drilldown always covers default BTC market + diverse markets
            chosen_assets = [
                "tok_btc_100k_yes" if i % 2 == 0 else "tok_btc_100k_no"
            ] + seed_rng.sample(valid_assets, k=min(3, len(valid_assets)))
            for j, asset_id in enumerate(chosen_assets):
                meta = state.markets[asset_id]
                base_p = self._prices.get(state.get_yes_asset_id(asset_id), 0.50)
                if meta.outcome_label == "NO":
                    base_p = 1.0 - base_p
                entry_price = round(
                    max(0.020, min(0.980, base_p + seed_rng.uniform(-0.045, 0.045))), 3
                )
                is_buy = (i + j) % 3 != 0
                size = float(seed_rng.choice([100.0, 250.0, 500.0, 1000.0, 2000.0]))
                usd_val = round(entry_price * size, 2)
                fee = round(usd_val * 0.001, 4)
                ts = now.timestamp() - (120 - i) * 45 - (j * 20)

                state.pnl_engine.apply_trade(
                    wallet=wallet,
                    asset_id=asset_id,
                    is_buy=is_buy,
                    price=entry_price,
                    qty=size,
                    fee=fee,
                    timestamp=ts,
                )

                tr = Trade(
                    event_id=f"seed_{i:03d}_{j}",
                    condition_id=meta.condition_id,
                    asset_id=asset_id,
                    outcome_idx=0 if meta.outcome_label == "YES" else 1,
                    maker_wallet=self._wallets[(i + 17) % len(self._wallets)],
                    taker_wallet=wallet,
                    side=Side.BUY if is_buy else Side.SELL,
                    price=entry_price,
                    size=size,
                    usd_value=usd_val,
                    fee=fee,
                    source=TradeSource.REST_BACKFILL,
                    tx_hash=f"0xseed{i:04x}{j:02x}",
                    timestamp=datetime.fromtimestamp(ts, tz=UTC),
                )
                state.wallet_trade_history.setdefault(wallet, []).append(tr)
                if len(state.recent_trades) < 50:
                    state.recent_trades.appendleft(tr)

                pos = state.pnl_engine.get_position(wallet, asset_id)
                if pos:
                    state.record_wallet_snapshot(wallet, now.timestamp() - 60, pos.total_pnl)

        # 4. Mark every token to its live price
        for ev in state.events.values():
            for cand in ev.candidates:
                yes_p = self._prices[cand.yes_asset_id]
                state.pnl_engine.mark_price(asset_id=cand.yes_asset_id, price=yes_p)
                state.pnl_engine.mark_price(asset_id=cand.no_asset_id, price=round(1.0 - yes_p, 3))

        stream_manager.mark_leaderboard_dirty()

    def _step_yes_price(self, yes_id: str) -> float:
        cur = self._prices[yes_id]
        ev_id = state.event_by_asset.get(yes_id)
        ev = state.events.get(ev_id) if ev_id else None

        drift = float(np.random.normal(0.0, 0.0012))
        new_p = round(max(0.015, min(0.985, cur + drift)), 3)
        self._prices[yes_id] = new_p

        if ev:
            for cand in ev.candidates:
                if cand.yes_asset_id == yes_id:
                    cand.yes_price = new_p
                    break

            # Keep multi-candidate mutually exclusive YES sum near 1.00
            if ev.is_multi_candidate and len(ev.candidates) > 1:
                total = sum(self._prices[c.yes_asset_id] for c in ev.candidates)
                if abs(total - 1.0) > 0.015 and total > 0:
                    for cand in ev.candidates:
                        adjusted = round(
                            max(0.010, min(0.960, self._prices[cand.yes_asset_id] / total)), 3
                        )
                        self._prices[cand.yes_asset_id] = adjusted
                        cand.yes_price = adjusted

        return self._prices[yes_id]

    def _emit_candle_if_active(self, yes_id: str, bar: CandleBar) -> None:
        active_id = state.active_sim_asset_id
        active_yes = state.get_yes_asset_id(active_id)
        if yes_id != active_yes:
            return

        active_meta = state.markets.get(active_id)
        if active_meta and active_meta.outcome_label == "NO":
            payload = {
                "time": bar.time,
                "open": round(1.0 - bar.open, 4),
                "high": round(1.0 - bar.low, 4),
                "low": round(1.0 - bar.high, 4),
                "close": round(1.0 - bar.close, 4),
                "volume": round(bar.volume, 2),
            }
        else:
            payload = {
                "time": bar.time,
                "open": round(bar.open, 4),
                "high": round(bar.high, 4),
                "low": round(bar.low, 4),
                "close": round(bar.close, 4),
                "volume": round(bar.volume, 2),
            }
        stream_manager.queue_candle_update(active_id, payload)

    def _sync_book_around_price(self, asset_id: str, price: float, queue_ws: bool) -> None:
        book = state.orderbooks[asset_id]
        # Maintain tight best bid / best ask around updated mid price
        spread_half = 0.001
        bid_p = round(max(0.001, price - spread_half), 3)
        ask_p = round(min(0.999, price + spread_half), 3)

        # Prune stale crossed quotes cleanly if price shifted across ticks
        if book.best_bid is not None and book.best_bid >= ask_p:
            p_clear = book.best_bid
            while p_clear >= ask_p:
                if book.bids[book.price_to_idx(p_clear)] > 0:
                    book.apply_delta(Side.BUY, p_clear, 0.0)
                    if queue_ws:
                        stream_manager.queue_book_delta(asset_id, Side.BUY, p_clear, 0.0)
                p_clear = round(p_clear - 0.001, 3)

        if book.best_ask is not None and book.best_ask <= bid_p:
            p_clear = book.best_ask
            while p_clear <= bid_p:
                if book.asks[book.price_to_idx(p_clear)] > 0:
                    book.apply_delta(Side.SELL, p_clear, 0.0)
                    if queue_ws:
                        stream_manager.queue_book_delta(asset_id, Side.SELL, p_clear, 0.0)
                p_clear = round(p_clear + 0.001, 3)

        side = Side.BUY if random.random() < 0.50 else Side.SELL
        offset = random.randint(1, 14)
        target_p = (
            round(max(0.001, price - offset * 0.001), 3)
            if side == Side.BUY
            else round(min(0.999, price + offset * 0.001), 3)
        )
        size = round(float(random.uniform(35.0, 420.0)), 1) if random.random() > 0.15 else 0.0
        book.apply_delta(side, target_p, size)
        if queue_ws:
            stream_manager.queue_book_delta(asset_id, side, target_p, size)

        # Ensure inside top-of-book stays populated
        if book.best_bid is None or abs(price - book.best_bid) > 0.004:
            sz_b = round(float(random.uniform(120.0, 350.0)), 1)
            book.apply_delta(Side.BUY, bid_p, sz_b)
            if queue_ws:
                stream_manager.queue_book_delta(asset_id, Side.BUY, bid_p, sz_b)
        if book.best_ask is None or abs(book.best_ask - price) > 0.004:
            sz_a = round(float(random.uniform(120.0, 350.0)), 1)
            book.apply_delta(Side.SELL, ask_p, sz_a)
            if queue_ws:
                stream_manager.queue_book_delta(asset_id, Side.SELL, ask_p, sz_a)

    async def _feed_loop(self):
        """High-frequency simulation loop driving active chart/book and all 50 markets."""
        logger.info("MarketFeedEngine simulation loop running (50 events, 100 traders).")

        while self._running:
            try:
                now_dt = datetime.now(UTC)
                now_ts = now_dt.timestamp()
                state.last_tick_timestamp = now_dt

                # Focus ~60% of ticks on the actively viewed market so UI charts/books feel instant;
                # rotate remaining ~40% smoothly across all 50 questions & 5 domains.
                active_id = state.active_sim_asset_id
                active_yes = state.get_yes_asset_id(active_id)
                if random.random() < 0.60 and active_yes in self._prices:
                    yes_id = active_yes
                else:
                    yes_id = state.yes_asset_ids[self._bg_cursor % len(state.yes_asset_ids)]
                    self._bg_cursor += 1

                meta_yes = state.markets[yes_id]
                no_id = meta_yes.paired_asset_id
                yes_price = self._step_yes_price(yes_id)
                no_price = round(1.0 - yes_price, 3)

                is_active_pair = active_id in (yes_id, no_id)
                emit_asset = active_id if is_active_pair else yes_id
                emit_price = no_price if emit_asset == no_id else yes_price
                book = state.orderbooks[emit_asset]

                # 35% Trade ticks, 65% L2 Book delta ticks
                if random.random() < 0.35:
                    self._trade_counter += 1
                    maker = random.choice(self._wallets)
                    taker = random.choice([w for w in self._wallets if w != maker])
                    side = Side.BUY if random.random() < 0.52 else Side.SELL
                    qty = float(random.choice([25.0, 50.0, 100.0, 250.0, 500.0]))
                    usd_val = round(emit_price * qty, 2)
                    fee = round(usd_val * 0.001 * 0.5, 4)

                    tr = Trade(
                        event_id=f"tr_{self._trade_counter:08d}",
                        condition_id=meta_yes.condition_id,
                        asset_id=emit_asset,
                        outcome_idx=0 if emit_asset == yes_id else 1,
                        maker_wallet=maker,
                        taker_wallet=taker,
                        side=side,
                        price=emit_price,
                        size=qty,
                        usd_value=usd_val,
                        fee=fee,
                        source=TradeSource.WS_CLOB,
                        tx_hash=f"0x{random.randint(10**10, 10**15):016x}",
                        timestamp=now_dt,
                    )

                    # Update PnL Engine for both peer-to-peer counterparties (100 traders)
                    state.pnl_engine.apply_trade(
                        wallet=taker,
                        asset_id=emit_asset,
                        is_buy=(side == Side.BUY),
                        price=emit_price,
                        qty=qty,
                        fee=fee,
                        timestamp=now_ts,
                    )
                    state.pnl_engine.apply_trade(
                        wallet=maker,
                        asset_id=emit_asset,
                        is_buy=(side != Side.BUY),
                        price=emit_price,
                        qty=qty,
                        fee=fee,
                        timestamp=now_ts,
                    )

                    # Mark paired outcomes to latest prices
                    state.pnl_engine.mark_price(asset_id=yes_id, price=yes_price)
                    state.pnl_engine.mark_price(asset_id=no_id, price=no_price)

                    # Update candle bar & event volume
                    bar = state.update_yes_candle(yes_id, yes_price, usd_val, now_ts)
                    ev = state.events.get(meta_yes.event_id)
                    if ev:
                        ev.volume_24h = round(ev.volume_24h + usd_val, 2)
                        for c in ev.candidates:
                            if c.yes_asset_id == yes_id:
                                c.volume_24h = round(c.volume_24h + usd_val, 2)
                                break
                    self._emit_candle_if_active(yes_id, bar)

                    state.recent_trades.appendleft(tr)
                    state.wallet_trade_history.setdefault(taker, []).append(tr)
                    state.wallet_trade_history.setdefault(maker, []).append(tr)

                    pos_taker = state.pnl_engine.get_position(taker, emit_asset)
                    if pos_taker:
                        state.record_wallet_snapshot(taker, now_ts, pos_taker.total_pnl)

                    state.paper_broker.process_trade_tick(tr, book)

                    if is_active_pair:
                        decision = state.smart_money_signal.evaluate(
                            trade=tr,
                            book=book,
                            timestamp=now_dt,
                        )
                        if decision and decision.action.value in ("BUY", "SELL"):
                            state.recent_decisions.appendleft(decision)
                            order_side = Side.BUY if decision.action.value == "BUY" else Side.SELL
                            state.paper_broker.execute_market_order(
                                emit_asset,
                                order_side,
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
                        stream_manager.queue_trade(tr)

                    stream_manager.mark_leaderboard_dirty()
                    state.total_trades_processed += 1

                else:
                    self._event_counter += 1
                    self._sync_book_around_price(yes_id, yes_price, queue_ws=(active_id == yes_id))
                    self._sync_book_around_price(no_id, no_price, queue_ws=(active_id == no_id))

                    if is_active_pair:
                        bar = state.update_yes_candle(yes_id, yes_price, 0.0, now_ts)
                        self._emit_candle_if_active(yes_id, bar)

                        if self._event_counter % 5 == 0:
                            decision = state.imbalance_signal.evaluate(book, now_ts)
                            if decision and decision.action.value in ("BUY", "SELL"):
                                state.recent_decisions.appendleft(decision)
                                order_side = (
                                    Side.BUY if decision.action.value == "BUY" else Side.SELL
                                )
                                state.paper_broker.execute_market_order(
                                    emit_asset,
                                    order_side,
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
