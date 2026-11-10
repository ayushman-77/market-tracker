import json
from datetime import datetime
from typing import Any

import httpx

from market_tracker.common.config import settings
from market_tracker.common.logging import logger
from market_tracker.common.types import MarketMeta


class GammaClient:
    """Client for Polymarket Gamma API (Market metadata, outcomes, CLOB Token IDs)."""

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.gamma_api_url).rstrip("/")
        self._client = httpx.AsyncClient(timeout=10.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def get_active_markets(self, limit: int = 100) -> list[MarketMeta]:
        """Fetch active, open markets with parsed outcomes and token IDs."""
        url = f"{self.base_url}/markets"
        params = {
            "active": "true",
            "closed": "false",
            "limit": str(limit),
        }
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return [self._parse_market(item) for item in data if isinstance(item, dict)]
        except Exception as e:
            logger.error(f"Failed to fetch active markets from Gamma API: {e}")
            return []

    def _parse_market(self, raw: dict[str, Any]) -> MarketMeta:
        """Safely parse Gamma market payload, handling the stringified array trap."""
        outcomes_raw = raw.get("outcomes", "[]")
        if isinstance(outcomes_raw, str):
            try:
                outcomes = json.loads(outcomes_raw)
            except Exception:
                outcomes = [outcomes_raw]
        else:
            outcomes = list(outcomes_raw)

        clob_ids_raw = raw.get("clobTokenIds", "[]")
        if isinstance(clob_ids_raw, str):
            try:
                clob_token_ids = json.loads(clob_ids_raw)
            except Exception:
                clob_token_ids = [clob_ids_raw]
        else:
            clob_token_ids = list(clob_ids_raw)

        end_date_raw = raw.get("endDate") or raw.get("end_date_iso")
        end_date = None
        if end_date_raw:
            try:
                end_date = datetime.fromisoformat(end_date_raw.replace("Z", "+00:00"))
            except Exception:
                pass

        return MarketMeta(
            condition_id=raw.get("conditionId") or raw.get("condition_id") or "",
            market_id=str(raw.get("id", "")),
            question=raw.get("question", ""),
            slug=raw.get("slug", ""),
            category=raw.get("category", "General"),
            outcomes=[str(o) for o in outcomes],
            clob_token_ids=[str(t) for t in clob_token_ids],
            active=bool(raw.get("active", True)),
            closed=bool(raw.get("closed", False)),
            accepting_orders=bool(raw.get("acceptingOrders", True)),
            neg_risk=bool(raw.get("negRisk", False)),
            fee_rate_bps=int(raw.get("fee", 0)),
            end_date=end_date,
        )
