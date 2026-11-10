from datetime import UTC, datetime
from typing import Any

import httpx

from market_tracker.common.config import settings
from market_tracker.common.logging import logger
from market_tracker.common.types import BookLevel, Side, Trade, TradeSource
from market_tracker.ingest.dedupe import make_trade_id


class DataClient:
    """REST Client for Polymarket Data API and CLOB REST backfill."""

    def __init__(
        self,
        data_api_url: str | None = None,
        clob_rest_url: str | None = None,
    ):
        self.data_api_url = (data_api_url or settings.data_api_url).rstrip("/")
        self.clob_rest_url = (clob_rest_url or settings.clob_rest_url).rstrip("/")
        self._client = httpx.AsyncClient(timeout=10.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def get_trades_backfill(
        self,
        condition_id: str | None = None,
        start_ts: float | None = None,
        end_ts: float | None = None,
        limit: int = 100,
    ) -> list[Trade]:
        """Fetch historical trades from Data API for gap backfill."""
        url = f"{self.data_api_url}/trades"
        params: dict[str, str] = {
            "limit": str(limit),
            "takerOnly": "false",
        }
        if condition_id:
            params["market"] = condition_id

        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            trades: list[Trade] = []
            for item in data:
                t = self._parse_trade(item)
                if t:
                    ts_val = t.timestamp.timestamp()
                    if start_ts is not None and ts_val < start_ts:
                        continue
                    if end_ts is not None and ts_val > end_ts:
                        continue
                    trades.append(t)
            return trades
        except Exception as e:
            logger.error(f"Failed to fetch trades from Data API: {e}")
            return []

    async def get_orderbook_snapshot(self, token_id: str) -> dict[str, list[BookLevel]]:
        """Fetch REST orderbook snapshot from CLOB API for drift reconciliation."""
        url = f"{self.clob_rest_url}/book"
        params = {"token_id": token_id}
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            bids = [
                BookLevel(price=float(b["price"]), size=float(b["size"]))
                for b in data.get("bids", [])
            ]
            asks = [
                BookLevel(price=float(a["price"]), size=float(a["size"]))
                for a in data.get("asks", [])
            ]
            return {"bids": bids, "asks": asks}
        except Exception as e:
            logger.error(f"Failed to fetch orderbook snapshot for {token_id}: {e}")
            return {"bids": [], "asks": []}

    def _parse_trade(self, raw: dict[str, Any]) -> Trade | None:
        try:
            tx_hash = raw.get("transactionHash") or "0x"
            asset_id = str(raw.get("asset", ""))
            price = float(raw.get("price", 0.0))
            size = float(raw.get("size", 0.0))
            side_str = str(raw.get("side", "BUY")).upper()
            side = Side.BUY if side_str == "BUY" else Side.SELL
            wallet = raw.get("proxyWallet") or "0x0000000000000000000000000000000000000000"
            raw_ts = raw.get("timestamp", 0)
            dt = datetime.fromtimestamp(float(raw_ts), tz=UTC)

            event_id = make_trade_id(
                tx_hash=tx_hash,
                identifier=str(raw_ts),
                asset_id=asset_id,
                side=side.value,
                price=price,
                size=size,
            )

            return Trade(
                event_id=event_id,
                condition_id=raw.get("conditionId", ""),
                asset_id=asset_id,
                outcome_idx=int(raw.get("outcomeIndex", 0)),
                maker_wallet=wallet if side == Side.SELL else "",
                taker_wallet=wallet if side == Side.BUY else "",
                side=side,
                price=price,
                size=size,
                usd_value=price * size,
                fee=0.0,
                source=TradeSource.REST_BACKFILL,
                tx_hash=tx_hash,
                timestamp=dt,
            )
        except Exception as e:
            logger.debug(f"Could not parse trade item: {e}")
            return None
