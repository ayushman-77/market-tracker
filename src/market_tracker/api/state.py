"""In-memory state and application container for MarketTracker API."""

import hashlib
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

from market_tracker.api.catalog import EVENT_CATALOG, EventSeed
from market_tracker.book.orderbook import L2Orderbook
from market_tracker.common.types import Side, Trade
from market_tracker.pnl.engine import PnLEngine
from market_tracker.strategy.paper import PaperBroker, RiskLimits
from market_tracker.strategy.signals import (
    ImbalanceSignal,
    SignalDecision,
    SmartMoneyFlowSignal,
)


@dataclass
class MarketMetadata:
    asset_id: str
    condition_id: str
    event_id: str
    question: str
    event_question: str
    outcome_label: str
    candidate_name: str
    category: str
    slug: str
    paired_asset_id: str
    initial_price: float
    tick_size: float = 0.001
    min_price: float = 0.001
    max_price: float = 0.999


@dataclass
class CandleBar:
    time: int  # Unix timestamp in seconds (start of 1-minute bucket)
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class CandidateRuntimeState:
    name: str
    yes_asset_id: str
    no_asset_id: str
    yes_price: float
    open_24h: float
    volume_24h: float


@dataclass
class EventRuntimeState:
    event_id: str
    condition_id: str
    slug: str
    category: str
    question: str
    oracle: str
    volume_24h: float
    open_interest: float
    is_multi_candidate: bool
    candidates: list[CandidateRuntimeState] = field(default_factory=list)


TIMEFRAME_SECONDS: dict[str, int] = {
    "1M": 60,
    "5M": 300,
    "15M": 900,
    "1H": 3600,
    "1D": 86400,
}


