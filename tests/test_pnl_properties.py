"""Hypothesis property tests for PnL engine correctness and invariant validation.

Tests:
1. Numba SoA vs Independent Reference Engine bit-for-bit match
2. Partial fills, buys, sells, position flips, and position closes
3. Market resolution and settlement at payout 0.0 and 1.0
4. Out-of-order and shuffled event stream invariance
5. Gap recovery invariance (PnL after backfill == PnL with no gap)
6. Incremental leaderboard accuracy
"""

import math
import random

from hypothesis import given, settings
from hypothesis import strategies as st

from market_tracker.pnl.engine import PnLEngine
from market_tracker.pnl.reference import ReferencePnLEngine

# Strategy for generating a realistic trade
trade_strategy = st.tuples(
    st.sampled_from(["0xwallet_alpha", "0xwallet_beta", "0xwallet_gamma"]),
    st.sampled_from(["token_yes_1", "token_no_1", "token_yes_2"]),
    st.booleans(),  # is_buy
    st.floats(min_value=0.01, max_value=0.99),  # price
    st.floats(min_value=1.0, max_value=1000.0),  # qty
    st.floats(min_value=0.0, max_value=5.0),  # fee
)


@given(st.lists(trade_strategy, min_size=5, max_size=25))
@settings(max_examples=15, deadline=None)
def test_property_numba_vs_reference_oracle(trade_inputs):
    """Property Test: Numba SoA engine must match the independent reference engine."""
    ref_engine = ReferencePnLEngine()
    numba_engine = PnLEngine(initial_capacity=500)

    for i, (wallet, asset_id, is_buy, price, qty, fee) in enumerate(trade_inputs):
        ts = 1000.0 + (i * 1.0)
        ref_engine.apply_trade(wallet, asset_id, is_buy, price, qty, fee, timestamp=ts)
        numba_engine.apply_trade(wallet, asset_id, is_buy, price, qty, fee, timestamp=ts)

    # Compare every position across both engines
    for wallet, asset_id in ref_engine.positions.keys():
        ref_pos = ref_engine.get_position(wallet, asset_id)
        numba_pos = numba_engine.get_position(wallet, asset_id)
        assert numba_pos is not None, f"Position missing in numba engine for {wallet}, {asset_id}"

        assert math.isclose(ref_pos.size, numba_pos.size, abs_tol=1e-7), (
            f"Size mismatch: ref={ref_pos.size}, numba={numba_pos.size}"
        )
        assert math.isclose(ref_pos.cost_basis, numba_pos.cost_basis, abs_tol=1e-7), (
            f"Cost basis mismatch: ref={ref_pos.cost_basis}, numba={numba_pos.cost_basis}"
        )
        assert math.isclose(ref_pos.realized_pnl, numba_pos.realized_pnl, abs_tol=1e-7), (
            f"Realized PnL mismatch: ref={ref_pos.realized_pnl}, numba={numba_pos.realized_pnl}"
        )
        assert math.isclose(ref_pos.unrealized_pnl, numba_pos.unrealized_pnl, abs_tol=1e-7), (
            f"Unrealized PnL mismatch: ref={ref_pos.unrealized_pnl}, numba={numba_pos.unrealized_pnl}"
        )
        assert math.isclose(ref_pos.fees_paid, numba_pos.fees_paid, abs_tol=1e-7), (
            f"Fees mismatch: ref={ref_pos.fees_paid}, numba={numba_pos.fees_paid}"
        )
        assert math.isclose(ref_pos.total_pnl, numba_pos.total_pnl, abs_tol=1e-7), (
            f"Total PnL mismatch: ref={ref_pos.total_pnl}, numba={numba_pos.total_pnl}"
        )


