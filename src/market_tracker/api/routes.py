"""FastAPI REST routes for MarketTracker."""

from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from market_tracker.api.catalog import CATEGORIES
from market_tracker.api.delta_stream import stream_manager
from market_tracker.api.state import state
from market_tracker.common.types import Side

router = APIRouter()


class OrderRequest(BaseModel):
    asset_id: str
    side: str  # "BUY" or "SELL"
    size: float
    price: float | None = None  # None for aggressive market order, float for passive limit order


@router.get("/health")
def get_health():
    return {
        "status": "healthy",
        "service": "market-tracker",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/metrics")
def get_metrics():
    uptime = (datetime.now(UTC) - state.start_time).total_seconds()
    rate = state.total_ticks_processed / max(1.0, uptime)
    return {
        "status": "healthy",
        "uptime_seconds": round(uptime, 1),
        "sustained_rows_sec": round(rate, 1),
        "total_ticks": state.total_ticks_processed,
        "total_trades": state.total_trades_processed,
        "total_deltas": state.total_deltas_processed,
        "queue_depth": len(stream_manager._pending_book_deltas)
        + len(stream_manager._pending_trades),
        "connected_ws_clients": len(stream_manager.active_connections),
        "reconnect_count": state.reconnect_count,
        "gap_count": state.gap_count,
        "last_tick_timestamp": state.last_tick_timestamp.isoformat(),
    }


@router.get("/api/markets")
def get_markets():
    return [
        {
            "asset_id": m.asset_id,
            "condition_id": m.condition_id,
            "event_id": m.event_id,
            "question": m.question,
            "event_question": m.event_question,
            "outcome_label": m.outcome_label,
            "candidate_name": m.candidate_name,
            "category": m.category,
            "slug": m.slug,
            "paired_asset_id": m.paired_asset_id,
            "tick_size": m.tick_size,
        }
        for m in state.markets.values()
    ]


@router.get("/api/events")
def get_events(category: str | None = Query(default=None)):
    events = state.get_events_payload(category=category)
    return {
        "categories": list(CATEGORIES),
        "count": len(events),
        "events": events,
    }


@router.get("/api/events/{event_id}")
def get_event_detail(event_id: str):
    if event_id not in state.events:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
    for ev in state.get_events_payload():
        if ev["event_id"] == event_id:
            return ev
    raise HTTPException(status_code=404, detail=f"Event {event_id} not found")


@router.get("/api/candles/{asset_id}")
def get_candles(asset_id: str, tf: str = Query(default="15M")):
    if asset_id not in state.markets:
        raise HTTPException(status_code=404, detail=f"Market {asset_id} not found")
    state.active_sim_asset_id = asset_id
    return state.get_candles_payload(asset_id=asset_id, timeframe=tf)


@router.get("/api/book/{asset_id}")
def get_orderbook(asset_id: str, depth: int = Query(default=25, ge=5, le=100)):
    book = state.orderbooks.get(asset_id)
    if not book:
        raise HTTPException(status_code=404, detail=f"Market {asset_id} not found")

    ladder = book.get_ladder(depth=depth)
    ladder_dict = asdict(ladder)
    ladder_dict["sequence"] = stream_manager.seq_numbers["book"]
    return ladder_dict


@router.get("/api/leaderboard")
def get_leaderboard(limit: int = Query(default=100, ge=5, le=100)):
    wallets = state.pnl_engine.get_leaderboard(top_n=limit)
    return {
        "count": len(wallets),
        "sequence": stream_manager.seq_numbers["leaderboard"],
        "wallets": [asdict(w) for w in wallets],
    }


@router.get("/api/wallets/{wallet_address}")
def get_wallet_drilldown(wallet_address: str):
    positions = []
    total_realized = 0.0
    total_unrealized = 0.0
    total_fees = 0.0

    for asset_id in state.markets:
        pos = state.pnl_engine.get_position(wallet_address, asset_id)
        if pos and (
            abs(pos.size) > 1e-9 or abs(pos.realized_pnl) > 1e-9 or abs(pos.fees_paid) > 1e-9
        ):
            total_realized += pos.realized_pnl
            total_unrealized += pos.unrealized_pnl
            total_fees += pos.fees_paid
            positions.append(asdict(pos))

    net_pnl = total_realized + total_unrealized

    pnl_history = list(state.wallet_pnl_snapshots.get(wallet_address, []))
    if not pnl_history:
        pnl_history = [(datetime.now(UTC).timestamp(), net_pnl)]

    recent_trades = [
        {
            "event_id": t.event_id,
            "asset_id": t.asset_id,
            "side": "BUY" if t.side == Side.BUY else "SELL",
            "price": t.price,
            "size": t.size,
            "usd_value": t.usd_value,
            "fee": t.fee,
            "timestamp": t.timestamp.isoformat(),
        }
        for t in list(state.wallet_trade_history.get(wallet_address, []))[-20:]
    ]

    return {
        "wallet": wallet_address,
        "total_pnl": round(net_pnl, 2),
        "realized_pnl": round(total_realized, 2),
        "unrealized_pnl": round(total_unrealized, 2),
        "total_fees": round(total_fees, 2),
        "positions": positions,
        "pnl_history": [{"timestamp": t, "pnl": round(p, 2)} for t, p in pnl_history],
        "recent_trades": recent_trades,
    }


@router.get("/api/trades")
def get_trades(limit: int = Query(default=50, ge=1, le=100)):
    trades = list(state.recent_trades)[:limit]
    return [
        {
            "event_id": t.event_id,
            "asset_id": t.asset_id,
            "maker_wallet": t.maker_wallet,
            "taker_wallet": t.taker_wallet,
            "side": "BUY" if t.side == Side.BUY else "SELL",
            "price": t.price,
            "size": t.size,
            "usd_value": t.usd_value,
            "fee": t.fee,
            "timestamp": t.timestamp.isoformat(),
        }
        for t in trades
    ]


@router.get("/api/paper/status")
def get_paper_status():
    return state.get_paper_status_payload()


@router.post("/api/paper/order")
def submit_paper_order(req: OrderRequest):
    book = state.orderbooks.get(req.asset_id)
    if not book:
        raise HTTPException(status_code=404, detail=f"Market {req.asset_id} not found")

    side = Side.BUY if req.side.upper() == "BUY" else Side.SELL
    now = datetime.now(UTC)

    if req.price is not None:
        order = state.paper_broker.submit_passive_order(
            req.asset_id, side, req.price, req.size, timestamp=now.timestamp()
        )
    else:
        order = state.paper_broker.execute_market_order(
            req.asset_id, side, req.size, timestamp=now.timestamp()
        )

    stream_manager.queue_paper_update(
        "manual_order",
        {
            "order_id": order.order_id,
            "status": order.status.value,
            "filled_size": order.filled_size,
            "avg_price": order.avg_fill_price,
        },
    )

    return {
        "order_id": order.order_id,
        "status": order.status.value,
        "filled_size": order.filled_size,
        "avg_fill_price": order.avg_fill_price,
        "fees": order.total_fees,
    }


@router.post("/api/paper/reset")
def reset_paper_portfolio():
    state.paper_broker.cash = 50_000.0
    state.paper_broker.peak_equity = 50_000.0
    state.paper_broker.realized_pnl = 0.0
    state.paper_broker.total_fees = 0.0
    state.paper_broker.positions.clear()
    state.paper_broker.cost_bases.clear()
    state.paper_broker.open_passive_orders.clear()
    state.paper_broker.fill_history.clear()
    state.paper_broker.risk_limits.is_kill_switch_triggered = False

    return {"status": "reset", "cash": 50_000.0}
