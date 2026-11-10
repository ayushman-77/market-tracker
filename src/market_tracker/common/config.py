import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    # ClickHouse
    clickhouse_host: str = field(default_factory=lambda: os.getenv("CLICKHOUSE_HOST", "localhost"))
    clickhouse_port: int = field(default_factory=lambda: int(os.getenv("CLICKHOUSE_PORT", "8123")))
    clickhouse_user: str = field(default_factory=lambda: os.getenv("CLICKHOUSE_USER", "default"))
    clickhouse_password: str = field(
        default_factory=lambda: os.getenv("CLICKHOUSE_PASSWORD", "clickhouse")
    )
    clickhouse_database: str = field(
        default_factory=lambda: os.getenv("CLICKHOUSE_DB", "market_tracker")
    )

    # Polymarket APIs
    clob_ws_url: str = field(
        default_factory=lambda: os.getenv(
            "CLOB_WS_URL", "wss://ws-subscriptions-clob.polymarket.com/ws/market"
        )
    )
    gamma_api_url: str = field(
        default_factory=lambda: os.getenv("GAMMA_API_URL", "https://gamma-api.polymarket.com")
    )
    data_api_url: str = field(
        default_factory=lambda: os.getenv("DATA_API_URL", "https://data-api.polymarket.com")
    )
    clob_rest_url: str = field(
        default_factory=lambda: os.getenv("CLOB_REST_URL", "https://clob.polymarket.com")
    )

    # Polygon RPC
    polygon_rpc_url: str = field(
        default_factory=lambda: os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
    )

    # Ingestion Batching & Queues
    batch_size: int = field(default_factory=lambda: int(os.getenv("INGEST_BATCH_SIZE", "10000")))
    flush_interval_ms: int = field(
        default_factory=lambda: int(os.getenv("INGEST_FLUSH_INTERVAL_MS", "250"))
    )
    queue_max_size: int = field(
        default_factory=lambda: int(os.getenv("INGEST_QUEUE_MAX_SIZE", "100000"))
    )

    # WebSocket Client
    ws_ping_interval: float = field(
        default_factory=lambda: float(os.getenv("WS_PING_INTERVAL", "10.0"))
    )
    ws_reconnect_base_delay: float = field(
        default_factory=lambda: float(os.getenv("WS_RECONNECT_BASE_DELAY", "0.5"))
    )
    ws_reconnect_max_delay: float = field(
        default_factory=lambda: float(os.getenv("WS_RECONNECT_MAX_DELAY", "30.0"))
    )


settings = Settings()
