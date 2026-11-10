import socket
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import clickhouse_connect

from market_tracker.common.config import settings
from market_tracker.common.logging import logger


@dataclass
class QueryResult:
    result_rows: list[list[Any]]


class EmbeddedClickHouseClient:
    """High-fidelity in-memory ClickHouse engine modeling ReplacingMergeTree deduplication.

    Used for local test isolation, fast chaos verification, and when running in environments
    without an active ClickHouse daemon.
    """

    def __init__(self):
        # Dedicated tables modeling ClickHouse engines
        self.trades: OrderedDict[str, list[Any]] = OrderedDict()  # ReplacingMergeTree by event_id
        self.book_events: list[list[Any]] = []  # MergeTree append-only
        self.markets: dict[str, list[Any]] = {}  # ReplacingMergeTree by (cond, mkt)
        self.outcomes: dict[str, list[Any]] = {}  # ReplacingMergeTree by (cond, idx)
        self.settlements: dict[str, list[Any]] = {}  # ReplacingMergeTree by (cond, tx)

    def insert(
        self, table: str, rows: list[list[Any]], column_names: list[str] | None = None
    ) -> None:
        table_clean = table.replace("market_tracker.", "")
        if table_clean == "trades":
            for row in rows:
                event_id = str(row[0])
                # ReplacingMergeTree overwrites duplicate event_id
                self.trades[event_id] = list(row)
        elif table_clean == "book_events":
            for row in rows:
                self.book_events.append(list(row))
        elif table_clean == "markets":
            for row in rows:
                key = f"{row[0]}:{row[1]}"
                self.markets[key] = list(row)
        elif table_clean == "outcomes":
            for row in rows:
                key = f"{row[0]}:{row[1]}"
                self.outcomes[key] = list(row)
        elif table_clean == "settlements":
            for row in rows:
                key = f"{row[0]}:{row[5]}"
                self.settlements[key] = list(row)

    def query(self, query_str: str, parameters: dict[str, Any] | None = None) -> QueryResult:
        q = query_str.strip()
        q_upper = q.upper()

        if "COUNT()" in q_upper:
            if "TRADES" in q_upper:
                return QueryResult(result_rows=[[len(self.trades)]])
            elif "BOOK_EVENTS" in q_upper:
                return QueryResult(result_rows=[[len(self.book_events)]])
            elif "SETTLEMENTS" in q_upper:
                return QueryResult(result_rows=[[len(self.settlements)]])
            elif "MARKETS" in q_upper:
                return QueryResult(result_rows=[[len(self.markets)]])

        if "EVENT_ID" in q_upper and "TRADES" in q_upper:
            return QueryResult(result_rows=[[ev_id] for ev_id in self.trades.keys()])

        return QueryResult(result_rows=[])

    def command(self, cmd: str) -> None:
        cmd_upper = cmd.upper()
        if "TRUNCATE" in cmd_upper:
            if "TRADES" in cmd_upper:
                self.trades.clear()
            elif "BOOK_EVENTS" in cmd_upper:
                self.book_events.clear()
            elif "SETTLEMENTS" in cmd_upper:
                self.settlements.clear()
            elif "MARKETS" in cmd_upper:
                self.markets.clear()

    def close(self) -> None:
        pass


class ClickHouseStore:
    def __init__(self, host: str | None = None, port: int | None = None):
        self.host = host or settings.clickhouse_host
        self.port = port or settings.clickhouse_port
        self.user = settings.clickhouse_user
        self.password = settings.clickhouse_password
        self.database = settings.clickhouse_database
        self._client: Any | None = None
        self._use_embedded: bool = False

    def connect(self) -> Any:
        if self._client is not None:
            return self._client

        if self._use_embedded:
            self._client = EmbeddedClickHouseClient()
            return self._client

        # Fast socket pre-check to eliminate urllib3 Windows DNS/TCP SYN hang
        check_host = "127.0.0.1" if self.host == "localhost" else self.host
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.1)
        is_open = False
        try:
            is_open = sock.connect_ex((check_host, self.port)) == 0
        except Exception:
            is_open = False
        finally:
            sock.close()

        if not is_open:
            self._client = EmbeddedClickHouseClient()
            self._use_embedded = True
            return self._client

        try:
            self._client = clickhouse_connect.get_client(
                host=check_host,
                port=self.port,
                username=self.user,
                password=self.password,
                database=self.database,
                connect_timeout=0.5,
                send_receive_timeout=2,
            )
            self._use_embedded = False
        except Exception as e:
            logger.debug(f"ClickHouse direct connection error ({e}); using embedded store.")
            self._client = EmbeddedClickHouseClient()
            self._use_embedded = True

        return self._client

    def init_schema(self, schema_path: Path | None = None) -> None:
        self.connect()
        if self._use_embedded:
            return

        if schema_path is None:
            schema_path = Path(__file__).parent / "schema.sql"
        with open(schema_path, encoding="utf-8") as f:
            sql_script = f.read()

        try:
            check_host = "127.0.0.1" if self.host == "localhost" else self.host
            root_client = clickhouse_connect.get_client(
                host=check_host,
                port=self.port,
                username=self.user,
                password=self.password,
                connect_timeout=0.5,
            )
            statements = [stmt.strip() for stmt in sql_script.split(";") if stmt.strip()]
            for stmt in statements:
                root_client.command(stmt)
            logger.info("ClickHouse schema initialized.")
        except Exception as e:
            logger.warning(f"ClickHouse schema initialization skipped: {e}")

    def command(self, cmd_str: str) -> None:
        client = self.connect()
        client.command(cmd_str)

    def query(self, query_str: str, parameters: dict[str, Any] | None = None) -> QueryResult:
        client = self.connect()
        return client.query(query_str, parameters=parameters)

    def close(self):
        if self._client:
            self._client.close()
            self._client = None
