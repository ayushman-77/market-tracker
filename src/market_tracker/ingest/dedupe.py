import hashlib
from collections import OrderedDict


class DedupeFilter:
    """Bounded LRU filter for fast, in-memory duplicate detection.

    Drops redundant events before they hit queues or the database.
    ClickHouse ReplacingMergeTree provides the secondary, persistent guarantee.
    """

    def __init__(self, capacity: int = 500_000):
        self.capacity = capacity
        self._seen: OrderedDict[str, None] = OrderedDict()
        self.duplicate_count = 0
        self.unique_count = 0

    def is_duplicate(self, event_id: str) -> bool:
        if event_id in self._seen:
            self._seen.move_to_end(event_id)
            self.duplicate_count += 1
            return True

        self._seen[event_id] = None
        self.unique_count += 1
        if len(self._seen) > self.capacity:
            self._seen.popitem(last=False)
        return False

    def clear(self) -> None:
        self._seen.clear()
        self.duplicate_count = 0
        self.unique_count = 0


def make_trade_id(
    tx_hash: str,
    identifier: str,
    asset_id: str,
    side: str,
    price: float,
    size: float,
) -> str:
    """Create a deterministic unique event_id for a trade fill."""
    raw = f"{tx_hash.lower()}:{identifier}:{asset_id}:{side}:{price:.6f}:{size:.6f}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"tr_{digest}"


def make_book_event_id(
    asset_id: str,
    timestamp_ms: int,
    side: str,
    price: float,
    size: float,
) -> str:
    """Create a deterministic unique event_id for an orderbook delta/snapshot."""
    raw = f"{asset_id}:{timestamp_ms}:{side}:{price:.6f}:{size:.6f}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"bk_{digest}"


def make_settlement_id(condition_id: str, tx_hash: str) -> str:
    """Create a deterministic event_id for market resolution."""
    raw = f"{condition_id.lower()}:{tx_hash.lower()}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"res_{digest}"
