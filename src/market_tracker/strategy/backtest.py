"""Event-driven replay backtester sharing identical execution code path with paper trading.

Replays recorded book and trade ticks in exact timestamp order, evaluating signals,
routing orders through the PaperBroker, and measuring in-process tick-to-order latency.
"""

import math
import time
from dataclasses import dataclass, field

import numpy as np

from market_tracker.book.orderbook import L2Orderbook
from market_tracker.common.logging import logger
from market_tracker.common.types import BookEvent, Side, Trade
from market_tracker.pnl.engine import PnLEngine
from market_tracker.strategy.paper import PaperBroker
from market_tracker.strategy.signals import ImbalanceSignal, SignalAction, SmartMoneyFlowSignal


@dataclass
class BacktestReport:
    total_events_processed: int
    total_fills: int
    winning_fills: int
    losing_fills: int
    hit_rate: float
    total_volume_usd: float
    turnover: float
    initial_cash: float
    final_equity: float
    net_pnl: float
    total_fees_paid: float
    return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    tick_to_order_p50_us: float
    tick_to_order_p99_us: float
    tick_to_order_p99_9_us: float
    equity_curve: list[tuple[float, float]] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "=" * 70,
            "MARKETTRACKER REPLAY BACKTEST SUMMARY",
            "=" * 70,
            f"Events Processed:         {self.total_events_processed:,}",
            f"Total Fills Executed:     {self.total_fills:,} (Wins: {self.winning_fills:,}, Losses: {self.losing_fills:,})",
            f"Hit Rate:                 {self.hit_rate * 100:.1f}%",
            f"Total Traded Volume:      ${self.total_volume_usd:,.2f}",
            f"Portfolio Turnover:       {self.turnover:.2f}x",
            f"Initial Capital Base:     ${self.initial_cash:,.2f}",
            f"Final Portfolio Equity:   ${self.final_equity:,.2f}",
            f"Net PnL (After Fees):     ${self.net_pnl:,.2f} ({self.return_pct:+.2f}%)",
            f"Total Fees Paid:          ${self.total_fees_paid:,.2f}",
            f"Max Portfolio Drawdown:   {self.max_drawdown_pct * 100:.2f}%",
            f"Sharpe Ratio (Annualized): {self.sharpe_ratio:.2f} (Note: prediction markets violate normal distribution)",
            "-" * 70,
            "TICK-TO-ORDER LATENCY (In-Process, Numba Hot Path):",
            f"  -> p50:   {self.tick_to_order_p50_us:8.3f} μs",
            f"  -> p99:   {self.tick_to_order_p99_us:8.3f} μs",
            f"  -> p99.9: {self.tick_to_order_p99_9_us:8.3f} μs",
            "=" * 70,
        ]
        return "\n".join(lines)


