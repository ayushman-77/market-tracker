from datetime import UTC, datetime

import httpx

from market_tracker.common.config import settings
from market_tracker.common.logging import logger
from market_tracker.common.types import Settlement, Side, Trade, TradeSource
from market_tracker.ingest.dedupe import make_trade_id

# Contract Addresses on Polygon PoS
CTF_EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
CONDITIONAL_TOKENS_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

# Event Signatures (keccak256 topics)
# OrderFilled(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)
ORDER_FILLED_TOPIC = "0xd0aab744f4a3e721528621424dfa052ff3725b822e379fe459b20756e09a349c"
# ConditionResolution(bytes32,address,bytes32,uint256,uint256[])
CONDITION_RESOLUTION_TOPIC = "0x16b0d9193be5893a9e334a1b0213aa89eb86d6560b08092288344e27f6b216fb"


class OnChainReader:
    """Reader for Polygon CTF Exchange fills and ConditionalTokens settlement events."""

    def __init__(self, rpc_url: str | None = None):
        self.rpc_url = rpc_url or settings.polygon_rpc_url
        self._http = httpx.AsyncClient(timeout=10.0)

    async def close(self) -> None:
        await self._http.aclose()

    def decode_order_filled(
        self,
        tx_hash: str,
        log_index: int,
        topics: list[str],
        data_hex: str,
        block_timestamp: int,
    ) -> Trade | None:
        """Decode raw Polygon OrderFilled event into a Trade record."""
        try:
            # topics[1] = maker (address padded to 32 bytes)
            # topics[2] = taker (address padded to 32 bytes)
            maker = "0x" + topics[1][-40:]
            taker = "0x" + topics[2][-40:]

            # data contains: makerAssetId, takerAssetId, makerAmountFilled, takerAmountFilled, fee
            clean_data = data_hex[2:] if data_hex.startswith("0x") else data_hex
            chunks = [clean_data[i : i + 64] for i in range(0, len(clean_data), 64)]

            maker_asset_id = int(chunks[0], 16)
            taker_asset_id = int(chunks[1], 16)
            maker_amount = int(chunks[2], 16) / 1e6
            taker_amount = int(chunks[3], 16) / 1e6
            fee = int(chunks[4], 16) / 1e6 if len(chunks) > 4 else 0.0

            # If makerAssetId == 0, maker gave USDC to buy tokens (taker sold tokens)
            if maker_asset_id == 0:
                side = Side.BUY
                asset_id = str(taker_asset_id)
                size = taker_amount
                price = maker_amount / max(0.000001, taker_amount)
            else:
                side = Side.SELL
                asset_id = str(maker_asset_id)
                size = maker_amount
                price = taker_amount / max(0.000001, maker_amount)

            dt = datetime.fromtimestamp(block_timestamp, tz=UTC)
            event_id = make_trade_id(
                tx_hash=tx_hash,
                identifier=str(log_index),
                asset_id=asset_id,
                side=side.value,
                price=price,
                size=size,
            )

            return Trade(
                event_id=event_id,
                condition_id="",
                asset_id=asset_id,
                outcome_idx=0,
                maker_wallet=maker,
                taker_wallet=taker,
                side=side,
                price=price,
                size=size,
                usd_value=price * size,
                fee=fee,
                source=TradeSource.ON_CHAIN,
                tx_hash=tx_hash,
                timestamp=dt,
            )
        except Exception as e:
            logger.debug(f"Failed to decode OrderFilled event: {e}")
            return None

    def decode_condition_resolution(
        self,
        tx_hash: str,
        topics: list[str],
        data_hex: str,
        block_timestamp: int,
    ) -> Settlement | None:
        """Decode ConditionResolution event into a Settlement record."""
        try:
            condition_id = topics[1] if len(topics) > 1 else ""
            oracle = "0x" + topics[2][-40:] if len(topics) > 2 else ""
            question_id = topics[3] if len(topics) > 3 else ""

            dt = datetime.fromtimestamp(block_timestamp, tz=UTC)
            # Default binary outcome payout [1.0, 0.0] or [0.0, 1.0]
            winning_idx = 0

            return Settlement(
                condition_id=condition_id,
                question_id=question_id,
                oracle=oracle,
                payout_numerators=[1.0, 0.0],
                winning_outcome_idx=winning_idx,
                tx_hash=tx_hash,
                resolved_at=dt,
            )
        except Exception as e:
            logger.debug(f"Failed to decode ConditionResolution event: {e}")
            return None