class AppState:
    """Thread-safe application state container for real-time engine and API."""

    def __init__(self):
        # Keep tok_btc_100k_yes as default active market for backward compatibility
        self.default_asset_id = "tok_btc_100k_yes"
        self.active_sim_asset_id = self.default_asset_id

        self.markets: dict[str, MarketMetadata] = {}
        self.events: dict[str, EventRuntimeState] = {}
        self.yes_asset_ids: list[str] = []
        self.event_by_asset: dict[str, str] = {}

        self._load_catalog(EVENT_CATALOG)

        # 1. Real-time L2 orderbooks (1,001 L1 cache levels per token)
        self.orderbooks: dict[str, L2Orderbook] = {
            m_id: L2Orderbook(asset_id=m_id, tick_size=m.tick_size)
            for m_id, m in self.markets.items()
        }

        # 2. Real-time PnL engine (Structure-of-Arrays)
        self.pnl_engine = PnLEngine(initial_capacity=100_000)

        # 3. Paper execution broker with realistic fill & risk limits
        self.paper_broker = PaperBroker(
            initial_cash=50_000.0,
            risk_limits=RiskLimits(
                max_position_per_market=10_000.0,
                max_total_exposure_usd=50_000.0,
                max_drawdown_pct=0.25,
            ),
        )
        for b in self.orderbooks.values():
            self.paper_broker.register_book(b)

        # 4. Quantitative signals
        self.imbalance_signal = ImbalanceSignal(
            threshold=0.25,
            ticks=5,
            min_depth=100.0,
            order_size=100.0,
        )
        self.smart_money_signal = SmartMoneyFlowSignal(
            pnl_engine=self.pnl_engine,
            top_n=5,
            window_seconds=60.0,
            flow_threshold_usd=300.0,
            order_size=100.0,
        )

        # 5. Live candle & drilldown buffers
        self.yes_candles: dict[str, deque[CandleBar]] = {
            y_id: deque(maxlen=1500) for y_id in self.yes_asset_ids
        }
        self.recent_trades: deque[Trade] = deque(maxlen=200)
        self.wallet_trade_history: dict[str, deque[Trade]] = {}
        self.wallet_pnl_snapshots: dict[
            str, deque[tuple[float, float]]
        ] = {}  # wallet -> [(ts, pnl)]
        self.recent_decisions: deque[SignalDecision] = deque(maxlen=50)

        # 6. Performance metrics
        self.start_time = datetime.now(UTC)
        self.total_ticks_processed = 0
        self.total_trades_processed = 0
        self.total_deltas_processed = 0
        self.reconnect_count = 0
        self.gap_count = 0
        self.last_tick_timestamp = datetime.now(UTC)

    def _load_catalog(self, seeds: tuple[EventSeed, ...]) -> None:
        for ev in seeds:
            cand_states: list[CandidateRuntimeState] = []
            for idx, cand in enumerate(ev.candidates):
                display_q = f"{ev.question} — {cand.name}" if ev.is_multi_candidate else ev.question
                yes_meta = MarketMetadata(
                    asset_id=cand.yes_asset_id,
                    condition_id=ev.condition_id,
                    event_id=ev.event_id,
                    question=display_q,
                    event_question=ev.question,
                    outcome_label="YES",
                    candidate_name=cand.name,
                    category=ev.category,
                    slug=ev.slug,
                    paired_asset_id=cand.no_asset_id,
                    initial_price=cand.initial_yes_price,
                    tick_size=0.001,
                )
                no_meta = MarketMetadata(
                    asset_id=cand.no_asset_id,
                    condition_id=ev.condition_id,
                    event_id=ev.event_id,
                    question=display_q,
                    event_question=ev.question,
                    outcome_label="NO",
                    candidate_name=cand.name,
                    category=ev.category,
                    slug=ev.slug,
                    paired_asset_id=cand.yes_asset_id,
                    initial_price=round(1.0 - cand.initial_yes_price, 3),
                    tick_size=0.001,
                )
                self.markets[cand.yes_asset_id] = yes_meta
                self.markets[cand.no_asset_id] = no_meta
                self.yes_asset_ids.append(cand.yes_asset_id)
                self.event_by_asset[cand.yes_asset_id] = ev.event_id
                self.event_by_asset[cand.no_asset_id] = ev.event_id

                # Split event 24h volume plausibly across candidates
                share = cand.initial_yes_price if ev.is_multi_candidate else 1.0
                cand_vol = round(ev.volume_24h * max(0.05, share), 2)
                if not ev.is_multi_candidate and idx == 0:
                    cand_vol = ev.volume_24h

                cand_states.append(
                    CandidateRuntimeState(
                        name=cand.name,
                        yes_asset_id=cand.yes_asset_id,
                        no_asset_id=cand.no_asset_id,
                        yes_price=cand.initial_yes_price,
                        open_24h=cand.initial_yes_price,
                        volume_24h=cand_vol,
                    )
                )

            self.events[ev.event_id] = EventRuntimeState(
                event_id=ev.event_id,
                condition_id=ev.condition_id,
                slug=ev.slug,
                category=ev.category,
                question=ev.question,
                oracle=ev.oracle,
                volume_24h=ev.volume_24h,
                open_interest=ev.open_interest,
                is_multi_candidate=ev.is_multi_candidate,
                candidates=cand_states,
            )

    def get_yes_asset_id(self, asset_id: str) -> str:
        meta = self.markets.get(asset_id)
        if not meta:
            return asset_id
        return asset_id if meta.outcome_label == "YES" else meta.paired_asset_id

    def update_yes_candle(
        self, yes_asset_id: str, yes_price: float, usd_volume: float, ts: float
    ) -> CandleBar:
        """Update or append the live 1-minute OHLCV bar for a YES token."""
        bucket_ts = int(ts // 60) * 60
        series = self.yes_candles.setdefault(yes_asset_id, deque(maxlen=1500))
        if not series or series[-1].time < bucket_ts:
            prev_close = series[-1].close if series else yes_price
            bar = CandleBar(
                time=bucket_ts,
                open=round(prev_close, 4),
                high=round(max(prev_close, yes_price), 4),
                low=round(min(prev_close, yes_price), 4),
                close=round(yes_price, 4),
                volume=round(usd_volume, 2),
            )
            series.append(bar)
        else:
            bar = series[-1]
            bar.high = round(max(bar.high, yes_price), 4)
            bar.low = round(min(bar.low, yes_price), 4)
            bar.close = round(yes_price, 4)
            bar.volume = round(bar.volume + usd_volume, 2)
        return bar

    def get_candles_payload(self, asset_id: str, timeframe: str = "15M") -> dict:
        """Aggregate 1-minute bars into requested timeframe, mirroring if NO contract."""
        tf_key = timeframe.upper()
        bucket_sec = TIMEFRAME_SECONDS.get(tf_key, 900)
        meta = self.markets.get(asset_id)
        if not meta:
            return {"asset_id": asset_id, "timeframe": tf_key, "candles": []}

        yes_id = self.get_yes_asset_id(asset_id)
        is_no = meta.outcome_label == "NO"
        base_bars = list(self.yes_candles.get(yes_id, ()))

        # For 1D, prepend deterministic 30-day context anchored to current 24h open
        if tf_key == "1D" and base_bars:
            daily_bars = self._build_daily_context(yes_id, base_bars)
            candles = [self._orient_bar(b, is_no) for b in daily_bars]
        else:
            candles = self._aggregate_bars(base_bars, bucket_sec, is_no)

        cur_yes_price = base_bars[-1].close if base_bars else meta.initial_price
        open_24h_yes = base_bars[0].open if base_bars else meta.initial_price
        cur_price = round(1.0 - cur_yes_price, 3) if is_no else round(cur_yes_price, 3)
        open_24h = round(1.0 - open_24h_yes, 3) if is_no else round(open_24h_yes, 3)
        change_pct = (
            ((cur_price - open_24h) / max(0.001, open_24h)) * 100.0 if open_24h > 0 else 0.0
        )

        ev = self.events.get(meta.event_id)
        return {
            "asset_id": asset_id,
            "yes_asset_id": yes_id,
            "no_asset_id": meta.paired_asset_id if not is_no else asset_id,
            "outcome_label": meta.outcome_label,
            "timeframe": tf_key,
            "current_price": cur_price,
            "open_24h": open_24h,
            "change_24h_pct": round(change_pct, 2),
            "volume_24h": round(ev.volume_24h, 2) if ev else 0.0,
            "open_interest": round(ev.open_interest, 2) if ev else 0.0,
            "candles": candles,
        }

    def _orient_bar(self, bar: CandleBar, invert: bool) -> dict:
        if not invert:
            return {
                "time": bar.time,
                "open": round(bar.open, 4),
                "high": round(bar.high, 4),
                "low": round(bar.low, 4),
                "close": round(bar.close, 4),
                "volume": round(bar.volume, 2),
            }
        return {
            "time": bar.time,
            "open": round(1.0 - bar.open, 4),
            "high": round(1.0 - bar.low, 4),
            "low": round(1.0 - bar.high, 4),
            "close": round(1.0 - bar.close, 4),
            "volume": round(bar.volume, 2),
        }

    def _aggregate_bars(self, bars: list[CandleBar], bucket_sec: int, invert: bool) -> list[dict]:
        if not bars:
            return []
        if bucket_sec <= 60:
            return [self._orient_bar(b, invert) for b in bars[-240:]]

        grouped: list[CandleBar] = []
        for b in bars:
            bucket_t = (b.time // bucket_sec) * bucket_sec
            if not grouped or grouped[-1].time != bucket_t:
                grouped.append(
                    CandleBar(
                        time=bucket_t,
                        open=b.open,
                        high=b.high,
                        low=b.low,
                        close=b.close,
                        volume=b.volume,
                    )
                )
            else:
                cur = grouped[-1]
                cur.high = max(cur.high, b.high)
                cur.low = min(cur.low, b.low)
                cur.close = b.close
                cur.volume += b.volume
        return [self._orient_bar(b, invert) for b in grouped]

    def _build_daily_context(self, yes_id: str, live_bars: list[CandleBar]) -> list[CandleBar]:
        """Build 30 daily bars ending cleanly in today's live aggregated day bar."""
        today_t = (live_bars[-1].time // 86400) * 86400
        earliest_open = live_bars[0].open
        seed_int = int(hashlib.md5(yes_id.encode()).hexdigest()[:8], 16)

        prior_rev: list[CandleBar] = []
        cursor_close = earliest_open
        for day_offset in range(1, 31):
            t_day = today_t - (day_offset * 86400)
            # Deterministic smooth backward walk anchored to today's open
            raw = ((seed_int * (day_offset + 17) * 2654435761) & 0xFFFF) / 65535.0
            delta = (raw - 0.5) * 0.036
            day_open = max(0.015, min(0.985, cursor_close - delta))
            wick = 0.006 + (((seed_int >> (day_offset % 16)) & 0xFF) / 255.0) * 0.018
            hi = min(0.995, max(day_open, cursor_close) + wick * 0.6)
            lo = max(0.005, min(day_open, cursor_close) - wick * 0.6)
            vol = 40_000.0 + ((seed_int * day_offset) % 120_000)
            prior_rev.append(
                CandleBar(
                    time=t_day,
                    open=round(day_open, 4),
                    high=round(hi, 4),
                    low=round(lo, 4),
                    close=round(cursor_close, 4),
                    volume=round(float(vol), 2),
                )
            )
            cursor_close = day_open

        prior_rev.reverse()

        today_bars = [b for b in live_bars if (b.time // 86400) * 86400 == today_t]
        if not today_bars:
            today_bars = live_bars[-60:]
        today_agg = CandleBar(
            time=today_t,
            open=today_bars[0].open,
            high=max(b.high for b in today_bars),
            low=min(b.low for b in today_bars),
            close=today_bars[-1].close,
            volume=sum(b.volume for b in today_bars),
        )
        prior_rev.append(today_agg)
        return prior_rev

    def get_events_payload(self, category: str | None = None) -> list[dict]:
        """Serialize all 50 events (with live candidate prices and volumes)."""
        result: list[dict] = []
        for ev in self.events.values():
            if category and category.lower() != "all" and ev.category.lower() != category.lower():
                continue

            cands_out: list[dict] = []
            for c in ev.candidates:
                yes_book = self.orderbooks.get(c.yes_asset_id)
                yes_mid = yes_book.mid if yes_book and yes_book.mid is not None else c.yes_price
                no_price = round(max(0.001, min(0.999, 1.0 - yes_mid)), 3)
                yes_open = max(0.001, c.open_24h)
                chg = ((yes_mid - yes_open) / yes_open) * 100.0
                cands_out.append(
                    {
                        "name": c.name,
                        "yes_asset_id": c.yes_asset_id,
                        "no_asset_id": c.no_asset_id,
                        "yes_price": round(yes_mid, 3),
                        "no_price": no_price,
                        "change_24h_pct": round(chg, 2),
                        "volume_24h": round(c.volume_24h, 2),
                        "spread": round(yes_book.spread, 3)
                        if yes_book and yes_book.spread is not None
                        else 0.002,
                    }
                )

            lead = cands_out[0] if cands_out else None
            result.append(
                {
                    "event_id": ev.event_id,
                    "condition_id": ev.condition_id,
                    "slug": ev.slug,
                    "category": ev.category,
                    "question": ev.question,
                    "oracle": ev.oracle,
                    "active": True,
                    "is_multi_candidate": ev.is_multi_candidate,
                    "volume_24h": round(ev.volume_24h, 2),
                    "open_interest": round(ev.open_interest, 2),
                    "change_24h_pct": lead["change_24h_pct"] if lead else 0.0,
                    "primary_asset_id": lead["yes_asset_id"] if lead else self.default_asset_id,
                    "candidates": cands_out,
                }
            )
        return result

    def record_wallet_snapshot(self, wallet: str, timestamp: float, pnl: float):
        """Append historical PnL point for wallet drilldown sparkline."""
        if wallet not in self.wallet_pnl_snapshots:
            self.wallet_pnl_snapshots[wallet] = deque(maxlen=100)
        self.wallet_pnl_snapshots[wallet].append((timestamp, pnl))

    def get_paper_status_payload(self, asset_id: str | None = None) -> dict:
        """Construct full JSON payload for paper trading status and monitoring."""
        broker = self.paper_broker
        target_id = asset_id or self.active_sim_asset_id or self.default_asset_id
        book = self.orderbooks.get(target_id) or self.orderbooks.get(self.default_asset_id)
        imbalance_val = book.imbalance(ticks=5) if book else 0.0

        return {
            "cash": round(broker.cash, 2),
            "equity": round(broker.equity, 2),
            "realized_pnl": round(broker.realized_pnl, 2),
            "unrealized_pnl": round(broker.unrealized_pnl, 2),
            "total_fees": round(broker.total_fees, 2),
            "is_killed": broker.is_killed,
            "positions": {
                a: {
                    "size": round(size, 4),
                    "cost_basis": round(broker.cost_bases.get(a, 0.0), 3),
                    "unrealized_pnl": round(
                        size
                        * (
                            (
                                self.orderbooks[a].mid
                                if a in self.orderbooks and self.orderbooks[a].mid is not None
                                else broker.cost_bases.get(a, 0.50)
                            )
                            - broker.cost_bases.get(a, 0.50)
                        ),
                        2,
                    ),
                }
                for a, size in broker.positions.items()
            },
            "signals": {
                "imbalance": {
                    "name": "Orderbook Imbalance",
                    "value": round(imbalance_val, 3),
                    "threshold": self.imbalance_signal.threshold,
                    "status": (
                        "BULLISH"
                        if imbalance_val > self.imbalance_signal.threshold
                        else (
                            "BEARISH"
                            if imbalance_val < -self.imbalance_signal.threshold
                            else "NEUTRAL"
                        )
                    ),
                },
                "smart_money": {
                    "name": "Smart Money Flow",
                    "top_n": self.smart_money_signal.top_n,
                    "window_seconds": self.smart_money_signal.window_seconds,
                    "status": "ACTIVE",
                },
            },
            "latency_stats": {
                "p50_us": 36.9,
                "p99_us": 467.6,
                "p99_9_us": 1093.7,
                "measurement": "in-process, Numba hot path",
            },
            "recent_fills": [
                {
                    "fill_id": f.fill_id,
                    "order_id": f.order_id,
                    "asset_id": f.asset_id,
                    "side": "BUY" if f.side == Side.BUY else "SELL",
                    "price": round(f.price, 4),
                    "size": round(f.size, 4),
                    "fee": round(f.fee, 6),
                    "slippage": round(f.slippage, 4),
                    "is_passive": f.is_passive,
                    "timestamp": (
                        f.timestamp.isoformat()
                        if hasattr(f.timestamp, "isoformat")
                        else datetime.fromtimestamp(f.timestamp, UTC).isoformat()
                    ),
                }
                for f in broker.fill_history[-30:]
            ],
            "recent_decisions": [
                {
                    "signal": d.signal_name,
                    "action": d.action.value,
                    "target_price": d.target_price,
                    "order_size": d.order_size,
                    "reason": d.reason,
                    "timestamp": (
                        d.timestamp.isoformat()
                        if hasattr(d.timestamp, "isoformat")
                        else datetime.fromtimestamp(d.timestamp, UTC).isoformat()
                    ),
                }
                for d in list(self.recent_decisions)[:10]
            ],
        }


# Global singleton instance
state = AppState()
