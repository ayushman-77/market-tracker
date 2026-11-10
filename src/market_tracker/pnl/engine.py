"""High-performance real-time PnL engine using NumPy Structure-of-Arrays and Numba.

Maintains per-wallet, per-outcome position sizing, average cost basis (AVCO),
realized PnL, fees paid, and unrealized PnL marked against live mid prices.
Guarantees bit-level determinism for out-of-order trades and gap recovery.
"""

from dataclasses import dataclass

import numpy as np

from market_tracker.common.logging import logger
from market_tracker.pnl.kernels import (
    kernel_aggregate_wallet_pnl,
    kernel_apply_trade,
    kernel_mtm_parallel,
    kernel_mtm_sequential,
    kernel_settle_outcome,
)
from market_tracker.pnl.types import LeaderboardEntry, PositionSnapshot, WalletPnL


@dataclass
class _RecordedTrade:
    timestamp: float
    is_buy: bool
    price: float
    qty: float
    fee: float


_JIT_WARMED = False


def _warmup_jit() -> None:
    """Trigger LLVM compilation once per process on small dummy arrays."""
    global _JIT_WARMED
    if _JIT_WARMED:
        return
    dummy_f = np.zeros(4, dtype=np.float64)
    dummy_i = np.zeros(4, dtype=np.int32)
    kernel_apply_trade(0, True, 0.5, 10.0, 0.01, dummy_f, dummy_f, dummy_f, dummy_f, dummy_f, 0.5)
    kernel_mtm_sequential(dummy_f, dummy_f, dummy_i, dummy_f, dummy_f, 4)
    kernel_mtm_parallel(dummy_f, dummy_f, dummy_i, dummy_f, dummy_f, 4)
    kernel_settle_outcome(0, 1.0, dummy_i, dummy_f, dummy_f, dummy_f, dummy_f, 4)
    kernel_aggregate_wallet_pnl(dummy_i, dummy_f, dummy_f, dummy_f, dummy_f, 4, 4)
    _JIT_WARMED = True


