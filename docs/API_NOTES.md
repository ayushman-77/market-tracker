# Polymarket Official API & Protocol Documentation Notes

> **Notice:** All endpoints, data schemas, rate limits, and contract addresses documented here were verified against official Polymarket documentation, developer guides, public contract repositories, and real API endpoints as of November 2024 / 2025.

---

## 1. Architecture Overview & Core Endpoints

Polymarket is built as a hybrid architecture:
1. **Central Limit Order Book (CLOB):** High-frequency off-chain matching engine and WebSocket distribution layer.
2. **Gamma API:** Off-chain catalog, event discovery, search, and market metadata engine.
3. **Data API:** Historical trade execution tape, user positions, and wallet activity indexing.
4. **Polygon PoS Smart Contracts:** On-chain atomic settlement, token minting/splitting, and oracle condition resolution.

| Service | Protocol / Base URL | Purpose | Authentication |
| :--- | :--- | :--- | :--- |
| **CLOB REST API** | `https://clob.polymarket.com` | Order submission, L2 book queries, midpoint, spread | Public for reads; L2 HMAC for writes |
| **CLOB WebSocket (Market)** | `wss://ws-subscriptions-clob.polymarket.com/ws/market` | Real-time L2 orderbook deltas, snapshots, last trade price | **Public (No auth)** |
| **CLOB WebSocket (User)** | `wss://ws-subscriptions-clob.polymarket.com/ws/user` | Private user order fills, cancellations, balances | L2 API Key + Passphrase + Secret |
| **Gamma API** | `https://gamma-api.polymarket.com` | Market discovery, question metadata, token IDs, tags | **Public (No auth)** |
| **Data API** | `https://data-api.polymarket.com` | Historical trades, user positions, past activity | **Public (No auth)** |
| **PolyBolt Reference WS** | `wss://ws-live-v2.polymarket.com/ws` | Crypto & equity spot price reference streams | Auth required |
| **Polygon PoS RPC** | Public RPC / `https://polygon-rpc.com` | On-chain settlement logs (`OrderFilled`, `ConditionResolution`) | Public JSON-RPC |

---

## 2. CLOB WebSocket: Market Channel

- **Endpoint:** `wss://ws-subscriptions-clob.polymarket.com/ws/market`
- **Auth:** None (Public).

### 2.1 Subscription Protocol
Clients must subscribe by sending a JSON frame containing an array of 77-digit **Asset IDs** (`assets_ids`), which correspond to the ERC-1155 token IDs of the market outcomes (obtained via Gamma API `clobTokenIds`):

```json
{
  "type": "market",
  "assets_ids": [
    "71238912739182371982371982371982371982371982371982371982371982371982371982371",
    "98412893712893712893712893712893712893712893712893712893712893712893712893712"
  ],
  "custom_feature_enabled": true
}
```
> [!IMPORTANT]
> The subscription property is strictly named `assets_ids` (with an "s"). Using `asset_ids` or `tokens` will cause silent drops or an error frame.

### 2.2 Heartbeat Requirements (Keepalive)
- Clients **must send a text frame `"PING"` roughly every 10 seconds**.
- The server responds with `"PONG"`.
- If no ping is received within ~15–20 seconds, the server abruptly terminates the WebSocket connection.

### 2.3 Message Payloads & Event Schemas

#### A. `book` (Initial Snapshot & Re-anchoring)
Sent immediately upon subscription and periodically after major market state shifts:
```json
{
  "event_type": "book",
  "asset_id": "71238912739182371982371982371982371982371982371982371982371982371982371982371",
  "market": "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
  "bids": [
    { "price": "0.48", "size": "1500.00" },
    { "price": "0.47", "size": "3200.50" }
  ],
  "asks": [
    { "price": "0.52", "size": "2100.00" },
    { "price": "0.53", "size": "4500.00" }
  ],
  "timestamp": "1739827200123",
  "hash": "0x9f83ab...31"
}
```
*Note: `timestamp` is a Unix epoch in milliseconds as a string. `hash` is an orderbook state checksum.*

