-- ============================================================================
-- MarketTracker ClickHouse Production Schema
-- Optimized for high-throughput ingestion, deduplication, and low-latency queries
-- ============================================================================

CREATE DATABASE IF NOT EXISTS market_tracker;

-- ----------------------------------------------------------------------------
-- 1. MARKETS: Dimension table for Polymarket events and question metadata
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_tracker.markets
(
    condition_id     String CODEC(ZSTD(3)),
    market_id        String CODEC(ZSTD(3)),
    question         String CODEC(ZSTD(3)),
    slug             String CODEC(ZSTD(3)),
    category         LowCardinality(String),
    end_date         Nullable(DateTime64(3, 'UTC')),
    active           UInt8,
    closed           UInt8,
    accepting_orders UInt8,
    neg_risk         UInt8,
    fee_rate_bps     UInt16,
    updated_at       DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (condition_id, market_id);

-- ----------------------------------------------------------------------------
-- 2. OUTCOMES: Mapping of outcome slots to 77-digit ERC-1155 CLOB Token IDs
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_tracker.outcomes
(
    condition_id   String CODEC(ZSTD(3)),
    outcome_idx    UInt8,
    outcome_label  String CODEC(ZSTD(3)),
    asset_id       String CODEC(ZSTD(3)),
    updated_at     DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (condition_id, outcome_idx, asset_id);

-- ----------------------------------------------------------------------------
-- 3. TRADES: Time-series execution tape of public trades and on-chain fills
-- Deduplicated via deterministic event_id across WS, REST backfill, and on-chain
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_tracker.trades
(
    event_id       String CODEC(ZSTD(3)),
    condition_id   String CODEC(ZSTD(3)),
    asset_id       String CODEC(ZSTD(3)),
    outcome_idx    UInt8,
    maker_wallet   String CODEC(ZSTD(3)),
    taker_wallet   String CODEC(ZSTD(3)),
    side           Enum8('BUY' = 1, 'SELL' = 2),
    price          Float64 CODEC(Gorilla, ZSTD),
    size           Float64 CODEC(Gorilla, ZSTD),
    usd_value      Float64 CODEC(Gorilla, ZSTD),
    fee            Float64 CODEC(Gorilla, ZSTD),
    source         Enum8('WS_CLOB' = 1, 'REST_BACKFILL' = 2, 'ON_CHAIN' = 3, 'BULK_HIST' = 4),
    tx_hash        String CODEC(ZSTD(3)),
    timestamp      DateTime64(3, 'UTC') CODEC(DoubleDelta, ZSTD),
    ingested_at    DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(timestamp)
ORDER BY (condition_id, asset_id, timestamp, event_id);

-- ----------------------------------------------------------------------------
-- 4. BOOK_EVENTS: High-volume orderbook snapshots and incremental level deltas
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_tracker.book_events
(
    event_id       String CODEC(ZSTD(3)),
    asset_id       String CODEC(ZSTD(3)),
    event_type     Enum8('SNAPSHOT' = 1, 'DELTA' = 2),
    side           Enum8('BUY' = 1, 'SELL' = 2),
    price          Float64 CODEC(Gorilla, ZSTD),
    size           Float64 CODEC(Gorilla, ZSTD),
    best_bid       Float64 CODEC(Gorilla, ZSTD),
    best_ask       Float64 CODEC(Gorilla, ZSTD),
    book_hash      String CODEC(ZSTD(3)),
    timestamp      DateTime64(3, 'UTC') CODEC(DoubleDelta, ZSTD),
    ingested_at    DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (asset_id, timestamp, event_type);

-- ----------------------------------------------------------------------------
-- 5. SETTLEMENTS: Oracle market resolution and payout multipliers
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_tracker.settlements
(
    condition_id        String CODEC(ZSTD(3)),
    question_id         String CODEC(ZSTD(3)),
    oracle              String CODEC(ZSTD(3)),
    payout_numerators   Array(Float64),
    winning_outcome_idx Int16,
    tx_hash             String CODEC(ZSTD(3)),
    resolved_at         DateTime64(3, 'UTC') CODEC(DoubleDelta, ZSTD),
    updated_at          DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (condition_id, tx_hash);