class PnLEngine:
    """Structure-of-Arrays (SoA) real-time PnL engine.

    Data is stored in contiguous 1D NumPy arrays for maximum cache locality
    and SIMD vectorization. Dict lookups only exist at the edge (wallet/token -> int index).
    """

    def __init__(self, initial_capacity: int = 10_000):
        self.capacity = initial_capacity
        self.n_positions = 0

        # Contiguous Structure-of-Arrays (SoA) for positions
        self.wallet_indices = np.zeros(self.capacity, dtype=np.int32)
        self.outcome_indices = np.zeros(self.capacity, dtype=np.int32)
        self.sizes = np.zeros(self.capacity, dtype=np.float64)
        self.cost_bases = np.zeros(self.capacity, dtype=np.float64)
        self.realized_pnls = np.zeros(self.capacity, dtype=np.float64)
        self.fees_paid = np.zeros(self.capacity, dtype=np.float64)
        self.unrealized_pnls = np.zeros(self.capacity, dtype=np.float64)

        # Outcome token price array and timestamp tracking
        self.max_outcomes = 10_000
        self.outcome_prices = np.zeros(self.max_outcomes, dtype=np.float64)
        self.outcome_latest_ts = np.full(self.max_outcomes, -1e18, dtype=np.float64)

        # Wallet aggregate PnL cache
        self.max_wallets = 10_000
        self.wallet_pnls = np.zeros(self.max_wallets, dtype=np.float64)

        # Edge lookups: String identifiers to contiguous integer indices
        self.wallet_to_idx: dict[str, int] = {}
        self.idx_to_wallet: list[str] = []

        self.token_to_idx: dict[str, int] = {}
        self.idx_to_token: list[str] = []

        # Position index lookup: (wallet_idx, outcome_idx) -> pos_idx
        self.pos_lookup: dict[tuple[int, int], int] = {}

        # Trade history per position index for out-of-order replay
        self.pos_history: dict[int, list[_RecordedTrade]] = {}

        # Pre-warm Numba JIT compiler
        _warmup_jit()

    def _ensure_capacity(self) -> None:
        """Geometrically resize SoA buffers when capacity is exhausted."""
        if self.n_positions < self.capacity:
            return

        new_cap = self.capacity * 2
        logger.debug(f"Resizing PnL SoA buffers: {self.capacity} -> {new_cap}")

        new_wallet = np.zeros(new_cap, dtype=np.int32)
        new_wallet[: self.capacity] = self.wallet_indices
        self.wallet_indices = new_wallet

        new_outcome = np.zeros(new_cap, dtype=np.int32)
        new_outcome[: self.capacity] = self.outcome_indices
        self.outcome_indices = new_outcome

        new_sizes = np.zeros(new_cap, dtype=np.float64)
        new_sizes[: self.capacity] = self.sizes
        self.sizes = new_sizes

        new_cb = np.zeros(new_cap, dtype=np.float64)
        new_cb[: self.capacity] = self.cost_bases
        self.cost_bases = new_cb

        new_real = np.zeros(new_cap, dtype=np.float64)
        new_real[: self.capacity] = self.realized_pnls
        self.realized_pnls = new_real

        new_fees = np.zeros(new_cap, dtype=np.float64)
        new_fees[: self.capacity] = self.fees_paid
        self.fees_paid = new_fees

        new_unreal = np.zeros(new_cap, dtype=np.float64)
        new_unreal[: self.capacity] = self.unrealized_pnls
        self.unrealized_pnls = new_unreal

        self.capacity = new_cap

    def get_or_create_wallet_idx(self, wallet: str) -> int:
        idx = self.wallet_to_idx.get(wallet)
        if idx is None:
            idx = len(self.idx_to_wallet)
            self.wallet_to_idx[wallet] = idx
            self.idx_to_wallet.append(wallet)
            if idx >= self.max_wallets:
                new_max = self.max_wallets * 2
                new_wp = np.zeros(new_max, dtype=np.float64)
                new_wp[: self.max_wallets] = self.wallet_pnls
                self.wallet_pnls = new_wp
                self.max_wallets = new_max
        return idx

    def get_or_create_token_idx(self, token_id: str) -> int:
        idx = self.token_to_idx.get(token_id)
        if idx is None:
            idx = len(self.idx_to_token)
            self.token_to_idx[token_id] = idx
            self.idx_to_token.append(token_id)
            if idx >= self.max_outcomes:
                new_max = self.max_outcomes * 2
                new_op = np.zeros(new_max, dtype=np.float64)
                new_op[: self.max_outcomes] = self.outcome_prices
                self.outcome_prices = new_op

                new_ts = np.full(new_max, -1e18, dtype=np.float64)
                new_ts[: self.max_outcomes] = self.outcome_latest_ts
                self.outcome_latest_ts = new_ts

                self.max_outcomes = new_max
        return idx

    def get_or_create_position_idx(self, wallet_idx: int, outcome_idx: int) -> int:
        key = (wallet_idx, outcome_idx)
        idx = self.pos_lookup.get(key)
        if idx is None:
            self._ensure_capacity()
            idx = self.n_positions
            self.pos_lookup[key] = idx
            self.wallet_indices[idx] = wallet_idx
            self.outcome_indices[idx] = outcome_idx
            self.sizes[idx] = 0.0
            self.cost_bases[idx] = 0.0
            self.realized_pnls[idx] = 0.0
            self.fees_paid[idx] = 0.0
            self.unrealized_pnls[idx] = 0.0
            self.pos_history[idx] = []
            self.n_positions += 1
        return idx

    def apply_trade(
        self,
        wallet: str,
        asset_id: str,
        is_buy: bool,
        price: float,
        qty: float,
        fee: float = 0.0,
        timestamp: float = 0.0,
    ) -> int:
        """Process an incremental trade fill.

        If the trade arrives out-of-order (timestamp < latest), triggers an isolated
        chronological replay for that single position to guarantee order invariance.
        """
        w_idx = self.get_or_create_wallet_idx(wallet)
        o_idx = self.get_or_create_token_idx(asset_id)
        pos_idx = self.get_or_create_position_idx(w_idx, o_idx)

        # Update mid price cache if incoming trade timestamp >= latest timestamp seen for this token
        if timestamp >= self.outcome_latest_ts[o_idx]:
            self.outcome_latest_ts[o_idx] = timestamp
            self.outcome_prices[o_idx] = price
        cur_mark = float(self.outcome_prices[o_idx])

        history = self.pos_history[pos_idx]
        rec = _RecordedTrade(timestamp=timestamp, is_buy=is_buy, price=price, qty=qty, fee=fee)

        if not history or timestamp >= history[-1].timestamp:
            # In-order fast path (hot path: O(1) JIT kernel call)
            history.append(rec)
            kernel_apply_trade(
                pos_idx,
                is_buy,
                price,
                qty,
                fee,
                self.sizes,
                self.cost_bases,
                self.realized_pnls,
                self.fees_paid,
                self.unrealized_pnls,
                cur_mark,
            )
        else:
            # Out-of-order trade: insert chronologically and replay position
            history.append(rec)
            history.sort(key=lambda t: t.timestamp)

            # Reset position state to 0
            self.sizes[pos_idx] = 0.0
            self.cost_bases[pos_idx] = 0.0
            self.realized_pnls[pos_idx] = 0.0
            self.fees_paid[pos_idx] = 0.0
            self.unrealized_pnls[pos_idx] = 0.0

            # Replay all trades for this single position in exact chronological order
            for t in history:
                kernel_apply_trade(
                    pos_idx,
                    t.is_buy,
                    t.price,
                    t.qty,
                    t.fee,
                    self.sizes,
                    self.cost_bases,
                    self.realized_pnls,
                    self.fees_paid,
                    self.unrealized_pnls,
                    t.price,
                )

            # Mark position to current token mid price
            s_final = self.sizes[pos_idx]
            c_final = self.cost_bases[pos_idx]
            self.unrealized_pnls[pos_idx] = s_final * (cur_mark - c_final)

        return pos_idx

    def mark_price(self, asset_id: str, price: float, parallel: bool = False) -> None:
        """Update mid price for an outcome token and recalculate unrealized PnL."""
        o_idx = self.get_or_create_token_idx(asset_id)
        self.outcome_prices[o_idx] = price

        if parallel:
            kernel_mtm_parallel(
                self.sizes,
                self.cost_bases,
                self.outcome_indices,
                self.outcome_prices,
                self.unrealized_pnls,
                self.n_positions,
            )
        else:
            kernel_mtm_sequential(
                self.sizes,
                self.cost_bases,
                self.outcome_indices,
                self.outcome_prices,
                self.unrealized_pnls,
                self.n_positions,
            )

    def mark_all(self, price_map: dict[str, float], parallel: bool = False) -> None:
        """Bulk update mid prices and run mark-to-market pass over all positions."""
        for aid, p in price_map.items():
            o_idx = self.get_or_create_token_idx(aid)
            self.outcome_prices[o_idx] = p

        if parallel:
            kernel_mtm_parallel(
                self.sizes,
                self.cost_bases,
                self.outcome_indices,
                self.outcome_prices,
                self.unrealized_pnls,
                self.n_positions,
            )
        else:
            kernel_mtm_sequential(
                self.sizes,
                self.cost_bases,
                self.outcome_indices,
                self.outcome_prices,
                self.unrealized_pnls,
                self.n_positions,
            )

    def settle_market(self, asset_id: str, payout: float) -> int:
        """Resolve an outcome token at payout (e.g. 1.0 for winning, 0.0 for losing)."""
        o_idx = self.get_or_create_token_idx(asset_id)
        self.outcome_prices[o_idx] = payout
        settled = kernel_settle_outcome(
            o_idx,
            payout,
            self.outcome_indices,
            self.sizes,
            self.cost_bases,
            self.realized_pnls,
            self.unrealized_pnls,
            self.n_positions,
        )
        return settled

    def get_position(self, wallet: str, asset_id: str) -> PositionSnapshot | None:
        """Fetch current snapshot for a single position."""
        w_idx = self.wallet_to_idx.get(wallet)
        o_idx = self.token_to_idx.get(asset_id)
        if w_idx is None or o_idx is None:
            return None

        pos_idx = self.pos_lookup.get((w_idx, o_idx))
        if pos_idx is None:
            return None

        s = float(self.sizes[pos_idx])
        c = float(self.cost_bases[pos_idx])
        r = float(self.realized_pnls[pos_idx])
        f = float(self.fees_paid[pos_idx])
        cur_p = float(self.outcome_prices[o_idx])
        u = s * (cur_p - c)
        self.unrealized_pnls[pos_idx] = u

        return PositionSnapshot(
            wallet=wallet,
            asset_id=asset_id,
            outcome_idx=o_idx,
            size=s,
            cost_basis=c,
            realized_pnl=r,
            unrealized_pnl=u,
            fees_paid=f,
            total_pnl=r + u - f,
            last_price=cur_p,
        )

    def get_wallet_pnl(self, wallet: str) -> WalletPnL | None:
        """Aggregate total PnL across all outcome tokens held by a wallet."""
        w_idx = self.wallet_to_idx.get(wallet)
        if w_idx is None:
            return None

        # Filter positions for this wallet
        total_r = 0.0
        total_u = 0.0
        total_f = 0.0
        open_count = 0

        for (w, _o), pos_idx in self.pos_lookup.items():
            if w == w_idx:
                s = self.sizes[pos_idx]
                r = self.realized_pnls[pos_idx]
                u = self.unrealized_pnls[pos_idx]
                f = self.fees_paid[pos_idx]

                total_r += r
                total_u += u
                total_f += f
                if abs(s) > 1e-12:
                    open_count += 1

        return WalletPnL(
            wallet=wallet,
            wallet_idx=w_idx,
            realized_pnl=total_r,
            unrealized_pnl=total_u,
            fees_paid=total_f,
            total_pnl=total_r + total_u - total_f,
            open_positions_count=open_count,
        )

    def get_leaderboard(self, top_n: int = 50) -> list[LeaderboardEntry]:
        """Generate top wallets leaderboard by total PnL.

        Uses Numba aggregation + np.argpartition for fast partial sorting (O(W + K log K)).
        """
        n_w = len(self.idx_to_wallet)
        if n_w == 0 or self.n_positions == 0:
            return []

        # Aggregate total PnL per wallet
        kernel_aggregate_wallet_pnl(
            self.wallet_indices,
            self.realized_pnls,
            self.unrealized_pnls,
            self.fees_paid,
            self.wallet_pnls,
            self.n_positions,
            n_w,
        )

        active_pnls = self.wallet_pnls[:n_w]
        k = min(top_n, n_w)

        # Partial sort via argpartition: O(W) instead of full sort O(W log W)
        top_indices = np.argpartition(-active_pnls, k - 1)[:k]
        # Sort only the top k elements: O(K log K)
        sorted_top = top_indices[np.argsort(-active_pnls[top_indices])]

        leaderboard = []
        for rank, w_idx in enumerate(sorted_top, start=1):
            w_addr = self.idx_to_wallet[w_idx]
            tot_pnl = float(active_pnls[w_idx])

            # Gather realized, unrealized, fees for this wallet
            r_sum = 0.0
            u_sum = 0.0
            f_sum = 0.0
            for (w, _o), pos_idx in self.pos_lookup.items():
                if w == w_idx:
                    r_sum += float(self.realized_pnls[pos_idx])
                    u_sum += float(self.unrealized_pnls[pos_idx])
                    f_sum += float(self.fees_paid[pos_idx])

            leaderboard.append(
                LeaderboardEntry(
                    rank=rank,
                    wallet=w_addr,
                    total_pnl=tot_pnl,
                    realized_pnl=r_sum,
                    unrealized_pnl=u_sum,
                    fees_paid=f_sum,
                )
            )

        return leaderboard
