"""FastAPI Main Application for MarketTracker."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from market_tracker.api.delta_stream import stream_manager
from market_tracker.api.feed import feed_engine
from market_tracker.api.routes import router as api_router
from market_tracker.api.state import state
from market_tracker.api.ws import router as ws_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("market_tracker.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the real-time simulation feed and delta push worker on startup."""
    logger.info("Initializing MarketTracker real-time engine...")
    feed_engine.start()
    stream_manager.start(state)
    yield
    logger.info("Shutting down MarketTracker engines...")
    feed_engine.stop()
    stream_manager.stop()


app = FastAPI(
    title="MarketTracker Engine",
    description="High-performance real-time PnL and orderbook engine for Polymarket",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include REST routes and WebSocket router
app.include_router(api_router)
app.include_router(ws_router)

# Mount web dist if built
dist_dir = Path(__file__).resolve().parent.parent.parent.parent / "web" / "dist"
if dist_dir.exists():
    app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="static")


def start():
    """CLI entrypoint to run the API server."""
    import uvicorn

    uvicorn.run("market_tracker.api.app:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    start()
