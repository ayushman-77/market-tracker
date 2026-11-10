from market_tracker.ingest.dedupe import DedupeFilter, make_trade_id
from market_tracker.ingest.gamma_client import GammaClient
from market_tracker.ingest.gap_detector import GapDetector


def test_dedupe_filter():
    dedupe = DedupeFilter(capacity=10)
    ev_id = "test_event_1"

    assert not dedupe.is_duplicate(ev_id)
    assert dedupe.is_duplicate(ev_id)
    assert dedupe.duplicate_count == 1
    assert dedupe.unique_count == 1


def test_make_trade_id_deterministic():
    id1 = make_trade_id("0xabc", "1", "123", "BUY", 0.5, 100.0)
    id2 = make_trade_id("0xabc", "1", "123", "BUY", 0.5, 100.0)
    id3 = make_trade_id("0xabc", "2", "123", "BUY", 0.5, 100.0)

    assert id1 == id2
    assert id1 != id3
    assert id1.startswith("tr_")


def test_gamma_stringified_array_parsing():
    client = GammaClient()
    raw_payload = {
        "id": "1234",
        "question": "Will BTC reach $100k?",
        "conditionId": "0xcondition123",
        "slug": "btc-100k",
        "outcomes": '["Yes", "No"]',
        "clobTokenIds": '["111222333", "444555666"]',
        "active": True,
        "closed": False,
        "acceptingOrders": True,
    }
    market = client._parse_market(raw_payload)

    assert market.outcomes == ["Yes", "No"]
    assert market.clob_token_ids == ["111222333", "444555666"]
    assert market.condition_id == "0xcondition123"


def test_gap_detector_disconnect_reconnect():
    detector = GapDetector(max_inactivity_seconds=1.0)
    detector.on_disconnect()
    gap = detector.on_reconnect()

    assert gap is not None
    assert gap.reason == "socket_disconnect"
    assert gap.end_time > gap.start_time
    assert detector.gap_count == 1