#### B. `price_change` (Incremental Level Deltas)
Sent whenever an individual order is placed, updated, or canceled:
```json
{
  "event_type": "price_change",
  "market": "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
  "price_changes": [
    {
      "asset_id": "71238912739182371982371982371982371982371982371982371982371982371982371982371",
      "price": "0.48",
      "size": "1800.00",
      "side": "BUY",
      "best_bid": "0.48",
      "best_ask": "0.52",
      "hash": "0xabc..."
    }
  ],
  "timestamp": "1739827200450"
}
```
*Rule: If `size` is `"0"` (or `"0.00"`), that price level has been emptied and must be removed from the book.*

#### C. `last_trade_price` (Public Trade Execution)
Broadcast immediately when a match executes on the matching engine:
```json
{
  "event_type": "last_trade_price",
  "asset_id": "71238912739182371982371982371982371982371982371982371982371982371982371982371",
  "price": "0.485",
  "size": "500.00",
  "side": "BUY",
  "fee_rate_bps": 0,
  "timestamp": "1739827200512"
}
```

---

## 3. Gamma API: Market & Event Metadata

- **Base URL:** `https://gamma-api.polymarket.com`
- **Key Endpoints:**
  - `GET /markets?active=true&closed=false&limit=100`: List active tradeable markets.
  - `GET /events?slug={slug}` or `GET /events/{id}`: Detailed event hierarchy.
  - `GET /public-search?q={query}`: Market full-text search.

### 3.1 The Stringified Array Parser Trap
In Gamma API responses, several array fields are **serialized JSON strings**, not native JSON arrays:
- `outcomes`: e.g. `"[\"Yes\", \"No\"]"`
- `outcomePrices`: e.g. `"[\"0.65\", \"0.35\"]"`
- `clobTokenIds`: e.g. `"[\"712389...\", \"984128...\"]"`

Failure to parse these with `json.loads()` will treat the entire array string as a single scalar or raise parsing exceptions.

### 3.2 Sample Market Schema
```json
{
  "id": "12345",
  "question": "Will BTC break $100k before Dec 31, 2024?",
  "conditionId": "0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
  "slug": "btc-100k-dec-2024",
  "active": true,
  "closed": false,
  "acceptingOrders": true,
  "outcomes": "[\"Yes\", \"No\"]",
  "outcomePrices": "[\"0.72\", \"0.28\"]",
  "clobTokenIds": "[\"71238912739182371982371982371982371982371982371982371982371982371982371982371\", \"98412893712893712893712893712893712893712893712893712893712893712893712893712\"]",
  "volume": 12543920.45,
  "volume24hr": 450123.10,
  "liquidity": 892301.22
}
```

---

## 4. Data API: Public Historical Trades & Positions

- **Base URL:** `https://data-api.polymarket.com`
- **Key Endpoint:** `GET /trades` (or `GET /trades?market={conditionId}&limit=100&takerOnly=false`)

### 4.1 Schema Fields
```json
[
  {
    "proxyWallet": "0x56a4b1234567890abcdef1234567890abcdef12",
    "side": "BUY",
    "asset": "71238912739182371982371982371982371982371982371982371982371982371982371982371",
    "conditionId": "0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
    "size": 250.0,
    "price": 0.48,
    "timestamp": 1739827200,
    "transactionHash": "0x5b39...82a1",
    "outcome": "Yes",
    "outcomeIndex": 0
  }
]
```
- Query parameter `takerOnly=false` retrieves both maker and taker fills.
- `proxyWallet` denotes the execution smart wallet for the user on Polymarket.

---

## 5. Polygon Smart Contracts & Settlement Events

Polymarket settles all trades and redemptions on Polygon PoS (Chain ID: 137).

### 5.1 Verified Contract Addresses
- **ConditionalTokens (CTF Framework, ERC-1155):** `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045`
- **CTF Exchange (Binary Markets):** `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E`
- **Neg Risk CTF Exchange (Multi-Outcome):** `0xC5d563A36AE78145C45a50134d48A1215220f80a`
- **Neg Risk Adapter:** `0xd91E809d02E80ba255B668666679B5f80b9101d2`
- **Collateral Token (Bridged USDC.e):** `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` (6 decimals)
- **Native USDC:** `0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359` (6 decimals)

