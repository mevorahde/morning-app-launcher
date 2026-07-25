"""Display-independent state and command routing for the Tkinter GUI."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ..controller import AddSummary, ApplicationController, ApplicationStatus, LaunchSummary
from ..errors import ApplicationError


class Command(Enum):
    ADD = "add"
    EDIT_NAME = "edit_name"
    REMOVE_SELECTED = "remove_selected"
    OPEN_SELECTED = "open_selected"
    OPEN_ALL = "open_all"
    REFRESH = "refresh"
    SELECT_ALL = "select_all"
    CLEAR_SELECTION = "clear_selection"
    CLOSE = "close"


KEY_BINDINGS: Mapping[str, Command] = {
    "<Return>": Command.OPEN_SELECTED,
    "<Delete>": Command.REMOVE_SELECTED,
    "<Control-o>": Command.ADD,
    "<Control-a>": Command.SELECT_ALL,
    "<F2>": Command.EDIT_NAME,
    "<F5>": Command.REFRESH,
    "<Escape>": Command.CLEAR_SELECTION,
}


@dataclass(frozen=True, slots=True)
class ApplicationRow:
    index: int
    name: str
    status: str
    ready: bool


@dataclass(frozen=True, slots=True)
class ActionAvailability:
    edit_name: bool
    remove_selected: bool
    open_selected: bool
    open_all: bool


@dataclass(frozen=True, slots=True)
class WindowState:
    rows: tuple[ApplicationRow, ...]
    selected: tuple[int, ...]
    actions: ActionAvailability
    empty_message: str | None
    message: str


class WindowPresenter:
    def __init__(self, controller: ApplicationController) -> None:
        self._controller = controller
        self._selected: tuple[int, ...] = ()
        self._message = "Ready."

    def state(self) -> WindowState:
        statuses = self._controller.list_statuses()
        valid_indices = {status.index for status in statuses}
        self._selected = tuple(index for index in self._selected if index in valid_indices)
        return self._state_from_statuses(statuses)

    def select(self, indices: Iterable[int]) -> WindowState:
        valid_indices = {status.index for status in self._controller.list_statuses()}
        self._selected = tuple(sorted(set(indices) & valid_indices))
        return self.state()

    def add(self, paths: Iterable[Path]) -> WindowState:
        selected_paths = tuple(paths)
        if not selected_paths:
            self._message = "Add cancelled. No applications were changed."
            return self.state()
        try:
            summary = self._controller.add_many(selected_paths)
        except ApplicationError as exc:
            self._message = str(exc)
        else:
            self._message = self._format_add_summary(summary)
        return self.state()

    def remove_selected(self, confirmed: bool) -> WindowState:
        if not self._selected:
            self._message = "Select one or more applications to remove."
        elif not confirmed:
            self._message = "Removal cancelled."
        else:
            try:
                removed = self._controller.remove_many(self._selected)
            except ApplicationError as exc:
                self._message = str(exc)
            else:
                self._selected = ()
                self._message = f"Removed {removed} application(s)."
        return self.state()

    def edit_name(self, name: str | None) -> WindowState:
        if len(self._selected) != 1:
            self._message = "Select one application to rename."
        elif name is None:
            self._message = "Rename cancelled. No applications were changed."
        else:
            try:
                self._controller.rename(self._selected[0], name)
            except ApplicationError as exc:
                self._message = str(exc)
            else:
                self._message = "Application name updated."
        return self.state()

    def open_selected(self) -> WindowState:
        if not self._selected:
            self._message = "Select one or more ready applications to open."
            return self.state()
        try:
            summary = self._controller.launch_indices(self._selected)
        except ApplicationError as exc:
            self._message = str(exc)
        else:
            self._message = self._format_launch_summary(summary)
        return self.state()

    def open_all(self) -> WindowState:
        try:
            summary = self._controller.launch_ready()
        except ApplicationError as exc:
            self._message = str(exc)
        else:
            self._message = self._format_launch_summary(summary)
        return self.state()

    def refresh(self) -> WindowState:
        statuses = self._controller.refresh_status()
        ready = sum(status.ready for status in statuses)
        missing = len(statuses) - ready
        self._message = f"Status refreshed: {ready} ready, {missing} missing."
        return self._state_from_statuses(statuses)

    def select_all(self) -> WindowState:
        self._selected = tuple(status.index for status in self._controller.list_statuses())
        return self.state()

    def clear_selection(self) -> WindowState:
        self._selected = ()
        self._message = "Selection cleared."
        return self.state()

    def _state_from_statuses(self, statuses: tuple[ApplicationStatus, ...]) -> WindowState:
        rows = tuple(
            ApplicationRow(
                index=status.index,
                name=status.name,
                status="Ready" if status.ready else "Missing",
                ready=status.ready,
            )
            for status in statuses
        )
        selected_set = set(self._selected)
        has_ready_selection = any(row.ready and row.index in selected_set for row in rows)
        actions = ActionAvailability(
            edit_name=len(self._selected) == 1,
            remove_selected=bool(self._selected),
            open_selected=has_ready_selection,
            open_all=any(row.ready for row in rows),
        )
        empty_message = (
            "No applications yet. Add one or more applications to build your morning list."
            if not rows
            else None
        )
        return WindowState(rows, self._selected, actions, empty_message, self._message)

    @staticmethod
    def _format_add_summary(summary: AddSummary) -> str:
        if summary.added and not summary.duplicates and not summary.invalid:
            return f"Added {summary.added} application(s)."
        return (
            f"Add complete: {summary.added} added, "
            f"{summary.duplicates} duplicate(s), {summary.invalid} invalid."
        )

    @staticmethod
    def _format_launch_summary(summary: LaunchSummary) -> str:
        if summary.succeeded == summary.requested:
            return f"Opened {summary.succeeded} application(s)."
        return (
            f"Open complete: {summary.succeeded} opened, "
            f"{summary.missing} missing, {summary.failed} failed."
        )


class CommandRouter:
    def __init__(self, handlers: Mapping[Command, Callable[[], None]]) -> None:
        self._handlers = dict(handlers)

    def dispatch(self, command: Command) -> None:
        handler = self._handlers.get(command)
        if handler is not None:
            handler()


class CloseCoordinator:
    def __init__(self, close_once: Callable[[], None]) -> None:
        self._close_once = close_once
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._close_once()
