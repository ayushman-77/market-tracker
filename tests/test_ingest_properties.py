import random

from hypothesis import given
from hypothesis import strategies as st

from market_tracker.common.types import Side
from market_tracker.ingest.dedupe import DedupeFilter, make_trade_id
from market_tracker.ingest.gap_detector import GapDetector
from market_tracker.ingest.onchain import OnChainReader


@given(
    tx_hash=st.text(min_size=10, max_size=66, alphabet="0123456789abcdefABCDEF"),
    identifier=st.text(min_size=1, max_size=20, alphabet="0123456789"),
    asset_id=st.text(min_size=10, max_size=77, alphabet="0123456789"),
    side=st.sampled_from(["BUY", "SELL"]),
    price=st.floats(min_value=0.0001, max_value=0.9999, allow_nan=False),
    size=st.floats(min_value=0.01, max_value=1_000_000.0, allow_nan=False),
)
def test_property_trade_id_deterministic(tx_hash, identifier, asset_id, side, price, size):
    """Event ID must be deterministic and invariant to repeated calls."""
    id1 = make_trade_id(tx_hash, identifier, asset_id, side, price, size)
    id2 = make_trade_id(tx_hash, identifier, asset_id, side, price, size)
    assert id1 == id2
    assert id1.startswith("tr_")
    assert len(id1) == 19  # 'tr_' + 16 hex chars


@given(
    trades_data=st.lists(
        st.tuples(
            st.text(min_size=6, max_size=16, alphabet="0123456789abcdef"),
            st.floats(min_value=0.01, max_value=0.99, allow_nan=False),
            st.floats(min_value=1.0, max_value=100.0, allow_nan=False),
        ),
        min_size=5,
        max_size=100,
    )
)
def test_property_dedupe_filter_shuffled_stream(trades_data):
    """Processing a stream with arbitrary duplicates and shuffling must retain only unique events."""
    unique_ids = []
    for tx_hash, price, size in trades_data:
        ev_id = make_trade_id(tx_hash, "0", "token123", "BUY", price, size)
        unique_ids.append(ev_id)

    # Inject duplicate copies of every event
    noisy_stream = list(unique_ids) + list(unique_ids) + list(unique_ids[: len(unique_ids) // 2])
    random.shuffle(noisy_stream)

    filter_instance = DedupeFilter(capacity=len(unique_ids) * 2)
    emitted = []
    for ev_id in noisy_stream:
        if not filter_instance.is_duplicate(ev_id):
            emitted.append(ev_id)

    # Set of emitted must match unique IDs exactly, and count must equal unique count
    assert set(emitted) == set(unique_ids)
    assert len(emitted) == len(set(unique_ids))


@given(
    base_ts=st.floats(min_value=1_000_000, max_value=2_000_000, allow_nan=False),
    increments=st.lists(
        st.floats(min_value=0.01, max_value=2.0, allow_nan=False),
        min_size=5,
        max_size=50,
    ),
)
def test_property_gap_detector_continuous_stream(base_ts, increments):
    """A stream with increments strictly under max_inactivity (e.g. 5.0s) must trigger zero gaps."""
    detector = GapDetector(max_inactivity_seconds=5.0)
    current_ts = base_ts
    detector.last_seen_timestamp = current_ts

    for inc in increments:
        current_ts += inc
        detector.on_message_received(current_ts)

    assert detector.gap_count == 0


def test_onchain_order_filled_decoding():
    """Verify OrderFilled decoding into Trade struct."""
    reader = OnChainReader()
    # topics[0] = ORDER_FILLED_TOPIC
    # topics[1] = maker (address)
    # topics[2] = taker (address)
    topics = [
        "0xd0aab744f4a3e721528621424dfa052ff3725b822e379fe459b20756e09a349c",
        "0x0000000000000000000000001111111111111111111111111111111111111111",
        "0x0000000000000000000000002222222222222222222222222222222222222222",
    ]
    # data: makerAssetId (0=USDC), takerAssetId (token), makerAmountFilled (50 USDC = 50_000_000), takerAmountFilled (100 shares = 100_000_000), fee (0)
    chunk0 = f"{0:064x}"
    chunk1 = f"{123456789:064x}"
    chunk2 = f"{50_000_000:064x}"
    chunk3 = f"{100_000_000:064x}"
    chunk4 = f"{0:064x}"
    data_hex = "0x" + chunk0 + chunk1 + chunk2 + chunk3 + chunk4

    trade = reader.decode_order_filled(
        tx_hash="0xabcdef123456",
        log_index=1,
        topics=topics,
        data_hex=data_hex,
        block_timestamp=1700000000,
    )

    assert trade is not None
    assert trade.side == Side.BUY
    assert trade.price == 0.5  # 50 USDC / 100 shares
    assert trade.size == 100.0
    assert trade.maker_wallet.lower() == "0x1111111111111111111111111111111111111111"
    assert trade.taker_wallet.lower() == "0x2222222222222222222222222222222222222222"
