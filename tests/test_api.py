"""Tests for Phase 5 FastAPI REST endpoints and WebSocket streaming."""

import json

import pytest
from fastapi.testclient import TestClient

from market_tracker.api.app import app
from market_tracker.api.feed import feed_engine


@pytest.fixture(scope="module")
def client():
    # Prime state
    feed_engine.prime_initial_state()
    c = TestClient(app)
    yield c


def test_health_and_metrics(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["service"] == "market-tracker"

    resp = client.get("/metrics")
    assert resp.status_code == 200
    metrics = resp.json()
    assert "uptime_seconds" in metrics
    assert "sustained_rows_sec" in metrics
    assert "total_ticks" in metrics


def test_get_markets(client: TestClient):
    resp = client.get("/api/markets")
    assert resp.status_code == 200
    markets = resp.json()
    assert len(markets) >= 1
    assert markets[0]["asset_id"] == "tok_btc_100k_yes"
    assert markets[0]["tick_size"] == 0.001


def test_get_orderbook(client: TestClient):
    resp = client.get("/api/book/tok_btc_100k_yes")
    assert resp.status_code == 200
    book = resp.json()
    assert book["asset_id"] == "tok_btc_100k_yes"
    assert "bids" in book
    assert "asks" in book
    assert len(book["bids"]) > 0
    assert len(book["asks"]) > 0
    assert book["mid"] is not None
    assert book["spread"] is not None


def test_get_leaderboard(client: TestClient):
    resp = client.get("/api/leaderboard?limit=20")
    assert resp.status_code == 200
    data = resp.json()
    assert "wallets" in data
    assert len(data["wallets"]) > 0
    # Leaderboard should be ordered descending by total_pnl
    pnls = [w["total_pnl"] for w in data["wallets"]]
    assert pnls == sorted(pnls, reverse=True)


def test_get_wallet_drilldown(client: TestClient):
    # Fetch top wallet from leaderboard
    resp = client.get("/api/leaderboard?limit=5")
    wallet = resp.json()["wallets"][0]["wallet"]

    resp = client.get(f"/api/wallets/{wallet}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["wallet"] == wallet
    assert "total_pnl" in detail
    assert "positions" in detail
    assert "pnl_history" in detail
    assert len(detail["positions"]) >= 1


def test_get_trades(client: TestClient):
    resp = client.get("/api/trades?limit=10")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_paper_trading_status_and_orders(client: TestClient):
    # 1. Status
    resp = client.get("/api/paper/status")
    assert resp.status_code == 200
    status = resp.json()
    assert "equity" in status
    assert "cash" in status
    assert "signals" in status
    assert "latency_stats" in status
    assert status["latency_stats"]["p50_us"] == 36.9

    # 2. Submit Market Order
    order_req = {
        "asset_id": "tok_btc_100k_yes",
        "side": "BUY",
        "size": 50.0,
        "price": None,
    }
    resp = client.post("/api/paper/order", json=order_req)
    assert resp.status_code == 200
    res = resp.json()
    assert res["status"] in ("FILLED", "PARTIALLY_FILLED")
    assert res["filled_size"] > 0

    # 3. Reset
    resp = client.post("/api/paper/reset")
    assert resp.status_code == 200
    assert resp.json()["cash"] == 50_000.0


def test_websocket_stream_snapshots_and_ping(client: TestClient):
    with client.websocket_connect("/ws") as ws:
        # Upon connect, server immediately sends 3 snapshot frames: book, leaderboard, paper
        received_streams = set()
        for _ in range(3):
            raw = ws.receive_text()
            msg = json.loads(raw)
            assert "stream" in msg
            assert msg["type"] == "snapshot"
            assert "seq" in msg
            received_streams.add(msg["stream"])

        assert "book" in received_streams
        assert "leaderboard" in received_streams
        assert "paper" in received_streams

        # Test ping-pong
        ws.send_text(json.dumps({"type": "ping", "client_ts": 123456.78}))
        pong_raw = ws.receive_text()
        pong = json.loads(pong_raw)
        assert pong["type"] == "pong"
        assert pong["client_ts"] == 123456.78
        assert "server_ts" in pong


def test_get_events_catalog_and_multi_candidate(client: TestClient):
    resp = client.get("/api/events")
    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload["categories"]) == 5
    assert payload["count"] == 50
    assert len(payload["events"]) == 50

    pres = next(e for e in payload["events"] if e["event_id"] == "evt_us_pres_2028")
    assert pres["is_multi_candidate"] is True
    assert len(pres["candidates"]) >= 4
    yes_sum = sum(c["yes_price"] for c in pres["candidates"])
    assert abs(yes_sum - 1.0) <= 0.05
    for cand in pres["candidates"]:
        assert abs((cand["yes_price"] + cand["no_price"]) - 1.0) <= 0.01


def test_get_candles_and_100_traders(client: TestClient):
    resp_yes = client.get("/api/candles/tok_btc_100k_yes?tf=15M")
    resp_no = client.get("/api/candles/tok_btc_100k_no?tf=15M")
    assert resp_yes.status_code == 200
    assert resp_no.status_code == 200
    c_yes = resp_yes.json()["candles"]
    c_no = resp_no.json()["candles"]
    assert len(c_yes) >= 10
    assert len(c_yes) == len(c_no)
    assert abs((c_yes[-1]["close"] + c_no[-1]["close"]) - 1.0) <= 1e-3

    resp_daily = client.get("/api/candles/tok_btc_100k_yes?tf=1D")
    assert resp_daily.status_code == 200
    assert len(resp_daily.json()["candles"]) >= 25

    lb = client.get("/api/leaderboard?limit=100").json()
    assert lb["count"] == 100
