import time
from collections.abc import Callable
from dataclasses import dataclass

from market_tracker.common.logging import logger


@dataclass
class GapWindow:
    start_time: float  # Unix epoch seconds
    end_time: float  # Unix epoch seconds
    asset_id: str | None = None
    reason: str = "disconnect"


class GapDetector:
    """Detects gaps across WebSocket streams and coordinates REST backfill windows."""

    def __init__(
        self,
        max_inactivity_seconds: float = 15.0,
        on_gap_detected: Callable[[GapWindow], None] | None = None,
    ):
        self.max_inactivity = max_inactivity_seconds
        self.on_gap_detected = on_gap_detected

        self.last_seen_timestamp: float = time.time()
        self.disconnect_time: float | None = None
        self.gap_count: int = 0
        self.active_gaps: list[GapWindow] = []

    def on_message_received(self, timestamp: float | None = None) -> None:
        now = timestamp or time.time()
        # If there was a large gap in streaming timestamps
        if now - self.last_seen_timestamp > self.max_inactivity:
            gap = GapWindow(
                start_time=self.last_seen_timestamp,
                end_time=now,
                reason="timestamp_discontinuity",
            )
            self._trigger_gap(gap)
        self.last_seen_timestamp = now

    def on_disconnect(self) -> None:
        self.disconnect_time = time.time()
        logger.warning(f"Connection dropped at {self.disconnect_time}. Monitoring gap window.")

    def on_reconnect(self) -> GapWindow | None:
        if self.disconnect_time is None:
            return None

        reconnect_time = time.time()
        # Include small 1-second margin buffer on both sides
        gap = GapWindow(
            start_time=max(0.0, self.disconnect_time - 1.0),
            end_time=reconnect_time + 1.0,
            reason="socket_disconnect",
        )
        self.disconnect_time = None
        self._trigger_gap(gap)
        return gap

    def _trigger_gap(self, gap: GapWindow) -> None:
        self.gap_count += 1
        self.active_gaps.append(gap)
        logger.info(
            f"Gap #{self.gap_count} detected: {gap.reason} "
            f"from {gap.start_time:.2f} to {gap.end_time:.2f} (duration: {gap.end_time - gap.start_time:.2f}s)"
        )
        if self.on_gap_detected:
            self.on_gap_detected(gap)
