"""Numba @njit acceleration kernels for real-time PnL accounting.

Compiled to bare-metal machine code using LLVM. Contiguous Structure-of-Arrays
enables auto-vectorization (SIMD) and zero interpreter overhead.
"""

import numpy as np
from numba import njit, prange


@njit(fastmath=True, nogil=True)
def kernel_apply_trade(
    pos_idx: int,
    is_buy: bool,
    price: float,
    qty: float,
    fee: float,
    sizes: np.ndarray,
    cost_bases: np.ndarray,
    realized_pnls: np.ndarray,
    fees_paid: np.ndarray,
    unrealized_pnls: np.ndarray,
    mark_price: float,
) -> None:
    """Incremental trade update on contiguous SoA arrays (O(1), zero allocation)."""
    s = sizes[pos_idx]
    c = cost_bases[pos_idx]
    fees_paid[pos_idx] += fee

    if is_buy:
        if s >= 0.0:
            # Adding to long position
            new_s = s + qty
            if new_s > 0.0:
                cost_bases[pos_idx] = (s * c + qty * price) / new_s
            sizes[pos_idx] = new_s
        else:
            # Covering short position
            abs_s = -s
            if qty <= abs_s:
                realized_pnls[pos_idx] += qty * (c - price)
                new_s = s + qty
                if abs(new_s) < 1e-12:
                    new_s = 0.0
                    cost_bases[pos_idx] = 0.0
                sizes[pos_idx] = new_s
            else:
                # Flip from short to long
                realized_pnls[pos_idx] += abs_s * (c - price)
                excess = qty - abs_s
                sizes[pos_idx] = excess
                cost_bases[pos_idx] = price
    else:
        # Sell
        if s > 0.0:
            # Closing long position
            if qty <= s:
                realized_pnls[pos_idx] += qty * (price - c)
                new_s = s - qty
                if abs(new_s) < 1e-12:
                    new_s = 0.0
                    cost_bases[pos_idx] = 0.0
                sizes[pos_idx] = new_s
            else:
                # Flip from long to short
                realized_pnls[pos_idx] += s * (price - c)
                excess = qty - s
                sizes[pos_idx] = -excess
                cost_bases[pos_idx] = price
        else:
            # Adding to short position
            abs_s = -s
            new_abs_s = abs_s + qty
            if new_abs_s > 0.0:
                cost_bases[pos_idx] = (abs_s * c + qty * price) / new_abs_s
            sizes[pos_idx] = -new_abs_s

    # Branchless mark to market: s * (mark_price - c) holds for both long and short
    sizes_final = sizes[pos_idx]
    cost_final = cost_bases[pos_idx]
    unrealized_pnls[pos_idx] = sizes_final * (mark_price - cost_final)


@njit(fastmath=True, nogil=True)
def kernel_mtm_sequential(
    sizes: np.ndarray,
    cost_bases: np.ndarray,
    outcome_indices: np.ndarray,
    outcome_prices: np.ndarray,
    unrealized_pnls: np.ndarray,
    n_positions: int,
) -> None:
    """Sequential mark-to-market pass over contiguous SoA arrays.

    Branchless inner loop auto-vectorizes cleanly with SIMD instructions.
    """
    for i in range(n_positions):
        s = sizes[i]
        c = cost_bases[i]
        oid = outcome_indices[i]
        p = outcome_prices[oid]
        unrealized_pnls[i] = s * (p - c)


@njit(fastmath=True, parallel=True, nogil=True)
def kernel_mtm_parallel(
    sizes: np.ndarray,
    cost_bases: np.ndarray,
    outcome_indices: np.ndarray,
    outcome_prices: np.ndarray,
    unrealized_pnls: np.ndarray,
    n_positions: int,
) -> None:
    """Multi-threaded mark-to-market pass using Numba prange (OpenMP/TBB work sharing)."""
    for i in prange(n_positions):
        s = sizes[i]
        c = cost_bases[i]
        oid = outcome_indices[i]
        p = outcome_prices[oid]
        unrealized_pnls[i] = s * (p - c)


@njit(fastmath=True, nogil=True)
def kernel_settle_outcome(
    target_oid: int,
    payout: float,
    outcome_indices: np.ndarray,
    sizes: np.ndarray,
    cost_bases: np.ndarray,
    realized_pnls: np.ndarray,
    unrealized_pnls: np.ndarray,
    n_positions: int,
) -> int:
    """Settle all positions for a specific outcome token at payout (e.g. 1.0 or 0.0)."""
    settled_count = 0
    for i in range(n_positions):
        if outcome_indices[i] == target_oid:
            s = sizes[i]
            c = cost_bases[i]
            if abs(s) > 1e-12:
                # Realize PnL: s * (payout - c)
                realized_pnls[i] += s * (payout - c)
                sizes[i] = 0.0
                cost_bases[i] = 0.0
                unrealized_pnls[i] = 0.0
                settled_count += 1
    return settled_count


@njit(fastmath=True, nogil=True)
def kernel_aggregate_wallet_pnl(
    wallet_indices: np.ndarray,
    realized_pnls: np.ndarray,
    unrealized_pnls: np.ndarray,
    fees_paid: np.ndarray,
    wallet_pnls: np.ndarray,
    n_positions: int,
    n_wallets: int,
) -> None:
    """Sum total PnL (realized + unrealized - fees) per wallet."""
    for w in range(n_wallets):
        wallet_pnls[w] = 0.0

    for i in range(n_positions):
        w_idx = wallet_indices[i]
        wallet_pnls[w_idx] += realized_pnls[i] + unrealized_pnls[i] - fees_paid[i]