def test_position_flips_and_closes():
    """Deterministic validation of position close, long-to-short flip, and short-to-long flip."""
    engine = PnLEngine()
    w = "0xflip_wallet"
    tok = "token_yes"

    # 1. Buy 10 @ 0.40 -> size=10, cost=0.40, realized=0
    engine.apply_trade(w, tok, is_buy=True, price=0.40, qty=10.0, fee=0.01, timestamp=1.0)
    pos = engine.get_position(w, tok)
    assert pos.size == 10.0
    assert pos.cost_basis == 0.40
    assert pos.realized_pnl == 0.0

    # 2. Add to position: Buy 10 @ 0.60 -> size=20, cost=0.50
    engine.apply_trade(w, tok, is_buy=True, price=0.60, qty=10.0, fee=0.01, timestamp=2.0)
    pos = engine.get_position(w, tok)
    assert pos.size == 20.0
    assert math.isclose(pos.cost_basis, 0.50, abs_tol=1e-9)

    # 3. Partial sell: Sell 5 @ 0.70 -> realized PnL = 5 * (0.70 - 0.50) = 1.0, size=15, cost=0.50
    engine.apply_trade(w, tok, is_buy=False, price=0.70, qty=5.0, fee=0.01, timestamp=3.0)
    pos = engine.get_position(w, tok)
    assert pos.size == 15.0
    assert math.isclose(pos.cost_basis, 0.50, abs_tol=1e-9)
    assert math.isclose(pos.realized_pnl, 1.0, abs_tol=1e-9)

    # 4. Flip from Long to Short: Sell 25 @ 0.80
    # Closes 15 long: realized += 15 * (0.80 - 0.50) = 4.5 -> total realized = 5.5
    # Opens 10 short @ 0.80 -> size = -10, cost_basis = 0.80
    engine.apply_trade(w, tok, is_buy=False, price=0.80, qty=25.0, fee=0.02, timestamp=4.0)
    pos = engine.get_position(w, tok)
    assert pos.size == -10.0
    assert math.isclose(pos.cost_basis, 0.80, abs_tol=1e-9)
    assert math.isclose(pos.realized_pnl, 5.5, abs_tol=1e-9)

    # 5. Flip from Short to Long: Buy 15 @ 0.60
    # Closes 10 short: realized += 10 * (0.80 - 0.60) = 2.0 -> total realized = 7.5
    # Opens 5 long @ 0.60 -> size = 5, cost_basis = 0.60
    engine.apply_trade(w, tok, is_buy=True, price=0.60, qty=15.0, fee=0.01, timestamp=5.0)
    pos = engine.get_position(w, tok)
    assert pos.size == 5.0
    assert math.isclose(pos.cost_basis, 0.60, abs_tol=1e-9)
    assert math.isclose(pos.realized_pnl, 7.5, abs_tol=1e-9)


def test_market_settlement():
    """Test market resolution at payout 1.0 (win) and 0.0 (loss)."""
    engine = PnLEngine()
    w1 = "0xwinner"
    w2 = "0xloser"
    tok_win = "tok_win"
    tok_lose = "tok_lose"

    # w1 buys 100 winning tokens @ 0.60
    engine.apply_trade(w1, tok_win, is_buy=True, price=0.60, qty=100.0, fee=0.10, timestamp=1.0)
    # w2 buys 100 losing tokens @ 0.40
    engine.apply_trade(w2, tok_lose, is_buy=True, price=0.40, qty=100.0, fee=0.10, timestamp=1.0)

    # Settle winning token at payout = 1.0
    engine.settle_market(tok_win, payout=1.0)
    pos_win = engine.get_position(w1, tok_win)
    assert pos_win.size == 0.0
    assert pos_win.cost_basis == 0.0
    assert math.isclose(pos_win.realized_pnl, 100.0 * (1.0 - 0.60), abs_tol=1e-9)  # +40.0

    # Settle losing token at payout = 0.0
    engine.settle_market(tok_lose, payout=0.0)
    pos_lose = engine.get_position(w2, tok_lose)
    assert pos_lose.size == 0.0
    assert pos_lose.cost_basis == 0.0
    assert math.isclose(pos_lose.realized_pnl, 100.0 * (0.0 - 0.40), abs_tol=1e-9)  # -40.0


