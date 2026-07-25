from __future__ import annotations

from pathlib import Path

import pytest

from morning_app_launcher.controller import ApplicationController
from morning_app_launcher.errors import (
    ConfigurationWriteError,
    DuplicateApplication,
    InvalidApplicationPath,
    InvalidDisplayName,
    InvalidSelection,
)
from morning_app_launcher.models import Application
from morning_app_launcher.operational_logging import OperationalEvent

from .fakes import FakeEventLogger, FakeLauncher, FakeStore


def make_controller() -> tuple[ApplicationController, FakeStore, FakeLauncher]:
    store = FakeStore()
    launcher = FakeLauncher()
    return ApplicationController(store, launcher), store, launcher


def test_load_list_add_and_remove(tmp_path: Path) -> None:
    controller, store, _launcher = make_controller()
    application_path = tmp_path / "app.exe"
    application_path.touch()

    assert controller.load() == ()
    added = controller.add(application_path)

    assert added == Application(application_path)
    assert controller.list_applications() == (added,)
    assert store.applications == [added]
    assert controller.remove(0) == added
    assert controller.list_applications() == ()


def test_add_rejects_duplicate(tmp_path: Path) -> None:
    controller, _store, _launcher = make_controller()
    application_path = tmp_path / "app.exe"
    application_path.touch()
    controller.add(application_path)

    with pytest.raises(DuplicateApplication):
        controller.add(application_path)


@pytest.mark.parametrize("kind", ["missing", "directory", "relative"])
def test_add_rejects_missing_or_invalid_paths(tmp_path: Path, kind: str) -> None:
    controller, _store, _launcher = make_controller()
    if kind == "missing":
        path = tmp_path / "missing.exe"
    elif kind == "directory":
        path = tmp_path
    else:
        path = Path("relative.exe")

    with pytest.raises(InvalidApplicationPath):
        controller.add(path)


def test_remove_rejects_invalid_selection() -> None:
    controller, _store, _launcher = make_controller()

    with pytest.raises(InvalidSelection):
        controller.remove(0)


def test_launch_one_and_all_use_only_injected_launcher(tmp_path: Path) -> None:
    controller, store, launcher = make_controller()
    paths = [tmp_path / "one.exe", tmp_path / "two.exe"]
    for path in paths:
        path.touch()
    applications = [Application(path) for path in paths]
    store.applications = applications
    controller.load()

    controller.launch_one(1)
    controller.launch_all()

    assert launcher.launched == [applications[1], *applications]


def test_launch_empty_list_is_safe() -> None:
    controller, _store, launcher = make_controller()

    with pytest.raises(InvalidSelection):
        controller.launch_all()
    assert launcher.launched == []


def test_statuses_use_friendly_names_and_ready_missing_states(tmp_path: Path) -> None:
    ready_path = tmp_path / "Ready Tool.exe"
    ready_path.touch()
    missing_path = tmp_path / "Missing Tool.exe"
    store = FakeStore([Application(ready_path), Application(missing_path)])
    controller = ApplicationController(store, FakeLauncher())
    controller.load()

    statuses = controller.list_statuses()

    assert [(status.name, status.ready) for status in statuses] == [
        ("Ready Tool", True),
        ("Missing Tool", False),
    ]


def test_add_many_handles_success_duplicates_and_invalid_paths(tmp_path: Path) -> None:
    existing = tmp_path / "existing.exe"
    existing.touch()
    added = tmp_path / "added.exe"
    added.touch()
    store = FakeStore([Application(existing)])
    controller = ApplicationController(store, FakeLauncher())
    controller.load()

    summary = controller.add_many(
        [existing, added, added, tmp_path / "missing.exe", Path("relative.exe")]
    )

    assert (summary.added, summary.duplicates, summary.invalid) == (1, 2, 2)
    assert controller.list_applications() == (Application(existing), Application(added))


