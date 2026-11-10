from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class TradeSource(StrEnum):
    WS_CLOB = "WS_CLOB"
    REST_BACKFILL = "REST_BACKFILL"
    ON_CHAIN = "ON_CHAIN"
    BULK_HIST = "BULK_HIST"


class BookEventType(StrEnum):
    SNAPSHOT = "SNAPSHOT"
    DELTA = "DELTA"


@dataclass(frozen=True)
class MarketMeta:
    condition_id: str
    market_id: str
    question: str
    slug: str
    category: str
    outcomes: list[str]
    clob_token_ids: list[str]
    active: bool
    closed: bool
    accepting_orders: bool
    neg_risk: bool = False
    fee_rate_bps: int = 0
    end_date: datetime | None = None


@dataclass(frozen=True)
class Trade:
    event_id: str
    condition_id: str
    asset_id: str
    outcome_idx: int
    maker_wallet: str
    taker_wallet: str
    side: Side
    price: float
    size: float
    usd_value: float
    fee: float
    source: TradeSource
    tx_hash: str
    timestamp: datetime
    ingested_at: datetime | None = None


@dataclass(frozen=True)
class BookLevel:
    price: float
    size: float


@dataclass(frozen=True)
class BookEvent:
    event_id: str
    asset_id: str
    event_type: BookEventType
    side: Side
    price: float
    size: float
    best_bid: float
    best_ask: float
    book_hash: str
    timestamp: datetime
    ingested_at: datetime | None = None


@dataclass(frozen=True)
class Settlement:
    condition_id: str
    question_id: str
    oracle: str
    payout_numerators: list[float]
    winning_outcome_idx: int
    tx_hash: str
    resolved_at: datetime
    updated_at: datetime | None = None
