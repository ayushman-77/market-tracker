"""Tests for trading signals, paper execution, risk limits, and replay backtester."""

import math
from datetime import UTC, datetime

from market_tracker.book.orderbook import L2Orderbook
from market_tracker.common.types import BookEvent, BookEventType, Side, Trade, TradeSource
from market_tracker.pnl.engine import PnLEngine
from market_tracker.strategy.backtest import ReplayBacktester
from market_tracker.strategy.paper import OrderStatus, PaperBroker, RiskLimits
from market_tracker.strategy.signals import (
    ImbalanceSignal,
    SignalAction,
    SmartMoneyFlowSignal,
)


def test_imbalance_signal_bullish_and_bearish():
    """Verify orderbook imbalance signal generates BUY on bid pressure and SELL on ask pressure."""
    book = L2Orderbook(asset_id="tok_sig", tick_size=0.001)
    sig = ImbalanceSignal(threshold=0.30, ticks=5, min_depth=50.0)

    # 1. Symmetric depth -> HOLD
    book.apply_delta(Side.BUY, 0.490, 100.0)
    book.apply_delta(Side.SELL, 0.510, 100.0)
    dec = sig.evaluate(book, timestamp=1.0)
    assert dec.action == SignalAction.HOLD

    # 2. Add large bid depth -> BUY
    book.apply_delta(Side.BUY, 0.489, 400.0)
    # bid_depth = 500, ask_depth = 100 -> imbalance = (500-100)/600 = +0.667 > 0.30
    dec_buy = sig.evaluate(book, timestamp=2.0)
    assert dec_buy.action == SignalAction.BUY
    assert dec_buy.target_price == 0.510

    # 3. Add massive ask depth -> SELL
    book.apply_delta(Side.SELL, 0.511, 1500.0)
    dec_sell = sig.evaluate(book, timestamp=3.0)
    assert dec_sell.action == SignalAction.SELL
    assert dec_sell.target_price == 0.490


def test_smart_money_flow_lookahead_bias_protection():
    """Verify smart money follower uses dynamically evaluated historical leaderboard."""
    pnl = PnLEngine()
    sig = SmartMoneyFlowSignal(
        pnl_engine=pnl, top_n=2, window_seconds=60.0, flow_threshold_usd=100.0
    )

    smart_wallet = "0xsmart_trader"
    asset = "tok_smart"

    # Initially, smart_wallet has zero trades and is NOT in top wallets
    t1 = Trade(
        event_id="tr_1",
        condition_id="cond_1",
        asset_id=asset,
        outcome_idx=0,
        maker_wallet="0xother",
        taker_wallet=smart_wallet,
        side=Side.BUY,
        price=0.50,
        size=300.0,
        usd_value=150.0,
        fee=0.15,
        source=TradeSource.WS_CLOB,
        tx_hash="0xhash1",
        timestamp=datetime.fromtimestamp(10.0, tz=UTC),
    )
    # First trade: not yet ranked in top 2 -> no signal
    dec1 = sig.on_trade(t1)
    assert dec1 is None

    # Now register a large winning trade in pnl engine at t=10 so smart_wallet enters top leaderboard
    pnl.apply_trade(smart_wallet, asset, is_buy=True, price=0.20, qty=1000.0, timestamp=10.0)
    pnl.mark_price(asset, price=0.80)  # PnL = +600

    # Advance time to t=20 (> refresh_interval=5s) so signal refreshes historical ranking
    t2 = Trade(
        event_id="tr_2",
        condition_id="cond_1",
        asset_id=asset,
        outcome_idx=0,
        maker_wallet="0xother",
        taker_wallet=smart_wallet,
        side=Side.BUY,
        price=0.80,
        size=500.0,
        usd_value=400.0,
        fee=0.40,
        source=TradeSource.WS_CLOB,
        tx_hash="0xhash2",
        timestamp=datetime.fromtimestamp(20.0, tz=UTC),
    )
    dec2 = sig.on_trade(t2)
    assert dec2 is not None
    assert dec2.action == SignalAction.BUY
    assert dec2.target_price == 0.80


