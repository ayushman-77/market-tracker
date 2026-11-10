"""Independent slow reference implementation of AVCO prediction market accounting.

Used as an oracle in unit and property tests to verify bit-level correctness
of the optimized Numba SoA hot path.
"""

from dataclasses import dataclass


@dataclass
class RefPosition:
    wallet: str
    asset_id: str
    size: float = 0.0
    cost_basis: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    fees_paid: float = 0.0

    @property
    def total_pnl(self) -> float:
        return self.realized_pnl + self.unrealized_pnl - self.fees_paid


class ReferencePnLEngine:
    """Pure-Python reference PnL engine for prediction markets.

    Implements Average Cost Accounting (AVCO) with:
    - Partial fills
    - Buys and sells
    - Position closes and flips
    - Market resolution / redemption
    - Explicit fee deduction
    """

    def __init__(self):
        # Key: (wallet, asset_id) -> RefPosition
        self.positions: dict[tuple[str, str], RefPosition] = {}
        # Key: asset_id -> current mid price
        self.prices: dict[str, float] = {}
        # Key: asset_id -> latest timestamp seen
        self.token_latest_ts: dict[str, float] = {}

    def get_position(self, wallet: str, asset_id: str) -> RefPosition:
        key = (wallet, asset_id)
        if key not in self.positions:
            self.positions[key] = RefPosition(wallet=wallet, asset_id=asset_id)
        pos = self.positions[key]
        cur_p = self.prices.get(asset_id, 0.0)
        if cur_p > 0.0:
            self._update_unrealized(pos, cur_p)
        return pos

    def apply_trade(
        self,
        wallet: str,
        asset_id: str,
        is_buy: bool,
        price: float,
        qty: float,
        fee: float = 0.0,
        timestamp: float = 0.0,
    ) -> RefPosition:
        pos = self.get_position(wallet, asset_id)
        pos.fees_paid += fee

        if is_buy:
            if pos.size >= 0:
                # Adding to long position
                new_size = pos.size + qty
                if new_size > 0:
                    pos.cost_basis = (pos.size * pos.cost_basis + qty * price) / new_size
                pos.size = new_size
            else:
                # Covering short position
                abs_size = abs(pos.size)
                if qty <= abs_size:
                    # Partial or full cover
                    pos.realized_pnl += qty * (pos.cost_basis - price)
                    pos.size += qty
                    if abs(pos.size) < 1e-12:
                        pos.size = 0.0
                        pos.cost_basis = 0.0
                else:
                    # Flip from short to long
                    pos.realized_pnl += abs_size * (pos.cost_basis - price)
                    excess = qty - abs_size
                    pos.size = excess
                    pos.cost_basis = price
        else:
            # Sell
            if pos.size > 0:
                # Closing long position
                if qty <= pos.size:
                    # Partial or full close
                    pos.realized_pnl += qty * (price - pos.cost_basis)
                    pos.size -= qty
                    if abs(pos.size) < 1e-12:
                        pos.size = 0.0
                        pos.cost_basis = 0.0
                else:
                    # Flip from long to short
                    pos.realized_pnl += pos.size * (price - pos.cost_basis)
                    excess = qty - pos.size
                    pos.size = -excess
                    pos.cost_basis = price
            else:
                # Adding to short position
                abs_size = abs(pos.size)
                new_abs_size = abs_size + qty
                if new_abs_size > 0:
                    pos.cost_basis = (abs_size * pos.cost_basis + qty * price) / new_abs_size
                pos.size = -new_abs_size

        # Update mark price to the latest timestamp seen for this token
        if timestamp >= self.token_latest_ts.get(asset_id, -float("inf")):
            self.token_latest_ts[asset_id] = timestamp
            self.prices[asset_id] = price

        cur_price = self.prices.get(asset_id, price)
        self._update_unrealized(pos, cur_price)
        return pos

    def apply_settlement(
        self,
        asset_id: str,
        payout: float,
    ) -> list[RefPosition]:
        """Resolve an outcome token at payout (e.g. 1.0 for winning outcome, 0.0 for losing)."""
        affected = []
        for (_w, aid), pos in self.positions.items():
            if aid == asset_id and abs(pos.size) > 1e-12:
                if pos.size > 0:
                    pos.realized_pnl += pos.size * (payout - pos.cost_basis)
                else:
                    pos.realized_pnl += abs(pos.size) * (pos.cost_basis - payout)
                pos.size = 0.0
                pos.cost_basis = 0.0
                pos.unrealized_pnl = 0.0
                affected.append(pos)
        self.prices[asset_id] = payout
        return affected

    def mark_to_market(self, asset_id: str, price: float) -> None:
        self.prices[asset_id] = price
        for (_w, aid), pos in self.positions.items():
            if aid == asset_id:
                self._update_unrealized(pos, price)

    def mark_all(self, price_map: dict[str, float]) -> None:
        self.prices.update(price_map)
        for (_w, aid), pos in self.positions.items():
            if aid in price_map:
                self._update_unrealized(pos, price_map[aid])

    def _update_unrealized(self, pos: RefPosition, mark_price: float) -> None:
        if abs(pos.size) < 1e-12:
            pos.unrealized_pnl = 0.0
        elif pos.size > 0:
            pos.unrealized_pnl = pos.size * (mark_price - pos.cost_basis)
        else:
            pos.unrealized_pnl = abs(pos.size) * (pos.cost_basis - mark_price)

    def get_wallet_total_pnl(self, wallet: str) -> float:
        total = 0.0
        for (w, _), pos in self.positions.items():
            if w == wallet:
                total += pos.total_pnl
        return total
