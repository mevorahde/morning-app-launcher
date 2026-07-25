from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from morning_app_launcher.controller import ApplicationController
from morning_app_launcher.models import Application
from morning_app_launcher.operational_logging import (
    LOG_FILENAME,
    NullOperationalLogger,
    OperationalEvent,
    RotatingOperationalLogger,
    create_operational_logger,
)

from .fakes import FakeLauncher, FakeStore


def test_operational_log_contains_only_events_and_counts(tmp_path: Path) -> None:
    private_path = tmp_path / "private-application-name.exe"
    private_path.touch()
    log_directory = tmp_path / "logs"
    event_logger = create_operational_logger(log_directory)
    controller = ApplicationController(
        FakeStore([Application(private_path)]), FakeLauncher(), event_logger
    )

    controller.load()
    controller.rename(0, "Private renamed display value")
    controller.launch_ready()
    controller.close()

    contents = (log_directory / LOG_FILENAME).read_text(encoding="utf-8")
    assert "application_started" in contents
    assert "launch_completed" in contents
    assert "rename_completed" in contents
    assert "entries=1" in contents
    assert str(tmp_path) not in contents
    assert private_path.name not in contents
    assert "Private renamed display value" not in contents


def test_unknown_count_names_are_not_logged(tmp_path: Path) -> None:
    log_directory = tmp_path / "logs"
    event_logger = create_operational_logger(log_directory)

    event_logger.event(OperationalEvent.ADD_COMPLETED, added=1, private_path=99)
    event_logger.close()

    contents = (log_directory / LOG_FILENAME).read_text(encoding="utf-8")
    assert "added=1" in contents
    assert "private_path" not in contents


def test_logging_setup_failure_returns_nonfatal_null_logger(tmp_path: Path) -> None:
    blocked_directory = tmp_path / "not-a-directory"
    blocked_directory.write_text("occupied", encoding="utf-8")

    event_logger = create_operational_logger(blocked_directory)

    assert isinstance(event_logger, NullOperationalLogger)
    event_logger.event(OperationalEvent.STATUS_REFRESHED, ready=1)
    event_logger.close()


def test_emit_failure_is_nonfatal() -> None:
    class FailingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            del record
            raise OSError("simulated")

    event_logger = RotatingOperationalLogger(FailingHandler())

    event_logger.event(OperationalEvent.STATUS_REFRESHED, ready=1)
    event_logger.close()
    event_logger.close()


def test_rotation_creates_bounded_backup(tmp_path: Path) -> None:
    log_directory = tmp_path / "logs"
    log_directory.mkdir()
    handler = RotatingFileHandler(
        log_directory / LOG_FILENAME,
        maxBytes=80,
        backupCount=1,
        encoding="utf-8",
    )
    event_logger = RotatingOperationalLogger(handler)

    for _ in range(12):
        event_logger.event(OperationalEvent.STATUS_REFRESHED, entries=3, ready=2, missing=1)
    event_logger.close()

    assert (log_directory / LOG_FILENAME).is_file()
    assert (log_directory / f"{LOG_FILENAME}.1").is_file()
