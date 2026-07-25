"""Privacy-safe, fail-open operational event logging."""

from __future__ import annotations

import logging
from contextlib import suppress
from enum import Enum
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Protocol

LOG_FILENAME = "operations.log"
MAX_LOG_BYTES = 256 * 1024
LOG_BACKUP_COUNT = 3
SAFE_COUNT_NAMES = frozenset(
    {
        "added",
        "duplicates",
        "entries",
        "failed",
        "invalid",
        "missing",
        "ready",
        "removed",
        "requested",
        "succeeded",
    }
)


class OperationalEvent(Enum):
    APPLICATION_STARTED = "application_started"
    APPLICATION_CLOSED = "application_closed"
    STATUS_REFRESHED = "status_refreshed"
    ADD_COMPLETED = "add_completed"
    RENAME_COMPLETED = "rename_completed"
    REMOVE_COMPLETED = "remove_completed"
    LAUNCH_COMPLETED = "launch_completed"


class OperationalEventLogger(Protocol):
    def event(self, event: OperationalEvent, **counts: int) -> None:
        """Record a predefined event and non-sensitive integer counts."""

    def close(self) -> None:
        """Release logging resources without raising."""


class NullOperationalLogger:
    def event(self, event: OperationalEvent, **counts: int) -> None:
        del event, counts

    def close(self) -> None:
        return


class _SilentRotatingFileHandler(RotatingFileHandler):
    def handleError(self, record: logging.LogRecord) -> None:
        del record


class RotatingOperationalLogger:
    """Write bounded operational events without accepting path values."""

    def __init__(self, handler: logging.Handler) -> None:
        self._logger = logging.Logger("morning_app_launcher.operations", logging.INFO)
        self._logger.propagate = False
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        self._logger.addHandler(handler)
        self._closed = False

    def event(self, event: OperationalEvent, **counts: int) -> None:
        if self._closed:
            return
        try:
            safe_counts = " ".join(
                f"{name}={int(value)}"
                for name, value in sorted(counts.items())
                if name in SAFE_COUNT_NAMES
            )
            message = event.value if not safe_counts else f"{event.value} {safe_counts}"
            self._logger.info(message)
        except Exception:
            return

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for handler in tuple(self._logger.handlers):
            with suppress(Exception):
                handler.close()
            self._logger.removeHandler(handler)


def create_operational_logger(log_directory: Path) -> OperationalEventLogger:
    """Create a rotating logger, falling back to a no-op logger on any failure."""

    try:
        log_directory.mkdir(parents=True, exist_ok=True)
        handler = _SilentRotatingFileHandler(
            log_directory / LOG_FILENAME,
            maxBytes=MAX_LOG_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
            delay=True,
        )
        return RotatingOperationalLogger(handler)
    except Exception:
        return NullOperationalLogger()
