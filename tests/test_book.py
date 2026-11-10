"""Tests for L2 orderbook reconstruction, array price levels, and drift detection."""

import math

from hypothesis import given, settings
from hypothesis import strategies as st

from market_tracker.book.drift import OrderbookDriftChecker
from market_tracker.book.orderbook import L2Orderbook
from market_tracker.common.types import Side


def test_orderbook_snapshot_and_deltas():
    """Verify L2 orderbook snapshot and delta updates maintain exact best bid/ask."""
    book = L2Orderbook(asset_id="tok_test", tick_size=0.001)

    # Initial snapshot
    bids = [(0.450, 100.0), (0.440, 200.0), (0.430, 300.0)]
    asks = [(0.550, 150.0), (0.560, 250.0), (0.570, 350.0)]
    book.apply_snapshot(bids, asks)

    assert book.best_bid == 0.450
    assert book.best_ask == 0.550
    assert math.isclose(book.mid, 0.500, abs_tol=1e-6)
    assert math.isclose(book.spread, 0.100, abs_tol=1e-6)

    # Apply tighter bid delta
    book.apply_delta(Side.BUY, price=0.480, size=50.0)
    assert book.best_bid == 0.480
    assert math.isclose(book.mid, 0.515, abs_tol=1e-6)
    assert math.isclose(book.spread, 0.070, abs_tol=1e-6)

    # Cancel best bid (size = 0.0) -> should revert to 0.450
    book.apply_delta(Side.BUY, price=0.480, size=0.0)
    assert book.best_bid == 0.450

    # Apply tighter ask delta
    book.apply_delta(Side.SELL, price=0.520, size=80.0)
    assert book.best_ask == 0.520
    assert math.isclose(book.spread, 0.070, abs_tol=1e-6)

    # Cancel best ask -> should revert to 0.550
    book.apply_delta(Side.SELL, price=0.520, size=0.0)
    assert book.best_ask == 0.550


def test_orderbook_depth_and_imbalance():
    """Verify depth aggregation and order flow imbalance calculations."""
    book = L2Orderbook(asset_id="tok_test", tick_size=0.001)

    # Set up symmetric depth
    book.apply_delta(Side.BUY, price=0.490, size=100.0)
    book.apply_delta(Side.SELL, price=0.510, size=100.0)

    # Imbalance should be 0.0 (perfectly balanced)
    assert math.isclose(book.imbalance(ticks=5), 0.0, abs_tol=1e-6)

    # Add bid depth -> positive imbalance (bid-heavy)
    book.apply_delta(Side.BUY, price=0.489, size=300.0)
    imb = book.imbalance(ticks=5)
    # bid_depth = 400, ask_depth = 100 -> (400 - 100) / 500 = 0.60
    assert math.isclose(imb, 0.60, abs_tol=1e-6)

    # Add large ask depth -> negative imbalance (ask-heavy)
    book.apply_delta(Side.SELL, price=0.511, size=900.0)
    # bid_depth = 400, ask_depth = 1000 -> (400 - 1000) / 1400 = -600 / 1400 = -0.428571
    imb2 = book.imbalance(ticks=5)
    assert math.isclose(imb2, -600.0 / 1400.0, abs_tol=1e-5)


def test_orderbook_hash_mismatch_callback():
    """Verify state hash calculation and mismatch trigger."""
    mismatches = []

    def on_mismatch(asset, computed, expected):
        mismatches.append((asset, computed, expected))

    book = L2Orderbook(asset_id="tok_mismatch", on_mismatch=on_mismatch)
    book.apply_delta(Side.BUY, price=0.400, size=10.0)

    correct_hash = book.compute_state_hash()
    assert len(correct_hash) == 16

    # Apply with correct hash -> passes
    res = book.apply_delta(Side.BUY, price=0.410, size=20.0, expected_hash=None)
    assert res is True

    # Apply with bogus hash -> triggers callback
    res2 = book.apply_delta(Side.SELL, price=0.600, size=30.0, expected_hash="0xbogushash12345")
    assert res2 is False
    assert len(mismatches) == 1
    assert mismatches[0][0] == "tok_mismatch"
    assert mismatches[0][2] == "0xbogushash12345"


def test_drift_checker():
    """Verify drift detector finds level discrepancies and mid price drift."""
    book = L2Orderbook(asset_id="tok_drift", tick_size=0.001)
    checker = OrderbookDriftChecker()

    # Local state
    book.apply_delta(Side.BUY, price=0.450, size=100.0)
    book.apply_delta(Side.SELL, price=0.550, size=100.0)

    # 1. Compare with identical remote state -> zero drift
    remote_bids = [(0.450, 100.0)]
    remote_asks = [(0.550, 100.0)]
    report = checker.compare(book, remote_bids, remote_asks)
    assert report.has_drift is False
    assert report.mismatched_levels_count == 0
    assert report.max_size_discrepancy == 0.0
    assert report.mid_price_drift == 0.0

    # 2. Inject drift in remote state (remote has changed size and new level)
    remote_bids_drift = [(0.450, 80.0)]  # Size discrepancy: 20.0
    remote_asks_drift = [(0.550, 100.0), (0.540, 50.0)]  # New tighter ask -> mid drift
    report_drift = checker.compare(book, remote_bids_drift, remote_asks_drift)

    assert report_drift.has_drift is True
    assert report_drift.mismatched_levels_count == 2  # Bid 0.450 and Ask 0.540
    assert math.isclose(report_drift.max_size_discrepancy, 50.0, abs_tol=1e-4)
    # Local mid = 0.500, Remote mid = (0.450 + 0.540) / 2 = 0.495 -> drift = 0.005
    assert math.isclose(report_drift.mid_price_drift, 0.005, abs_tol=1e-5)


@given(
    st.lists(
        st.tuples(
            st.booleans(),  # is_buy
            st.floats(min_value=0.01, max_value=0.99),  # price
            st.floats(min_value=0.0, max_value=500.0),  # size (0 means cancel)
        ),
        min_size=10,
        max_size=50,
    )
)
@settings(max_examples=25, deadline=None)
def test_orderbook_property_random_deltas(deltas):
    """Property test: L2 book maintain consistent state across random deltas."""
    book = L2Orderbook(asset_id="tok_prop", tick_size=0.001)

    for is_buy, p, s in deltas:
        side = Side.BUY if is_buy else Side.SELL
        book.apply_delta(side, p, s)

    # Derived invariants
    bb = book.best_bid
    ba = book.best_ask
    if bb is not None and ba is not None:
        assert book.spread is not None
        assert book.mid is not None
        assert math.isclose(book.mid, (bb + ba) / 2.0, abs_tol=1e-6)

    # Imbalance must always be in [-1.0, 1.0]
    imb = book.imbalance(ticks=5)
    assert -1.0 <= imb <= 1.0

    # Ladder export must have descending bids and ascending asks
    ladder = book.get_ladder(depth=10)
    for i in range(len(ladder.bids) - 1):
        assert ladder.bids[i].price > ladder.bids[i + 1].price
    for i in range(len(ladder.asks) - 1):
        assert ladder.asks[i].price < ladder.asks[i + 1].price