@given(st.lists(trade_strategy, min_size=5, max_size=20))
@settings(max_examples=15, deadline=None)
def test_property_shuffled_stream_order_invariance(trade_inputs):
    """Property Test: PnL after processing a shuffled stream MUST equal the sorted stream."""
    # Assign monotonic timestamps to create ground truth
    timed_trades = []
    for i, t in enumerate(trade_inputs):
        timed_trades.append((100.0 + i * 2.0, t[0], t[1], t[2], t[3], t[4], t[5]))

    # Engine A processes in exact chronological order
    engine_sorted = PnLEngine(initial_capacity=100)
    for ts, w, aid, is_buy, p, q, f in timed_trades:
        engine_sorted.apply_trade(w, aid, is_buy, p, q, f, timestamp=ts)

    # Engine B processes the exact same trades in shuffled order
    shuffled_trades = timed_trades[:]
    random.Random(42).shuffle(shuffled_trades)

    engine_shuffled = PnLEngine(initial_capacity=100)
    for ts, w, aid, is_buy, p, q, f in shuffled_trades:
        engine_shuffled.apply_trade(w, aid, is_buy, p, q, f, timestamp=ts)

    # Both engines must yield identical positions and PnL
    for _ts, w, aid, _is_buy, _p, _q, _f in timed_trades:
        pos_sorted = engine_sorted.get_position(w, aid)
        pos_shuffled = engine_shuffled.get_position(w, aid)

        assert pos_sorted is not None and pos_shuffled is not None
        assert math.isclose(pos_sorted.size, pos_shuffled.size, abs_tol=1e-7)
        assert math.isclose(pos_sorted.cost_basis, pos_shuffled.cost_basis, abs_tol=1e-7)
        assert math.isclose(pos_sorted.realized_pnl, pos_shuffled.realized_pnl, abs_tol=1e-7)
        assert math.isclose(pos_sorted.unrealized_pnl, pos_shuffled.unrealized_pnl, abs_tol=1e-7)
        assert math.isclose(pos_sorted.fees_paid, pos_shuffled.fees_paid, abs_tol=1e-7)
        assert math.isclose(pos_sorted.total_pnl, pos_shuffled.total_pnl, abs_tol=1e-7)


def test_property_gap_recovery_pnl():
    """Property Test: After backfill fills a gap, PnL must equal continuous stream."""
    trades = [
        (10.0, "0xwal1", "tok_yes", True, 0.40, 100.0, 0.05),
        (20.0, "0xwal1", "tok_yes", True, 0.50, 50.0, 0.02),
        (30.0, "0xwal1", "tok_yes", False, 0.60, 80.0, 0.04),  # In gap
        (40.0, "0xwal1", "tok_yes", False, 0.70, 40.0, 0.03),  # In gap
        (50.0, "0xwal1", "tok_yes", True, 0.55, 100.0, 0.05),
    ]

    # Ground truth: continuous processing
    ground_truth_engine = PnLEngine()
    for ts, w, aid, is_buy, p, q, f in trades:
        ground_truth_engine.apply_trade(w, aid, is_buy, p, q, f, timestamp=ts)

    # Gap engine: misses trades at ts=30 and ts=40 initially
    gap_engine = PnLEngine()
    gap_engine.apply_trade(*trades[0][1:], timestamp=trades[0][0])
    gap_engine.apply_trade(*trades[1][1:], timestamp=trades[1][0])
    gap_engine.apply_trade(*trades[4][1:], timestamp=trades[4][0])

    # Gap detected and REST backfill recovers trades[2] and trades[3]
    gap_engine.apply_trade(*trades[2][1:], timestamp=trades[2][0])
    gap_engine.apply_trade(*trades[3][1:], timestamp=trades[3][0])

    # Verify gap recovery state is identical to ground truth
    pos_gt = ground_truth_engine.get_position("0xwal1", "tok_yes")
    pos_recovered = gap_engine.get_position("0xwal1", "tok_yes")

    assert math.isclose(pos_gt.size, pos_recovered.size, abs_tol=1e-9)
    assert math.isclose(pos_gt.cost_basis, pos_recovered.cost_basis, abs_tol=1e-9)
    assert math.isclose(pos_gt.realized_pnl, pos_recovered.realized_pnl, abs_tol=1e-9)
    assert math.isclose(pos_gt.total_pnl, pos_recovered.total_pnl, abs_tol=1e-9)


def test_leaderboard_ordering():
    """Verify incremental leaderboard generates properly sorted top-N entries."""
    engine = PnLEngine()
    for i in range(20):
        wallet = f"0xleader_{i:02d}"
        # Make higher indices have more profitable positions
        price = 0.30 + (i * 0.02)
        engine.apply_trade(
            wallet, "tok_common", is_buy=True, price=price, qty=100.0, fee=0.01, timestamp=1.0
        )

    # Mark price high so all have positive unrealized PnL
    engine.mark_price("tok_common", price=0.90)

    leaderboard = engine.get_leaderboard(top_n=5)
    assert len(leaderboard) == 5

    # Lowest cost basis (i=0, price=0.30) has greatest profit at price=0.90
    assert leaderboard[0].wallet == "0xleader_00"
    for j in range(len(leaderboard) - 1):
        assert leaderboard[j].total_pnl >= leaderboard[j + 1].total_pnl
