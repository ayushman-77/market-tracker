"""Orderbook drift detection and reconciliation engine.

Periodically compares the locally reconstructed L2 book against a ground-truth
REST snapshot, detecting depth divergence, dropped deltas, and mid-price drift.
"""

from dataclasses import dataclass, field

import numpy as np

from market_tracker.book.orderbook import L2Orderbook
from market_tracker.common.logging import logger


@dataclass
class LevelDiscrepancy:
    side: str
    price: float
    local_size: float
    remote_size: float
    delta_size: float


@dataclass
class DriftReport:
    asset_id: str
    has_drift: bool
    mismatched_levels_count: int
    max_size_discrepancy: float
    total_size_discrepancy: float
    mid_price_drift: float
    local_mid: float | None
    remote_mid: float | None
    discrepancies: list[LevelDiscrepancy] = field(default_factory=list)


class OrderbookDriftChecker:
    """Verifies consistency between local L2 reconstruction and REST snapshots."""

    def __init__(self, size_tolerance: float = 1e-4, price_tolerance: float = 1e-4):
        self.size_tolerance = size_tolerance
        self.price_tolerance = price_tolerance

    def compare(
        self,
        local_book: L2Orderbook,
        remote_bids: list[tuple[float, float]],
        remote_asks: list[tuple[float, float]],
    ) -> DriftReport:
        """Compare local orderbook with a fresh snapshot of bids and asks."""
        discrepancies: list[LevelDiscrepancy] = []

        # Convert remote snapshot to dense level arrays matching local book indexing
        n_levels = local_book.n_levels
        expected_bids = np.zeros(n_levels, dtype=np.float64)
        expected_asks = np.zeros(n_levels, dtype=np.float64)

        for p, s in remote_bids:
            idx = local_book.price_to_idx(p)
            expected_bids[idx] = s

        for p, s in remote_asks:
            idx = local_book.price_to_idx(p)
            expected_asks[idx] = s

        # 1. Compare Bids
        for i in range(n_levels):
            l_sz = float(local_book.bids[i])
            r_sz = float(expected_bids[i])
            diff = abs(l_sz - r_sz)
            if diff > self.size_tolerance:
                p = local_book.idx_to_price(i)
                discrepancies.append(
                    LevelDiscrepancy(
                        side="BUY",
                        price=p,
                        local_size=l_sz,
                        remote_size=r_sz,
                        delta_size=diff,
                    )
                )

        # 2. Compare Asks
        for i in range(n_levels):
            l_sz = float(local_book.asks[i])
            r_sz = float(expected_asks[i])
            diff = abs(l_sz - r_sz)
            if diff > self.size_tolerance:
                p = local_book.idx_to_price(i)
                discrepancies.append(
                    LevelDiscrepancy(
                        side="SELL",
                        price=p,
                        local_size=l_sz,
                        remote_size=r_sz,
                        delta_size=diff,
                    )
                )

        # Calculate remote best bid/ask and mid
        r_best_bid = max([p for p, s in remote_bids if s > 1e-12], default=None)
        r_best_ask = min([p for p, s in remote_asks if s > 1e-12], default=None)
        remote_mid = None
        if r_best_bid is not None and r_best_ask is not None:
            remote_mid = round((r_best_bid + r_best_ask) / 2.0, 6)

        local_mid = local_book.mid
        mid_drift = 0.0
        if local_mid is not None and remote_mid is not None:
            mid_drift = abs(local_mid - remote_mid)
        elif (local_mid is None) != (remote_mid is None):
            mid_drift = 1.0

        max_size_disc = max([d.delta_size for d in discrepancies], default=0.0)
        total_size_disc = sum([d.delta_size for d in discrepancies])
        has_drift = (len(discrepancies) > 0) or (mid_drift > self.price_tolerance)

        if has_drift:
            logger.warning(
                f"Drift detected on {local_book.asset_id}: {len(discrepancies)} level mismatches, "
                f"max_delta={max_size_disc:.2f}, mid_drift={mid_drift:.4f}"
            )

        return DriftReport(
            asset_id=local_book.asset_id,
            has_drift=has_drift,
            mismatched_levels_count=len(discrepancies),
            max_size_discrepancy=max_size_disc,
            total_size_discrepancy=total_size_disc,
            mid_price_drift=mid_drift,
            local_mid=local_mid,
            remote_mid=remote_mid,
            discrepancies=discrepancies,
        )
