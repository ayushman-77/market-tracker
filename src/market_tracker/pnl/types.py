from dataclasses import dataclass


@dataclass
class PositionSnapshot:
    """Read-only view of a wallet's position in a specific outcome token."""

    wallet: str
    asset_id: str
    outcome_idx: int
    size: float
    cost_basis: float
    realized_pnl: float
    unrealized_pnl: float
    fees_paid: float
    total_pnl: float
    last_price: float


@dataclass
class WalletPnL:
    """Summary of a wallet's aggregate PnL across all outcome tokens."""

    wallet: str
    wallet_idx: int
    realized_pnl: float
    unrealized_pnl: float
    fees_paid: float
    total_pnl: float
    open_positions_count: int


@dataclass
class LeaderboardEntry:
    """A single row on the real-time PnL leaderboard."""

    rank: int
    wallet: str
    total_pnl: float
    realized_pnl: float
    unrealized_pnl: float
    fees_paid: float