def test_remove_many_removes_all_selected_in_one_save(tmp_path: Path) -> None:
    applications = [Application(tmp_path / f"app-{index}.exe") for index in range(4)]
    store = FakeStore(applications)
    controller = ApplicationController(store, FakeLauncher())
    controller.load()

    assert controller.remove_many([3, 1, 1]) == 2
    assert controller.list_applications() == (applications[0], applications[2])
    assert len(store.save_calls) == 1


def test_rename_persists_name_without_changing_path_order_or_status(tmp_path: Path) -> None:
    first = tmp_path / "first.exe"
    first.touch()
    second = tmp_path / "second.exe"
    applications = [Application(first), Application(second)]
    store = FakeStore(applications)
    controller = ApplicationController(store, FakeLauncher())
    controller.load()

    renamed = controller.rename(0, "  Daily 工具  ")

    assert renamed == Application(first, "Daily 工具")
    assert renamed.path == first
    assert controller.list_applications() == (renamed, applications[1])
    assert store.applications == [renamed, applications[1]]
    assert [(status.name, status.ready) for status in controller.list_statuses()] == [
        ("Daily 工具", True),
        ("second", False),
    ]


def test_duplicate_display_names_are_allowed(tmp_path: Path) -> None:
    applications = [
        Application(tmp_path / "one.exe", "Same"),
        Application(tmp_path / "two.exe", "Different"),
    ]
    controller = ApplicationController(FakeStore(applications), FakeLauncher())
    controller.load()

    controller.rename(1, "Same")

    assert [application.name for application in controller.list_applications()] == ["Same", "Same"]


@pytest.mark.parametrize("name", ["", "   ", "line\nbreak", "control\x07name", "x" * 121])
def test_rename_rejects_invalid_names_without_saving(tmp_path: Path, name: str) -> None:
    application = Application(tmp_path / "app.exe")
    store = FakeStore([application])
    controller = ApplicationController(store, FakeLauncher())
    controller.load()

    with pytest.raises(InvalidDisplayName):
        controller.rename(0, name)

    assert controller.list_applications() == (application,)
    assert store.save_calls == []


def test_rename_storage_failure_keeps_controller_state_and_uses_safe_error(
    tmp_path: Path,
) -> None:
    private_path = tmp_path / "private-tool.exe"
    original = Application(private_path)

    class FailingStore(FakeStore):
        def save(self, applications: list[Application]) -> None:
            del applications
            raise ConfigurationWriteError("The configuration could not be saved.")

    controller = ApplicationController(FailingStore([original]), FakeLauncher())
    controller.load()

    with pytest.raises(ConfigurationWriteError) as error:
        controller.rename(0, "New private name")

    assert controller.list_applications() == (original,)
    assert str(tmp_path) not in str(error.value)
    assert private_path.name not in str(error.value)


def test_partial_launch_continues_after_missing_and_failure(tmp_path: Path) -> None:
    ready = tmp_path / "ready.exe"
    ready.touch()
    failed = tmp_path / "failed.exe"
    failed.touch()
    missing = tmp_path / "missing.exe"

    class PartialLauncher:
        def __init__(self) -> None:
            self.calls: list[Application] = []

        def launch(self, application: Application) -> None:
            self.calls.append(application)
            if application.path == failed:
                raise OSError("simulated")

    launcher = PartialLauncher()
    store = FakeStore([Application(failed), Application(missing), Application(ready)])
    event_logger = FakeEventLogger()
    controller = ApplicationController(store, launcher, event_logger)
    controller.load()

    summary = controller.launch_ready()

    assert (summary.requested, summary.succeeded, summary.missing, summary.failed) == (3, 1, 1, 1)
    assert launcher.calls == [Application(failed), Application(ready)]


def test_repeated_controller_close_closes_logger_once() -> None:
    event_logger = FakeEventLogger()
    controller = ApplicationController(FakeStore(), FakeLauncher(), event_logger)

    controller.close()
    controller.close()

    assert event_logger.close_calls == 1
    assert [event for event, _counts in event_logger.events].count(
        OperationalEvent.APPLICATION_CLOSED
    ) == 1
