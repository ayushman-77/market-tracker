"""WebSocket endpoint router for MarketTracker real-time streaming."""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from market_tracker.api.delta_stream import stream_manager
from market_tracker.api.state import state

logger = logging.getLogger("market_tracker.ws")
router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time streaming WebSocket endpoint pushing sequence-tracked deltas at 20 Hz."""
    await stream_manager.connect(websocket)
    try:
        # Send initial snapshot on connect so UI renders immediately
        await stream_manager.handle_client_message(
            websocket=websocket,
            text='{"type": "subscribe", "stream": null}',
            app_state=state,
        )

        while True:
            text = await websocket.receive_text()
            await stream_manager.handle_client_message(websocket, text, state)

    except WebSocketDisconnect:
        await stream_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket client error: {e}")
        await stream_manager.disconnect(websocket)