### 5.2 Solidity Event Signatures

#### A. Trade Settlement on CTF Exchange: `OrderFilled`
```solidity
event OrderFilled(
    bytes32 indexed orderHash,
    address indexed maker,
    address indexed taker,
    uint256 makerAssetId,
    uint256 takerAssetId,
    uint256 makerAmountFilled,
    uint256 takerAmountFilled,
    uint256 fee
);
```
- Asset ID `0` represents the collateral token (USDC).
- Non-zero Asset ID is the ERC-1155 conditional token ID.
- Amounts are in 6 decimal fixed-point integers ($1.00 = 1,000,000$).

#### B. Market Resolution on ConditionalTokens: `ConditionResolution`
```solidity
event ConditionResolution(
    bytes32 indexed conditionId,
    address indexed oracle,
    bytes32 indexed questionId,
    uint outcomeSlotCount,
    uint[] payoutNumerators
);
```
- `payoutNumerators`: Payout vector for each slot (e.g. `[1, 0]` means outcome 0 wins 100%, `[0, 1]` means outcome 1 wins 100%, `[5000, 5000]` means 50/50 split).

#### C. Payout Redemption on ConditionalTokens: `PayoutRedemption`
```solidity
event PayoutRedemption(
    address indexed redeemer,
    IERC20 indexed collateralToken,
    bytes32 indexed parentCollectionId,
    bytes32 conditionId,
    uint[] indexSets,
    uint payout
);
```
- Emitted when a user burns winning conditional tokens in exchange for USDC collateral.

---

## 6. Fee Structure

Polymarket applies an asymmetric, category-dependent fee schedule:

1. **Maker Fees:** **0% (0 bps)** across all markets. Makers earn daily USDC rebates funded by taker fees in eligible markets.
2. **General Event Markets (Politics, Culture, Macro):** **0% taker fee (0 bps)**.
3. **High-Velocity Short-Duration Markets (15-min Crypto intervals BTC/ETH/SOL):**
   Dynamic taker fee scaled by price uncertainty:
   $$\text{Fee} = \text{size} \times \text{feeRate} \times p \times (1 - p)$$
   - Peak fee is at $p = 0.50$ (maximum volatility / uncertainty).
   - Fee converges to $0$ as $p \to 0$ or $p \to 1$.

---

## 7. Sequence Numbers, Gaps & Idempotency Strategy

### 7.1 Gap Detection Realities
1. **No Monotonic Sequence Numbers in Public WS:**
   Unlike some crypto exchanges that emit an incrementing `seq_id`, Polymarket's public CLOB WebSocket does **not** provide integer sequence numbers on market updates.
2. **Detection Mechanics:**
   - **Timestamp Discontinuity:** If no message or heartbeat is received within expected jitter thresholds ($> \Delta t_{max}$), the connection is presumed stale.
   - **Orderbook State Hash Check:** The `hash` field on `book` snapshots and price changes provides a checksum of the orderbook. A discrepancy against a fresh REST `/book` snapshot flags a state desynchronization.
   - **Reconnect Windows:** Any disconnect event triggers a recorded downtime interval $[t_{\text{disconnect}} - \delta, t_{\text{reconnect}}]$. The pipeline immediately triggers a REST backfill over this interval.

### 7.2 Deterministic Event IDs for ClickHouse Idempotency
To guarantee that backfills and replays never double-count trades or positions:
- **On-chain trades:** `fill:{tx_hash}:{log_index}`
- **CLOB trades:** `trade:{transaction_hash}:{timestamp}:{asset_id}` (or `trade:{trade_id}` if provided by Data API)
- **Orderbook snapshots:** `snap:{asset_id}:{timestamp}:{hash}`
- **Settlement events:** `res:{condition_id}:{tx_hash}`

These deterministic keys feed into ClickHouse `ReplacingMergeTree`, ensuring that re-insertions overwrite without duplicating rows.