def test_paper_broker_slippage_and_queue_fills():
    """Verify spread-crossing depth slippage and passive queue fill simulation."""
    broker = PaperBroker(initial_cash=5_000.0)
    book = L2Orderbook(asset_id="tok_flow", tick_size=0.001)
    broker.register_book(book)

    # Set up multi-level asks:
    # Level 1: 0.500 with size 50.0
    # Level 2: 0.510 with size 50.0
    book.apply_delta(Side.SELL, 0.500, 50.0)
    book.apply_delta(Side.SELL, 0.510, 50.0)

    # 1. Market order for size 80.0 walks the book!
    # Fills 50 @ 0.500 and 30 @ 0.510 -> avg price = (25.0 + 15.30) / 80 = 0.50375
    order = broker.execute_market_order("tok_flow", Side.BUY, size=80.0, timestamp=1.0)
    assert order.status == OrderStatus.FILLED
    assert order.filled_size == 80.0
    assert math.isclose(order.avg_fill_price, 0.50375, abs_tol=1e-5)
    assert broker.positions["tok_flow"] == 80.0

    # Remaining depth on level 2 should be 20.0 (50 - 30)
    assert math.isclose(book.asks[book.price_to_idx(0.510)], 20.0, abs_tol=1e-5)

    # 2. Passive Limit Order Queue Position Model
    # Place passive buy order at price 0.450 with 100 volume ahead in queue
    book.apply_delta(Side.BUY, 0.450, 100.0)
    passive_order = broker.submit_passive_order(
        "tok_flow", Side.BUY, price=0.450, size=50.0, timestamp=2.0
    )
    assert passive_order.status == OrderStatus.PENDING
    assert passive_order.queue_ahead == 100.0

    # Trade 1: 60 contracts trade at 0.450 -> not enough to clear queue_ahead (100 - 60 = 40 remaining)
    tr1 = Trade(
        event_id="tr_p1",
        condition_id="c1",
        asset_id="tok_flow",
        outcome_idx=0,
        maker_wallet="0xw1",
        taker_wallet="0xw2",
        side=Side.SELL,
        price=0.450,
        size=60.0,
        usd_value=27.0,
        fee=0.01,
        source=TradeSource.WS_CLOB,
        tx_hash="0xtx1",
        timestamp=datetime.fromtimestamp(3.0, tz=UTC),
    )
    fills1 = broker.on_trade_event(tr1)
    assert len(fills1) == 0
    assert math.isclose(passive_order.queue_ahead, 40.0, abs_tol=1e-5)

    # Trade 2: 70 contracts trade at 0.450 -> clears remaining 40 queue_ahead, and fills 30 contracts of our order!
    tr2 = Trade(
        event_id="tr_p2",
        condition_id="c1",
        asset_id="tok_flow",
        outcome_idx=0,
        maker_wallet="0xw1",
        taker_wallet="0xw2",
        side=Side.SELL,
        price=0.450,
        size=70.0,
        usd_value=31.5,
        fee=0.01,
        source=TradeSource.WS_CLOB,
        tx_hash="0xtx2",
        timestamp=datetime.fromtimestamp(4.0, tz=UTC),
    )
    fills2 = broker.on_trade_event(tr2)
    assert len(fills2) == 1
    assert fills2[0].size == 30.0
    assert passive_order.status == OrderStatus.PARTIALLY_FILLED


def test_paper_broker_risk_limits_and_kill_switch():
    """Verify position limit rejection and drawdown kill switch."""
    limits = RiskLimits(max_position_per_market=100.0, max_drawdown_pct=0.04)
    broker = PaperBroker(initial_cash=1_000.0, risk_limits=limits)
    book = L2Orderbook(asset_id="tok_risk", tick_size=0.001)
    broker.register_book(book)

    book.apply_delta(Side.SELL, 0.500, 1000.0)

    # 1. Reject order exceeding max_position_per_market (100)
    rej_order = broker.execute_market_order("tok_risk", Side.BUY, size=150.0, timestamp=1.0)
    assert rej_order.status == OrderStatus.REJECTED

    # 2. Valid order: Buy 100 @ 0.500 (cost = $50)
    ok_order = broker.execute_market_order("tok_risk", Side.BUY, size=100.0, timestamp=2.0)
    assert ok_order.status == OrderStatus.FILLED

    # 3. Price crashes to 0.050 -> mid = 0.055 -> unrealized loss = 100 * (0.055 - 0.500) = -$44.50
    # On $1000 capital, $44.50 loss is 4.45% drawdown -> trips 4% kill switch!
    book.apply_delta(Side.BUY, 0.050, 100.0)
    book.apply_delta(Side.SELL, 0.060, 100.0)
    broker._check_drawdown(timestamp=3.0)

    assert limits.is_kill_switch_triggered is True
    # Subsequent orders must be rejected
    next_order = broker.execute_market_order("tok_risk", Side.BUY, size=10.0, timestamp=4.0)
    assert next_order.status == OrderStatus.REJECTED


def test_replay_backtester_end_to_end():
    """Verify event-driven backtester produces complete report and latency metrics."""
    broker = PaperBroker(initial_cash=10_000.0)
    pnl = PnLEngine()
    backtester = ReplayBacktester(broker=broker, pnl_engine=pnl)

    # Generate synthetic stream of 200 book and trade ticks
    events = []
    base_ts = 1000.0
    asset = "tok_replay"

    for i in range(200):
        t = base_ts + (i * 0.5)
        dt = datetime.fromtimestamp(t, tz=UTC)
        p = round(0.45 + (math.sin(i / 10.0) * 0.05), 3)

        if i % 2 == 0:
            # Book event
            ev = BookEvent(
                event_id=f"bk_{i}",
                asset_id=asset,
                event_type=BookEventType.DELTA,
                side=Side.BUY if (i % 4 == 0) else Side.SELL,
                price=p,
                size=round(50.0 + (i % 50), 1),
                best_bid=p if (i % 4 == 0) else 0.44,
                best_ask=p if (i % 4 != 0) else 0.56,
                book_hash="0xhash",
                timestamp=dt,
            )
        else:
            # Trade event
            ev = Trade(
                event_id=f"tr_{i}",
                condition_id="c_replay",
                asset_id=asset,
                outcome_idx=0,
                maker_wallet=f"0xmaker_{i % 5}",
                taker_wallet=f"0xtaker_{i % 5}",
                side=Side.BUY if (i % 3 == 0) else Side.SELL,
                price=p,
                size=25.0,
                usd_value=p * 25.0,
                fee=0.01,
                source=TradeSource.WS_CLOB,
                tx_hash=f"0xtx_{i}",
                timestamp=dt,
            )
        events.append(ev)

    report = backtester.run(events)

    assert report.total_events_processed == 200
    assert report.final_equity > 0.0
    assert report.tick_to_order_p50_us >= 0.0
    assert len(report.equity_curve) > 0
    assert isinstance(report.summary(), str)
