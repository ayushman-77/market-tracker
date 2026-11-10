"""Realistic paper execution broker with book-walking slippage and passive queue model.

Enforces:
1. Spread-crossing market order fills with depth slippage walking the L2 book.
2. Queue-position model for passive limit orders (only fills on traded volume).
3. Polymarket fee schedule.
4. Risk management: max position size per market, max total portfolio exposure,
   and kill-switch drawdown circuit breaker.
"""

import uuid
from dataclasses import dataclass, field
from enum import Enum

from market_tracker.book.orderbook import L2Orderbook
from market_tracker.common.logging import logger
from market_tracker.common.types import Side, Trade


class OrderStatus(Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class FillEvent:
    fill_id: str
    order_id: str
    asset_id: str
    side: Side
    price: float
    size: float
    usd_value: float
    fee: float
    slippage: float
    is_passive: bool
    timestamp: float


@dataclass
class PaperOrder:
    order_id: str
    asset_id: str
    side: Side
    requested_size: float
    limit_price: float | None
    is_passive: bool
    status: OrderStatus = OrderStatus.PENDING
    filled_size: float = 0.0
    avg_fill_price: float = 0.0
    total_fees: float = 0.0
    queue_ahead: float = 0.0
    created_at: float = 0.0
    fills: list[FillEvent] = field(default_factory=list)

    @property
    def remaining_size(self) -> float:
        return max(0.0, self.requested_size - self.filled_size)


@dataclass
class RiskLimits:
    max_position_per_market: float = 5_000.0  # contracts
    max_total_exposure_usd: float = 25_000.0  # total portfolio exposure
    max_drawdown_pct: float = 0.15  # 15% drawdown kill switch
    is_kill_switch_triggered: bool = False
    kill_switch_reason: str = ""


class PaperBroker:
    """Event-driven paper execution broker with realistic market microstructure modeling."""

    def __init__(
        self,
        initial_cash: float = 10_000.0,
        risk_limits: RiskLimits | None = None,
        maker_fee_rate: float = 0.000,
        taker_fee_rate: float = 0.001,
    ):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.risk_limits = risk_limits or RiskLimits()
        self.maker_fee_rate = maker_fee_rate
        self.taker_fee_rate = taker_fee_rate

        # Position tracking: asset_id -> size (positive = long, negative = short)
        self.positions: dict[str, float] = {}
        # Cost basis tracking: asset_id -> avg entry price
        self.cost_bases: dict[str, float] = {}
        # Realized PnL and total fees
        self.realized_pnl = 0.0
        self.total_fees = 0.0

        # Books registered for execution: asset_id -> L2Orderbook
        self.books: dict[str, L2Orderbook] = {}

        # Open passive orders waiting in queue: order_id -> PaperOrder
        self.open_passive_orders: dict[str, PaperOrder] = {}

        # Trade execution records
        self.fill_history: list[FillEvent] = []
        self.equity_curve: list[tuple[float, float]] = [(0.0, initial_cash)]
        self.peak_equity = initial_cash

    def register_book(self, book: L2Orderbook) -> None:
        self.books[book.asset_id] = book

    def calculate_fee(self, price: float, size: float, is_passive: bool) -> float:
        """Polymarket fee schedule: dynamic formula C * feeRate * p * (1 - p)."""
        fee_rate = self.maker_fee_rate if is_passive else self.taker_fee_rate
        # Bounded probability fee curve
        dynamic_p = max(0.01, min(0.99, price))
        return round(size * fee_rate * dynamic_p * (1.0 - dynamic_p), 6)

    @property
    def equity(self) -> float:
        return self.get_portfolio_equity()

    @property
    def unrealized_pnl(self) -> float:
        unrealized = 0.0
        for asset_id, size in self.positions.items():
            if abs(size) > 1e-12:
                book = self.books.get(asset_id)
                cur_mid = (
                    book.mid
                    if (book and book.mid is not None)
                    else self.cost_bases.get(asset_id, 0.50)
                )
                cb = self.cost_bases.get(asset_id, 0.50)
                unrealized += size * (cur_mid - cb)
        return unrealized

    @property
    def is_killed(self) -> bool:
        return self.risk_limits.is_kill_switch_triggered

    def get_portfolio_equity(self) -> float:
        """Total equity = Cash + Realized PnL + Unrealized PnL."""
        return self.cash + self.unrealized_pnl

    def _check_risk_limits(
        self, asset_id: str, side: Side, size: float, est_price: float
    ) -> tuple[bool, str]:
        """Validate order against risk limits and kill-switch circuit breaker."""
        if self.risk_limits.is_kill_switch_triggered:
            return False, f"Kill switch active: {self.risk_limits.kill_switch_reason}"

        cur_pos = self.positions.get(asset_id, 0.0)
        new_pos = cur_pos + size if side == Side.BUY else cur_pos - size
        if abs(new_pos) > self.risk_limits.max_position_per_market:
            return (
                False,
                f"Position limit exceeded on {asset_id} (requested={abs(new_pos):.1f}, max={self.risk_limits.max_position_per_market:.1f})",
            )

        # Portfolio total exposure check
        est_val = size * est_price
        cur_exposure = sum(
            abs(s) * self.cost_bases.get(aid, 0.50) for aid, s in self.positions.items()
        )
        if (cur_exposure + est_val) > self.risk_limits.max_total_exposure_usd:
            return (
                False,
                f"Total exposure limit exceeded (projected={cur_exposure + est_val:.1f}, max={self.risk_limits.max_total_exposure_usd:.1f})",
            )

        return True, ""

    def _check_drawdown(self, timestamp: float) -> None:
        """Monitor peak equity and trip kill switch if drawdown exceeds threshold."""
        equity = self.get_portfolio_equity()
        self.equity_curve.append((timestamp, equity))

        if equity > self.peak_equity:
            self.peak_equity = equity

        if self.peak_equity > 0.0:
            drawdown = (self.peak_equity - equity) / self.peak_equity
            if (
                drawdown >= self.risk_limits.max_drawdown_pct
                and not self.risk_limits.is_kill_switch_triggered
            ):
                self.risk_limits.is_kill_switch_triggered = True
                self.risk_limits.kill_switch_reason = f"Max drawdown breached: {drawdown * 100:.2f}% >= {self.risk_limits.max_drawdown_pct * 100:.2f}%"
                logger.critical(f"KILL SWITCH TRIGGERED: {self.risk_limits.kill_switch_reason}")
                # Cancel all pending passive orders
                self.open_passive_orders.clear()

    def execute_market_order(
        self,
        asset_id: str,
        side: Side,
        size: float,
        timestamp: float = 0.0,
    ) -> PaperOrder:
        """Cross the spread with realistic slippage walking the L2 book."""
        book = self.books.get(asset_id)
        if not book:
            order = PaperOrder(
                order_id=str(uuid.uuid4())[:8],
                asset_id=asset_id,
                side=side,
                requested_size=size,
                limit_price=None,
                is_passive=False,
                status=OrderStatus.REJECTED,
                created_at=timestamp,
            )
            return order

        # Estimate price for risk check
        best_price = book.best_ask if side == Side.BUY else book.best_bid
        if best_price is None:
            order = PaperOrder(
                order_id=str(uuid.uuid4())[:8],
                asset_id=asset_id,
                side=side,
                requested_size=size,
                limit_price=None,
                is_passive=False,
                status=OrderStatus.REJECTED,
                created_at=timestamp,
            )
            return order

        passed, reason = self._check_risk_limits(asset_id, side, size, best_price)
        if not passed:
            logger.debug(f"Order rejected by risk manager: {reason}")
            return PaperOrder(
                order_id=str(uuid.uuid4())[:8],
                asset_id=asset_id,
                side=side,
                requested_size=size,
                limit_price=None,
                is_passive=False,
                status=OrderStatus.REJECTED,
                created_at=timestamp,
            )

        # Walk the book to fill size across depth levels
        order = PaperOrder(
            order_id=str(uuid.uuid4())[:8],
            asset_id=asset_id,
            side=side,
            requested_size=size,
            limit_price=None,
            is_passive=False,
            created_at=timestamp,
        )

        remaining = size
        total_fill_cost = 0.0

        if side == Side.BUY:
            # Walk asks ascending starting at best_ask_idx
            i = book.best_ask_idx
            while i < book.n_levels and remaining > 1e-12:
                avail = float(book.asks[i])
                if avail > 1e-12:
                    p = book.idx_to_price(i)
                    fill_q = min(remaining, avail)
                    fee = self.calculate_fee(p, fill_q, is_passive=False)
                    slippage = abs(p - best_price)

                    fill = FillEvent(
                        fill_id=str(uuid.uuid4())[:8],
                        order_id=order.order_id,
                        asset_id=asset_id,
                        side=side,
                        price=p,
                        size=fill_q,
                        usd_value=p * fill_q,
                        fee=fee,
                        slippage=slippage,
                        is_passive=False,
                        timestamp=timestamp,
                    )
                    order.fills.append(fill)
                    self.fill_history.append(fill)

                    total_fill_cost += (p * fill_q) + fee
                    self.total_fees += fee
                    order.total_fees += fee
                    order.filled_size += fill_q
                    remaining -= fill_q

                    # Decrement simulated book liquidity
                    book.asks[i] -= fill_q
                i += 1
        else:
            # Walk bids descending starting at best_bid_idx
            i = book.best_bid_idx
            while i >= 0 and remaining > 1e-12:
                avail = float(book.bids[i])
                if avail > 1e-12:
                    p = book.idx_to_price(i)
                    fill_q = min(remaining, avail)
                    fee = self.calculate_fee(p, fill_q, is_passive=False)
                    slippage = abs(p - best_price)

                    fill = FillEvent(
                        fill_id=str(uuid.uuid4())[:8],
                        order_id=order.order_id,
                        asset_id=asset_id,
                        side=side,
                        price=p,
                        size=fill_q,
                        usd_value=p * fill_q,
                        fee=fee,
                        slippage=slippage,
                        is_passive=False,
                        timestamp=timestamp,
                    )
                    order.fills.append(fill)
                    self.fill_history.append(fill)

                    total_fill_cost += (p * fill_q) - fee
                    self.total_fees += fee
                    order.total_fees += fee
                    order.filled_size += fill_q
                    remaining -= fill_q

                    book.bids[i] -= fill_q
                i -= 1

        if order.filled_size > 0:
            order.avg_fill_price = sum(f.price * f.size for f in order.fills) / order.filled_size
            self._apply_position_fill(
                asset_id, side, order.filled_size, order.avg_fill_price, order.total_fees
            )
            order.status = OrderStatus.FILLED if remaining < 1e-12 else OrderStatus.PARTIALLY_FILLED
        else:
            order.status = OrderStatus.REJECTED

        self._check_drawdown(timestamp)
        return order

    def submit_passive_order(
        self,
        asset_id: str,
        side: Side,
        price: float,
        size: float,
        timestamp: float = 0.0,
    ) -> PaperOrder:
        """Submit a passive limit order using queue-position priority."""
        book = self.books.get(asset_id)
        if not book:
            return PaperOrder(
                order_id=str(uuid.uuid4())[:8],
                asset_id=asset_id,
                side=side,
                requested_size=size,
                limit_price=price,
                is_passive=True,
                status=OrderStatus.REJECTED,
                created_at=timestamp,
            )

        passed, reason = self._check_risk_limits(asset_id, side, size, price)
        if not passed:
            logger.debug(f"Passive order rejected by risk limits: {reason}")
            return PaperOrder(
                order_id=str(uuid.uuid4())[:8],
                asset_id=asset_id,
                side=side,
                requested_size=size,
                limit_price=price,
                is_passive=True,
                status=OrderStatus.REJECTED,
                created_at=timestamp,
            )

        # Queue-position model: count volume currently resting at or ahead of this price level
        idx = book.price_to_idx(price)
        queue_ahead = float(book.bids[idx]) if side == Side.BUY else float(book.asks[idx])

        order = PaperOrder(
            order_id=str(uuid.uuid4())[:8],
            asset_id=asset_id,
            side=side,
            requested_size=size,
            limit_price=price,
            is_passive=True,
            queue_ahead=queue_ahead,
            created_at=timestamp,
        )
        self.open_passive_orders[order.order_id] = order
        return order

    def on_trade_event(self, trade: Trade) -> list[FillEvent]:
        """Realistic passive fill simulation: fills passive limit orders only on actual traded volume."""
        t_ts = trade.timestamp.timestamp()
        fills_generated: list[FillEvent] = []

        completed_orders: list[str] = []

        for order_id, order in list(self.open_passive_orders.items()):
            if order.asset_id != trade.asset_id or order.limit_price is None:
                continue

            can_fill = False
            if order.side == Side.BUY and trade.price <= order.limit_price:
                can_fill = True
            elif order.side == Side.SELL and trade.price >= order.limit_price:
                can_fill = True

            if can_fill:
                # Decrement queue position by trade size
                order.queue_ahead -= trade.size
                if order.queue_ahead < 0:
                    fill_q = min(order.remaining_size, abs(order.queue_ahead))
                    if fill_q > 1e-12:
                        p = order.limit_price
                        fee = self.calculate_fee(p, fill_q, is_passive=True)
                        fill = FillEvent(
                            fill_id=str(uuid.uuid4())[:8],
                            order_id=order.order_id,
                            asset_id=order.asset_id,
                            side=order.side,
                            price=p,
                            size=fill_q,
                            usd_value=p * fill_q,
                            fee=fee,
                            slippage=0.0,
                            is_passive=True,
                            timestamp=t_ts,
                        )
                        order.fills.append(fill)
                        self.fill_history.append(fill)
                        fills_generated.append(fill)

                        order.filled_size += fill_q
                        order.total_fees += fee
                        self.total_fees += fee

                        self._apply_position_fill(order.asset_id, order.side, fill_q, p, fee)

                        if order.remaining_size < 1e-12:
                            order.status = OrderStatus.FILLED
                            completed_orders.append(order_id)
                        else:
                            order.status = OrderStatus.PARTIALLY_FILLED
                            order.queue_ahead = 0.0

        for oid in completed_orders:
            self.open_passive_orders.pop(oid, None)

        self._check_drawdown(t_ts)
        return fills_generated

    def process_trade_tick(self, trade: Trade, book: L2Orderbook | None = None) -> list[FillEvent]:
        """Convenience alias for incoming trade ticks: updates book and executes passive queue fills."""
        if book is not None:
            self.register_book(book)
        return self.on_trade_event(trade)

    def _apply_position_fill(
        self, asset_id: str, side: Side, size: float, price: float, fee: float
    ) -> None:
        """Update cash, inventory, cost basis, and realized PnL via AVCO accounting."""
        cur_s = self.positions.get(asset_id, 0.0)
        cur_c = self.cost_bases.get(asset_id, 0.0)

        if side == Side.BUY:
            self.cash -= (size * price) + fee
            if cur_s >= 0:
                new_s = cur_s + size
                if new_s > 0:
                    self.cost_bases[asset_id] = (cur_s * cur_c + size * price) / new_s
                self.positions[asset_id] = new_s
            else:
                abs_s = abs(cur_s)
                if size <= abs_s:
                    self.realized_pnl += size * (cur_c - price)
                    self.positions[asset_id] = cur_s + size
                    if abs(self.positions[asset_id]) < 1e-12:
                        self.positions[asset_id] = 0.0
                        self.cost_bases[asset_id] = 0.0
                else:
                    self.realized_pnl += abs_s * (cur_c - price)
                    excess = size - abs_s
                    self.positions[asset_id] = excess
                    self.cost_bases[asset_id] = price
        else:
            # Sell
            self.cash += (size * price) - fee
            if cur_s > 0:
                if size <= cur_s:
                    self.realized_pnl += size * (price - cur_c)
                    self.positions[asset_id] = cur_s - size
                    if abs(self.positions[asset_id]) < 1e-12:
                        self.positions[asset_id] = 0.0
                        self.cost_bases[asset_id] = 0.0
                else:
                    self.realized_pnl += cur_s * (price - cur_c)
                    excess = size - cur_s
                    self.positions[asset_id] = -excess
                    self.cost_bases[asset_id] = price
            else:
                abs_s = abs(cur_s)
                new_abs = abs_s + size
                if new_abs > 0:
                    self.cost_bases[asset_id] = (abs_s * cur_c + size * price) / new_abs
                self.positions[asset_id] = -new_abs
