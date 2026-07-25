"""Use cases shared by the GUI and isolated tests."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .errors import DuplicateApplication, InvalidApplicationPath, InvalidSelection
from .launcher import ApplicationLauncher
from .models import Application, deduplicate
from .operational_logging import (
    NullOperationalLogger,
    OperationalEvent,
    OperationalEventLogger,
)
from .storage import ApplicationStore


@dataclass(frozen=True, slots=True)
class ApplicationStatus:
    index: int
    name: str
    ready: bool


@dataclass(frozen=True, slots=True)
class AddSummary:
    added: int
    duplicates: int
    invalid: int


@dataclass(frozen=True, slots=True)
class LaunchSummary:
    requested: int
    succeeded: int
    missing: int
    failed: int


class ApplicationController:
    def __init__(
        self,
        store: ApplicationStore,
        launcher: ApplicationLauncher,
        event_logger: OperationalEventLogger | None = None,
    ) -> None:
        self._store = store
        self._launcher = launcher
        self._event_logger = event_logger or NullOperationalLogger()
        self._applications: list[Application] = []
        self._closed = False

    def load(self) -> tuple[Application, ...]:
        self._applications = deduplicate(self._store.load())
        self._log_status(OperationalEvent.APPLICATION_STARTED)
        return self.list_applications()

    def list_applications(self) -> tuple[Application, ...]:
        return tuple(self._applications)

    def list_statuses(self) -> tuple[ApplicationStatus, ...]:
        return tuple(
            ApplicationStatus(
                index=index,
                name=application.name,
                ready=self._is_launchable(application),
            )
            for index, application in enumerate(self._applications)
        )

    def refresh_status(self) -> tuple[ApplicationStatus, ...]:
        statuses = self.list_statuses()
        self._log_status(OperationalEvent.STATUS_REFRESHED, statuses)
        return statuses

    def add(self, path: Path) -> Application:
        summary = self.add_many([path])
        if summary.invalid:
            raise InvalidApplicationPath("The selected application is missing or invalid.")
        if summary.duplicates:
            raise DuplicateApplication("The selected application is already in the list.")
        return self._applications[-1]

    def add_many(self, paths: Iterable[Path]) -> AddSummary:
        updated = list(self._applications)
        identities = {application.identity for application in updated}
        added = duplicates = invalid = 0
        for path in paths:
            try:
                application = Application.from_text(str(path))
            except InvalidApplicationPath:
                invalid += 1
                continue
            if not self._is_launchable(application):
                invalid += 1
            elif application.identity in identities:
                duplicates += 1
            else:
                identities.add(application.identity)
                updated.append(application)
                added += 1
        if added:
            self._store.save(updated)
            self._applications = updated
        summary = AddSummary(added=added, duplicates=duplicates, invalid=invalid)
        self._event_logger.event(
            OperationalEvent.ADD_COMPLETED,
            added=added,
            duplicates=duplicates,
            invalid=invalid,
        )
        return summary

    def remove(self, index: int) -> Application:
        if index < 0 or index >= len(self._applications):
            raise InvalidSelection("Select an application to remove.")
        removed = self._applications[index]
        self.remove_many([index])
        return removed

    def remove_many(self, indices: Iterable[int]) -> int:
        selected = sorted(set(indices))
        if not selected or selected[0] < 0 or selected[-1] >= len(self._applications):
            raise InvalidSelection("Select one or more applications to remove.")
        selected_set = set(selected)
        updated = [
            application
            for position, application in enumerate(self._applications)
            if position not in selected_set
        ]
        self._store.save(updated)
        self._applications = updated
        self._event_logger.event(OperationalEvent.REMOVE_COMPLETED, removed=len(selected))
        return len(selected)

    def rename(self, index: int, name: str) -> Application:
        if index < 0 or index >= len(self._applications):
            raise InvalidSelection("Select one application to rename.")
        renamed = self._applications[index].renamed(name)
        updated = list(self._applications)
        updated[index] = renamed
        self._store.save(updated)
        self._applications = updated
        self._event_logger.event(OperationalEvent.RENAME_COMPLETED)
        return renamed

    def launch_one(self, index: int) -> LaunchSummary:
        return self.launch_indices([index])

    def launch_all(self) -> LaunchSummary:
        return self.launch_ready()

    def launch_indices(self, indices: Iterable[int]) -> LaunchSummary:
        selected = sorted(set(indices))
        if not selected or selected[0] < 0 or selected[-1] >= len(self._applications):
            raise InvalidSelection("Select one or more applications to open.")
        succeeded = missing = failed = 0
        for index in selected:
            application = self._applications[index]
            if not self._is_launchable(application):
                missing += 1
                continue
            try:
                self._launcher.launch(application)
            except Exception:
                failed += 1
            else:
                succeeded += 1
        summary = LaunchSummary(
            requested=len(selected),
            succeeded=succeeded,
            missing=missing,
            failed=failed,
        )
        self._event_logger.event(
            OperationalEvent.LAUNCH_COMPLETED,
            requested=summary.requested,
            succeeded=summary.succeeded,
            missing=summary.missing,
            failed=summary.failed,
        )
        return summary

    def launch_ready(self) -> LaunchSummary:
        if not self._applications:
            raise InvalidSelection("Add an application before opening the list.")
        return self.launch_indices(range(len(self._applications)))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._event_logger.event(OperationalEvent.APPLICATION_CLOSED)
        self._event_logger.close()

    @staticmethod
    def _is_launchable(application: Application) -> bool:
        path = application.path
        return path.is_absolute() and path.exists() and path.is_file()

    def _log_status(
        self,
        event: OperationalEvent,
        statuses: tuple[ApplicationStatus, ...] | None = None,
    ) -> None:
        current = self.list_statuses() if statuses is None else statuses
        ready = sum(status.ready for status in current)
        self._event_logger.event(
            event,
            entries=len(current),
            ready=ready,
            missing=len(current) - ready,
        )
