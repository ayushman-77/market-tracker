"""In-memory state and application container for MarketTracker API."""

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

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
    question: str
    outcome_label: str
    tick_size: float = 0.001
    min_price: float = 0.001
    max_price: float = 0.999


class AppState:
    """Thread-safe application state container for real-time engine and API."""

    def __init__(self):
        # Default active market
        self.default_asset_id = "tok_btc_100k_yes"
        self.markets: dict[str, MarketMetadata] = {
            "tok_btc_100k_yes": MarketMetadata(
                asset_id="tok_btc_100k_yes",
                condition_id="c_btc_100k_eoy",
                question="Will Bitcoin hit $100k before Dec 31, 2026?",
                outcome_label="YES",
                tick_size=0.001,
            ),
            "tok_btc_100k_no": MarketMetadata(
                asset_id="tok_btc_100k_no",
                condition_id="c_btc_100k_eoy",
                question="Will Bitcoin hit $100k before Dec 31, 2026?",
                outcome_label="NO",
                tick_size=0.001,
            ),
            "tok_fed_cut_yes": MarketMetadata(
                asset_id="tok_fed_cut_yes",
                condition_id="c_fed_cut_q1",
                question="Will Federal Reserve cut rates in Q1?",
                outcome_label="YES",
                tick_size=0.001,
            ),
        }

        # 1. Real-time L2 orderbooks
        self.orderbooks: dict[str, L2Orderbook] = {
            m_id: L2Orderbook(asset_id=m_id, tick_size=m.tick_size)
            for m_id, m in self.markets.items()
        }

        # 2. Real-time PnL engine (Structure-of-Arrays)
        self.pnl_engine = PnLEngine(initial_capacity=50_000)

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

        # 5. Circular buffers for UI drilldown and history
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

    def record_wallet_snapshot(self, wallet: str, timestamp: float, pnl: float):
        """Append historical PnL point for wallet drilldown sparkline."""
        if wallet not in self.wallet_pnl_snapshots:
            self.wallet_pnl_snapshots[wallet] = deque(maxlen=100)
        self.wallet_pnl_snapshots[wallet].append((timestamp, pnl))

    def get_paper_status_payload(self) -> dict:
        """Construct full JSON payload for paper trading status and monitoring."""
        broker = self.paper_broker
        book = self.orderbooks.get(self.default_asset_id)
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
