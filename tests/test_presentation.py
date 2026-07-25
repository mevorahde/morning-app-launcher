from __future__ import annotations

from pathlib import Path

from morning_app_launcher.controller import ApplicationController
from morning_app_launcher.gui.presentation import (
    KEY_BINDINGS,
    CloseCoordinator,
    Command,
    CommandRouter,
    WindowPresenter,
)
from morning_app_launcher.models import Application

from .fakes import FakeLauncher, FakeStore


def presenter_with(
    applications: list[Application], launcher: FakeLauncher | None = None
) -> tuple[WindowPresenter, ApplicationController, FakeLauncher]:
    fake_launcher = launcher or FakeLauncher()
    controller = ApplicationController(FakeStore(applications), fake_launcher)
    controller.load()
    return WindowPresenter(controller), controller, fake_launcher


def test_empty_state_and_initial_button_enablement() -> None:
    presenter, _controller, _launcher = presenter_with([])

    state = presenter.state()

    assert state.empty_message is not None
    assert not state.actions.remove_selected
    assert not state.actions.edit_name
    assert not state.actions.open_selected
    assert not state.actions.open_all


def test_ready_and_missing_rows_control_button_enablement(tmp_path: Path) -> None:
    ready = tmp_path / "Ready App.exe"
    ready.touch()
    missing = tmp_path / "Missing App.exe"
    presenter, _controller, _launcher = presenter_with(
        [Application(ready), Application(missing)]
    )

    initial = presenter.state()
    missing_selected = presenter.select([1])
    mixed_selected = presenter.select([0, 1])

    assert [(row.name, row.status) for row in initial.rows] == [
        ("Ready App", "Ready"),
        ("Missing App", "Missing"),
    ]
    assert initial.actions.open_all
    assert missing_selected.actions.remove_selected
    assert missing_selected.actions.edit_name
    assert not missing_selected.actions.open_selected
    assert mixed_selected.actions.open_selected
    assert not mixed_selected.actions.edit_name

    missing_only, _controller, _launcher = presenter_with([Application(missing)])
    assert not missing_only.state().actions.open_all


def test_add_reports_cancel_success_duplicates_and_invalid(tmp_path: Path) -> None:
    added = tmp_path / "added.exe"
    added.touch()
    presenter, _controller, _launcher = presenter_with([])

    assert "cancelled" in presenter.add([]).message.lower()
    assert "Added 1" in presenter.add([added]).message
    summary = presenter.add([added, tmp_path / "missing.exe"])
    assert "1 duplicate" in summary.message
    assert "1 invalid" in summary.message


def test_remove_confirmation_and_multi_remove(tmp_path: Path) -> None:
    applications = [Application(tmp_path / f"app-{index}.exe") for index in range(3)]
    presenter, controller, _launcher = presenter_with(applications)
    presenter.select([0, 2])

    cancelled = presenter.remove_selected(False)
    removed = presenter.remove_selected(True)

    assert "cancelled" in cancelled.message.lower()
    assert "Removed 2" in removed.message
    assert controller.list_applications() == (applications[1],)


def test_edit_name_cancel_validation_success_and_selection_preservation(tmp_path: Path) -> None:
    application = Application(tmp_path / "app.exe")
    presenter, controller, _launcher = presenter_with([application])
    presenter.select([0])

    cancelled = presenter.edit_name(None)
    invalid = presenter.edit_name(" \n ")
    renamed = presenter.edit_name("  Unicode ☀ name  ")

    assert "cancelled" in cancelled.message.lower()
    assert "line breaks" in invalid.message.lower() or "enter" in invalid.message.lower()
    assert renamed.rows[0].name == "Unicode ☀ name"
    assert renamed.selected == (0,)
    assert renamed.actions.edit_name
    assert controller.list_applications()[0].path == application.path


def test_partial_launch_message_contains_counts_not_private_paths(tmp_path: Path) -> None:
    ready = tmp_path / "private-ready-name.exe"
    ready.touch()
    missing = tmp_path / "private-missing-name.exe"

    class FailingLauncher(FakeLauncher):
        def launch(self, application: Application) -> None:
            super().launch(application)
            raise OSError("simulated")

    presenter, _controller, _launcher = presenter_with(
        [Application(ready), Application(missing)], FailingLauncher()
    )
    presenter.select_all()

    state = presenter.open_selected()

    assert "0 opened" in state.message
    assert "1 missing" in state.message
    assert "1 failed" in state.message
    assert str(tmp_path) not in state.message
    assert "private-ready-name" not in state.message


def test_refresh_updates_missing_status_and_message(tmp_path: Path) -> None:
    application_path = tmp_path / "app.exe"
    application_path.touch()
    presenter, _controller, _launcher = presenter_with([Application(application_path)])
    application_path.unlink()

    state = presenter.refresh()

    assert state.rows[0].status == "Missing"
    assert state.message == "Status refreshed: 0 ready, 1 missing."
    assert not state.actions.open_all


def test_keyboard_bindings_and_command_router_route_expected_commands() -> None:
    assert KEY_BINDINGS == {
        "<Return>": Command.OPEN_SELECTED,
        "<Delete>": Command.REMOVE_SELECTED,
        "<Control-o>": Command.ADD,
        "<Control-a>": Command.SELECT_ALL,
        "<F2>": Command.EDIT_NAME,
        "<F5>": Command.REFRESH,
        "<Escape>": Command.CLEAR_SELECTION,
    }
    routed: list[Command] = []
    router = CommandRouter(
        {command: lambda value=command: routed.append(value) for command in Command}
    )

    for command in Command:
        router.dispatch(command)

    assert routed == list(Command)


def test_close_coordinator_is_idempotent() -> None:
    calls: list[str] = []
    coordinator = CloseCoordinator(lambda: calls.append("closed"))

    coordinator.close()
    coordinator.close()

    assert calls == ["closed"]
