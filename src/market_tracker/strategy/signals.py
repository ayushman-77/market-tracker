"""Quantitative trading signals for prediction market orderbook and trade flow dynamics.

Includes:
1. ImbalanceSignal: Orderbook depth imbalance within X ticks of mid.
2. SmartMoneyFlowSignal: Real-time net flow follower of top-N PnL leaderboard wallets
   with strict lookahead-bias protection (evaluated strictly using historical data).
"""

from collections import deque
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
from numba import njit

from market_tracker.book.orderbook import L2Orderbook
from market_tracker.common.types import Side, Trade
from market_tracker.pnl.engine import PnLEngine


class SignalAction(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class SignalDecision:
    action: SignalAction
    signal_name: str
    asset_id: str
    confidence: float
    target_price: float
    target_size: float
    timestamp: float
    reason: str = ""
    metrics: dict[str, float] = field(default_factory=dict)

    @property
    def order_size(self) -> float:
        return self.target_size


@njit(fastmath=True, nogil=True)
def kernel_eval_imbalance(
    bids: np.ndarray,
    asks: np.ndarray,
    best_bid_idx: int,
    best_ask_idx: int,
    ticks: int,
    n_levels: int,
) -> tuple[float, float, float]:
    """Fast Numba calculation of bid depth, ask depth, and imbalance ratio."""
    bid_depth = 0.0
    if best_bid_idx >= 0:
        start_i = max(0, best_bid_idx - ticks)
        for i in range(start_i, best_bid_idx + 1):
            bid_depth += bids[i]

    ask_depth = 0.0
    if best_ask_idx >= 0:
        end_i = min(n_levels - 1, best_ask_idx + ticks)
        for i in range(best_ask_idx, end_i + 1):
            ask_depth += asks[i]

    total = bid_depth + ask_depth
    if total < 1e-12:
        return 0.0, 0.0, 0.0

    imbalance = (bid_depth - ask_depth) / total
    return imbalance, bid_depth, ask_depth


class ImbalanceSignal:
    """Signal 1: Evaluates orderbook depth imbalance within X ticks."""

    def __init__(
        self,
        threshold: float = 0.25,
        ticks: int = 5,
        min_depth: float = 20.0,
        order_size: float = 50.0,
    ):
        self.threshold = threshold
        self.ticks = ticks
        self.min_depth = min_depth
        self.order_size = order_size

    def evaluate(self, book: L2Orderbook, timestamp: float = 0.0) -> SignalDecision:
        ts_val = (
            timestamp.timestamp() if hasattr(timestamp, "timestamp") else float(timestamp or 0.0)
        )
        if book.best_bid_idx < 0 or book.best_ask_idx < 0:
            return SignalDecision(
                action=SignalAction.HOLD,
                signal_name="ImbalanceSignal",
                asset_id=book.asset_id,
                confidence=0.0,
                target_price=0.0,
                target_size=0.0,
                timestamp=ts_val,
                reason="No valid two-sided market",
            )

        imb, b_depth, a_depth = kernel_eval_imbalance(
            book.bids,
            book.asks,
            book.best_bid_idx,
            book.best_ask_idx,
            self.ticks,
            book.n_levels,
        )

        total_depth = b_depth + a_depth
        if total_depth < self.min_depth:
            return SignalDecision(
                action=SignalAction.HOLD,
                signal_name="ImbalanceSignal",
                asset_id=book.asset_id,
                confidence=0.0,
                target_price=0.0,
                target_size=0.0,
                timestamp=ts_val,
                reason=f"Insufficient depth ({total_depth:.1f} < {self.min_depth:.1f})",
                metrics={"imbalance": imb, "depth": total_depth},
            )

        if imb >= self.threshold:
            # Bullish pressure: cross ask or bid at best ask
            target_p = book.best_ask or 0.50
            return SignalDecision(
                action=SignalAction.BUY,
                signal_name="ImbalanceSignal",
                asset_id=book.asset_id,
                confidence=min(1.0, float(abs(imb))),
                target_price=target_p,
                target_size=self.order_size,
                timestamp=ts_val,
                reason=f"Bullish depth imbalance ({imb:+.2f} >= +{self.threshold:.2f})",
                metrics={"imbalance": imb, "bid_depth": b_depth, "ask_depth": a_depth},
            )
        elif imb <= -self.threshold:
            # Bearish pressure: hit bid at best bid
            target_p = book.best_bid or 0.50
            return SignalDecision(
                action=SignalAction.SELL,
                signal_name="ImbalanceSignal",
                asset_id=book.asset_id,
                confidence=min(1.0, float(abs(imb))),
                target_price=target_p,
                target_size=self.order_size,
                timestamp=ts_val,
                reason=f"Bearish depth imbalance ({imb:+.2f} <= -{self.threshold:.2f})",
                metrics={"imbalance": imb, "bid_depth": b_depth, "ask_depth": a_depth},
            )

        return SignalDecision(
            action=SignalAction.HOLD,
            signal_name="ImbalanceSignal",
            asset_id=book.asset_id,
            confidence=0.0,
            target_price=0.0,
            target_size=0.0,
            timestamp=ts_val,
            reason=f"Imbalance neutral ({imb:+.2f} within [{-self.threshold:.2f}, +{self.threshold:.2f}])",
            metrics={"imbalance": imb, "bid_depth": b_depth, "ask_depth": a_depth},
        )


@dataclass
class _FlowRecord:
    timestamp: float
    wallet: str
    asset_id: str
    net_usd: float


class SmartMoneyFlowSignal:
    """Signal 2: Follows net trade flow of top-N wallets from PnL leaderboard.

    Includes lookahead-bias check: leaderboard rankings are dynamically updated
    ONLY using historical data prior to the decision timestamp.
    """

    def __init__(
        self,
        pnl_engine: PnLEngine,
        top_n: int = 10,
        window_seconds: float = 60.0,
        flow_threshold_usd: float = 250.0,
        order_size: float = 50.0,
    ):
        self.pnl_engine = pnl_engine
        self.top_n = top_n
        self.window_seconds = window_seconds
        self.flow_threshold = flow_threshold_usd
        self.order_size = order_size

        # Rolling window of recent top-wallet flows: deque of _FlowRecord
        self.flow_history: deque[_FlowRecord] = deque()
        # Cached top wallet set with timestamp of last leaderboard refresh
        self._cached_top_wallets: set[str] = set()
        self._last_leaderboard_refresh: float = -1.0
        self._refresh_interval: float = 5.0  # seconds between leaderboard re-rankings

    def _get_historical_top_wallets(self, cur_time: float) -> set[str]:
        """Lookahead-Bias Protection: Get top wallets using strictly historical state."""
        # Refresh ranking periodically (every refresh_interval in simulation time)
        if (
            cur_time - self._last_leaderboard_refresh >= self._refresh_interval
            or not self._cached_top_wallets
        ):
            leaderboard = self.pnl_engine.get_leaderboard(top_n=self.top_n)
            self._cached_top_wallets = {entry.wallet for entry in leaderboard}
            self._last_leaderboard_refresh = cur_time
        return self._cached_top_wallets

    def on_trade(self, trade: Trade) -> SignalDecision | None:
        """Ingest trade tick and evaluate smart-money follower signal."""
        t_ts = trade.timestamp.timestamp()
        top_wallets = self._get_historical_top_wallets(t_ts)

        # Check if taker or maker is a smart wallet
        # Taker aggressive flow is weighted higher than maker passive liquidity
        trade_usd = trade.price * trade.size
        flow_delta = 0.0

        if trade.taker_wallet in top_wallets:
            # Smart money taker buy = positive flow; taker sell = negative flow
            flow_delta += trade_usd if trade.side == Side.BUY else -trade_usd
        elif trade.maker_wallet in top_wallets:
            # Smart money maker
            flow_delta += (trade_usd * 0.5) if trade.side == Side.SELL else (-trade_usd * 0.5)

        if abs(flow_delta) > 1e-6:
            self.flow_history.append(
                _FlowRecord(
                    timestamp=t_ts,
                    wallet=trade.taker_wallet
                    if trade.taker_wallet in top_wallets
                    else trade.maker_wallet,
                    asset_id=trade.asset_id,
                    net_usd=flow_delta,
                )
            )

        # Prune records outside rolling window
        cutoff = t_ts - self.window_seconds
        while self.flow_history and self.flow_history[0].timestamp < cutoff:
            self.flow_history.popleft()

        # Compute net smart flow for this asset
        asset_net_flow = sum(
            rec.net_usd for rec in self.flow_history if rec.asset_id == trade.asset_id
        )

        if asset_net_flow >= self.flow_threshold:
            return SignalDecision(
                action=SignalAction.BUY,
                signal_name="SmartMoneyFlowSignal",
                asset_id=trade.asset_id,
                confidence=min(1.0, float(asset_net_flow / (self.flow_threshold * 2.0))),
                target_price=trade.price,
                target_size=self.order_size,
                timestamp=t_ts,
                reason=f"Top-wallet net inflow ${asset_net_flow:.1f} >= ${self.flow_threshold:.1f}",
                metrics={"net_flow_usd": asset_net_flow},
            )
        elif asset_net_flow <= -self.flow_threshold:
            return SignalDecision(
                action=SignalAction.SELL,
                signal_name="SmartMoneyFlowSignal",
                asset_id=trade.asset_id,
                confidence=min(1.0, float(abs(asset_net_flow) / (self.flow_threshold * 2.0))),
                target_price=trade.price,
                target_size=self.order_size,
                timestamp=t_ts,
                reason=f"Top-wallet net outflow ${abs(asset_net_flow):.1f} >= ${self.flow_threshold:.1f}",
                metrics={"net_flow_usd": asset_net_flow},
            )

        return None

    def evaluate(
        self,
        trade: Trade | None = None,
        book: L2Orderbook | None = None,
        timestamp: object = None,
    ) -> SignalDecision | None:
        """Evaluate smart money follower signal on new trade ticks."""
        if trade is None:
            return None
        return self.on_trade(trade)
