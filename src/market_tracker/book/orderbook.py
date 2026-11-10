"""High-performance L2 orderbook reconstruction with fixed-tick array price levels.

In prediction markets (prices in [0, 1]), fixed tick sizing maps price directly
to a contiguous 1D array index (O(1) indexing, zero dicts or tree allocations on the hot path).
The entire price ladder fits within the CPU L1 data cache.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numba import njit

from market_tracker.common.logging import logger
from market_tracker.common.types import Side


@njit(fastmath=True, nogil=True)
def _find_best_bid(bids: np.ndarray, start_idx: int) -> int:
    for i in range(start_idx, -1, -1):
        if bids[i] > 1e-12:
            return i
    return -1


@njit(fastmath=True, nogil=True)
def _find_best_ask(asks: np.ndarray, start_idx: int, n: int) -> int:
    for i in range(start_idx, n):
        if asks[i] > 1e-12:
            return i
    return -1


@njit(fastmath=True, nogil=True)
def _sum_depth(arr: np.ndarray, start_idx: int, end_idx: int) -> float:
    total = 0.0
    for i in range(start_idx, end_idx + 1):
        total += arr[i]
    return total


@dataclass
class LadderLevel:
    price: float
    size: float


@dataclass
class OrderbookSnapshot:
    asset_id: str
    best_bid: float | None
    best_ask: float | None
    mid: float | None
    spread: float | None
    imbalance: float
    bids: list[LadderLevel]
    asks: list[LadderLevel]
    book_hash: str


class L2Orderbook:
    """Array-based L2 Orderbook for a single prediction market outcome token.

    Price levels are represented as contiguous 1D NumPy arrays of size N = (max_p - min_p)/tick + 1.
    Direct indexing: idx = round((price - min_price) / tick_size).
    """

    def __init__(
        self,
        asset_id: str,
        tick_size: float = 0.001,
        min_price: float = 0.0,
        max_price: float = 1.0,
        on_mismatch: Callable[[str, str, str], None] | None = None,
    ):
        self.asset_id = asset_id
        self.tick_size = tick_size
        self.min_price = min_price
        self.max_price = max_price
        self.on_mismatch = on_mismatch

        # Number of discrete price levels
        self.n_levels = int(round((max_price - min_price) / tick_size)) + 1

        # Contiguous L1-resident price arrays
        self.bids = np.zeros(self.n_levels, dtype=np.float64)
        self.asks = np.zeros(self.n_levels, dtype=np.float64)

        # Cached best level indices (-1 if side is empty)
        self.best_bid_idx: int = -1
        self.best_ask_idx: int = -1

        # Sequence and mismatch tracking
        self.last_seq: int = 0
        self.mismatch_count: int = 0
        self.total_updates: int = 0

    def price_to_idx(self, price: float) -> int:
        """Map price to contiguous array index in O(1)."""
        idx = int(round((price - self.min_price) / self.tick_size))
        if idx < 0:
            return 0
        if idx >= self.n_levels:
            return self.n_levels - 1
        return idx

    def idx_to_price(self, idx: int) -> float:
        """Map array index back to price float."""
        return round(self.min_price + (idx * self.tick_size), 6)

    def apply_snapshot(
        self,
        bids: list[tuple[float, float]],
        asks: list[tuple[float, float]],
        book_hash: str | None = None,
        seq: int = 0,
    ) -> None:
        """Initialize or reset orderbook state from a full snapshot."""
        self.bids.fill(0.0)
        self.asks.fill(0.0)
        self.best_bid_idx = -1
        self.best_ask_idx = -1
        self.last_seq = seq

        for price, size in bids:
            idx = self.price_to_idx(price)
            self.bids[idx] = size
            if self.best_bid_idx == -1 or idx > self.best_bid_idx:
                self.best_bid_idx = idx

        for price, size in asks:
            idx = self.price_to_idx(price)
            self.asks[idx] = size
            if self.best_ask_idx == -1 or idx < self.best_ask_idx:
                self.best_ask_idx = idx

        self.total_updates += 1

    def apply_delta(
        self,
        side: Side,
        price: float,
        size: float,
        expected_hash: str | None = None,
        seq: int | None = None,
    ) -> bool:
        """Apply an incremental level delta (O(1) hot path).

        size == 0 indicates removal of the price level.
        Returns True if hash matches or not checked, False if mismatch occurred.
        """
        idx = self.price_to_idx(price)
        self.total_updates += 1

        if seq is not None:
            self.last_seq = seq

        if side == Side.BUY:
            self.bids[idx] = size
            if size > 1e-12:
                if self.best_bid_idx == -1 or idx > self.best_bid_idx:
                    self.best_bid_idx = idx
            elif idx == self.best_bid_idx:
                # Level was removed from best bid; search downwards for new best bid
                self.best_bid_idx = _find_best_bid(self.bids, idx - 1)
        else:
            self.asks[idx] = size
            if size > 1e-12:
                if self.best_ask_idx == -1 or idx < self.best_ask_idx:
                    self.best_ask_idx = idx
            elif idx == self.best_ask_idx:
                # Level was removed from best ask; search upwards for new best ask
                self.best_ask_idx = _find_best_ask(self.asks, idx + 1, self.n_levels)

        # Hash verification
        if expected_hash is not None:
            computed = self.compute_state_hash()
            if computed != expected_hash:
                self.mismatch_count += 1
                logger.warning(
                    f"Orderbook hash mismatch on {self.asset_id}: computed={computed}, expected={expected_hash}"
                )
                if self.on_mismatch:
                    self.on_mismatch(self.asset_id, computed, expected_hash)
                return False

        return True

    @property
    def best_bid(self) -> float | None:
        if self.best_bid_idx >= 0:
            return self.idx_to_price(self.best_bid_idx)
        return None

    @property
    def best_ask(self) -> float | None:
        if self.best_ask_idx >= 0:
            return self.idx_to_price(self.best_ask_idx)
        return None

    @property
    def mid(self) -> float | None:
        bb = self.best_bid
        ba = self.best_ask
        if bb is not None and ba is not None:
            return round((bb + ba) / 2.0, 6)
        return None

    @property
    def spread(self) -> float | None:
        bb = self.best_bid
        ba = self.best_ask
        if bb is not None and ba is not None:
            return round(ba - bb, 6)
        return None

    def depth_within_ticks(self, ticks: int = 5) -> tuple[float, float]:
        """Calculate total volume depth within X ticks of best bid and ask."""
        bid_depth = 0.0
        if self.best_bid_idx >= 0:
            start_i = max(0, self.best_bid_idx - ticks)
            bid_depth = _sum_depth(self.bids, start_i, self.best_bid_idx)

        ask_depth = 0.0
        if self.best_ask_idx >= 0:
            end_i = min(self.n_levels - 1, self.best_ask_idx + ticks)
            ask_depth = _sum_depth(self.asks, self.best_ask_idx, end_i)

        return bid_depth, ask_depth

    def imbalance(self, ticks: int = 5) -> float:
        """Calculate orderbook order flow imbalance: (bid_vol - ask_vol) / (bid_vol + ask_vol).

        Returns float in [-1.0, 1.0]. Positive means bid-heavy; negative means ask-heavy.
        """
        b_depth, a_depth = self.depth_within_ticks(ticks)
        tot = b_depth + a_depth
        if tot < 1e-12:
            return 0.0
        return round((b_depth - a_depth) / tot, 6)

    def compute_state_hash(self, top_k: int = 5) -> str:
        """Deterministic fingerprint hash of the top K bid and ask levels."""
        parts = []
        if self.best_bid_idx >= 0:
            count = 0
            i = self.best_bid_idx
            while i >= 0 and count < top_k:
                if self.bids[i] > 1e-12:
                    p = self.idx_to_price(i)
                    s = float(self.bids[i])
                    parts.append(f"b:{p:.4f}:{s:.2f}")
                    count += 1
                i -= 1

        if self.best_ask_idx >= 0:
            count = 0
            i = self.best_ask_idx
            while i < self.n_levels and count < top_k:
                if self.asks[i] > 1e-12:
                    p = self.idx_to_price(i)
                    s = float(self.asks[i])
                    parts.append(f"a:{p:.4f}:{s:.2f}")
                    count += 1
                i += 1

        raw = "|".join(parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def get_ladder(self, depth: int = 10) -> OrderbookSnapshot:
        """Export a clean ladder view with top N levels for clients and API push."""
        bid_levels: list[LadderLevel] = []
        if self.best_bid_idx >= 0:
            i = self.best_bid_idx
            while i >= 0 and len(bid_levels) < depth:
                if self.bids[i] > 1e-12:
                    bid_levels.append(
                        LadderLevel(price=self.idx_to_price(i), size=float(self.bids[i]))
                    )
                i -= 1

        ask_levels: list[LadderLevel] = []
        if self.best_ask_idx >= 0:
            i = self.best_ask_idx
            while i < self.n_levels and len(ask_levels) < depth:
                if self.asks[i] > 1e-12:
                    ask_levels.append(
                        LadderLevel(price=self.idx_to_price(i), size=float(self.asks[i]))
                    )
                i += 1

        return OrderbookSnapshot(
            asset_id=self.asset_id,
            best_bid=self.best_bid,
            best_ask=self.best_ask,
            mid=self.mid,
            spread=self.spread,
            imbalance=self.imbalance(ticks=5),
            bids=bid_levels,
            asks=ask_levels,
            book_hash=self.compute_state_hash(top_k=5),
        )