class ReplayBacktester:
    """Event-driven backtester executing the exact same trading logic as live paper trading."""

    def __init__(
        self,
        broker: PaperBroker,
        imbalance_signal: ImbalanceSignal | None = None,
        smart_money_signal: SmartMoneyFlowSignal | None = None,
        pnl_engine: PnLEngine | None = None,
    ):
        self.broker = broker
        self.imbalance_signal = imbalance_signal or ImbalanceSignal()
        self.smart_money_signal = smart_money_signal
        self.pnl_engine = pnl_engine

        # Tick-to-order latency tracking in nanoseconds
        self.latencies_ns: list[int] = []

    def run(self, events: list[Trade | BookEvent]) -> BacktestReport:
        """Run event-driven backtest over chronological event sequence."""
        # Ensure chronological ordering
        events_sorted = sorted(
            events,
            key=lambda e: (
                e.timestamp.timestamp() if hasattr(e.timestamp, "timestamp") else float(e.timestamp)
            ),
        )

        n_events = len(events_sorted)
        logger.info(f"Starting event-driven replay backtest over {n_events:,} events...")

        for ev in events_sorted:
            t_ts = (
                ev.timestamp.timestamp()
                if hasattr(ev.timestamp, "timestamp")
                else float(ev.timestamp)
            )

            if isinstance(ev, BookEvent):
                # Book delta event
                book = self.broker.books.get(ev.asset_id)
                if not book:
                    book = L2Orderbook(asset_id=ev.asset_id, tick_size=0.001)
                    self.broker.register_book(book)

                book.apply_delta(ev.side, ev.price, ev.size)

                # Measure tick-to-order latency on signal evaluation & decision
                t0 = time.perf_counter_ns()
                decision = self.imbalance_signal.evaluate(book, timestamp=t_ts)
                if decision.action in (SignalAction.BUY, SignalAction.SELL):
                    t1 = time.perf_counter_ns()
                    self.latencies_ns.append(t1 - t0)

                    # Route order through the exact same paper broker
                    side = Side.BUY if decision.action == SignalAction.BUY else Side.SELL
                    self.broker.execute_market_order(
                        asset_id=decision.asset_id,
                        side=side,
                        size=decision.target_size,
                        timestamp=t_ts,
                    )

            elif isinstance(ev, Trade):
                # 1. First trigger passive fills on the trade tick
                self.broker.on_trade_event(ev)

                # 2. Update real-time PnL engine for leaderboard tracking (lookahead-bias free)
                if self.pnl_engine:
                    self.pnl_engine.apply_trade(
                        wallet=ev.taker_wallet,
                        asset_id=ev.asset_id,
                        is_buy=(ev.side == Side.BUY),
                        price=ev.price,
                        qty=ev.size,
                        fee=ev.fee,
                        timestamp=t_ts,
                    )

                # 3. Evaluate smart money flow signal if configured
                if self.smart_money_signal:
                    t0 = time.perf_counter_ns()
                    decision = self.smart_money_signal.on_trade(ev)
                    if decision and decision.action in (SignalAction.BUY, SignalAction.SELL):
                        t1 = time.perf_counter_ns()
                        self.latencies_ns.append(t1 - t0)

                        side = Side.BUY if decision.action == SignalAction.BUY else Side.SELL
                        self.broker.execute_market_order(
                            asset_id=decision.asset_id,
                            side=side,
                            size=decision.target_size,
                            timestamp=t_ts,
                        )

        return self._compile_report(n_events)

    def _compile_report(self, n_events: int) -> BacktestReport:
        """Calculate financial performance metrics and tick-to-order latency distribution."""
        final_eq = self.broker.get_portfolio_equity()
        init_eq = self.broker.initial_cash
        net_pnl = final_eq - init_eq
        ret_pct = (net_pnl / init_eq) * 100.0 if init_eq > 0 else 0.0

        # Compute volume and win/loss hit rate from executed fills
        fills = self.broker.fill_history
        n_fills = len(fills)
        tot_vol = sum(f.price * f.size for f in fills)
        turnover = tot_vol / init_eq if init_eq > 0 else 0.0

        # Classify trade outcomes: buy vs sell price comparisons
        wins = 0
        losses = 0
        for i in range(1, len(fills)):
            prev = fills[i - 1]
            curr = fills[i]
            if prev.asset_id == curr.asset_id and prev.side != curr.side:
                # Round trip completed
                pnl = (
                    (curr.price - prev.price) * curr.size
                    if prev.side == Side.BUY
                    else (prev.price - curr.price) * curr.size
                )
                if pnl > 0:
                    wins += 1
                elif pnl < 0:
                    losses += 1

        hit_rate = (wins / (wins + losses)) if (wins + losses) > 0 else 0.50

        # Calculate max drawdown from equity curve
        curve = self.broker.equity_curve
        peak = init_eq
        max_dd = 0.0
        for _ts, eq in curve:
            if eq > peak:
                peak = eq
            if peak > 0:
                dd = (peak - eq) / peak
                if dd > max_dd:
                    max_dd = dd

        # Calculate Sharpe-like ratio
        # Sub-sample equity series to compute period returns
        sharpe = 0.0
        if len(curve) > 5:
            eq_values = np.array([eq for _, eq in curve])
            diffs = np.diff(eq_values)
            rets = diffs / eq_values[:-1]
            std_ret = np.std(rets)
            if std_ret > 1e-9:
                mean_ret = np.mean(rets)
                # Annualization factor for high-frequency prediction market intervals
                sharpe = float((mean_ret / std_ret) * math.sqrt(252 * 24 * 60))

        # Latency percentiles in microseconds
        if self.latencies_ns:
            lat_arr = np.array(self.latencies_ns) / 1_000.0
            p50 = float(np.percentile(lat_arr, 50))
            p99 = float(np.percentile(lat_arr, 99))
            p99_9 = float(np.percentile(lat_arr, 99.9))
        else:
            p50, p99, p99_9 = 0.0, 0.0, 0.0

        return BacktestReport(
            total_events_processed=n_events,
            total_fills=n_fills,
            winning_fills=wins,
            losing_fills=losses,
            hit_rate=hit_rate,
            total_volume_usd=tot_vol,
            turnover=turnover,
            initial_cash=init_eq,
            final_equity=final_eq,
            net_pnl=net_pnl,
            total_fees_paid=self.broker.total_fees,
            return_pct=ret_pct,
            sharpe_ratio=sharpe,
            max_drawdown_pct=max_dd,
            tick_to_order_p50_us=p50,
            tick_to_order_p99_us=p99,
            tick_to_order_p99_9_us=p99_9,
            equity_curve=curve,
        )
