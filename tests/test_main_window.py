from __future__ import annotations

from pathlib import Path
from typing import Any

from morning_app_launcher.controller import ApplicationController
from morning_app_launcher.gui import main_window
from morning_app_launcher.gui.main_window import MainWindow
from morning_app_launcher.gui.presentation import WindowPresenter, WindowState
from morning_app_launcher.models import Application

from .fakes import FakeLauncher, FakeStore


class FakeTree:
    def __init__(self) -> None:
        self.focused = ""
        self.focus_set_calls = 0

    def selection(self) -> tuple[str, ...]:
        return ("0",)

    def focus(self, item: str) -> None:
        self.focused = item

    def focus_set(self) -> None:
        self.focus_set_calls += 1


def test_edit_dialog_is_parent_owned_prefilled_and_restores_tree_focus(
    tmp_path: Path, monkeypatch: Any
) -> None:
    application = Application(tmp_path / "private-tool.exe", "Current name")
    store = FakeStore([application])
    controller = ApplicationController(store, FakeLauncher())
    controller.load()
    presenter = WindowPresenter(controller)
    root = object()
    tree = FakeTree()
    renders: list[WindowState] = []
    dialog_calls: list[dict[str, object]] = []

    def askstring(_title: str, _prompt: str, **options: object) -> str:
        dialog_calls.append(options)
        return "Updated name"

    window = object.__new__(MainWindow)
    window._root = root
    window._presenter = presenter
    window._tree = tree
    window._render = lambda state, **_options: renders.append(state)
    monkeypatch.setattr(main_window.simpledialog, "askstring", askstring)

    window._edit_name()

    assert dialog_calls == [{"initialvalue": "Current name", "parent": root}]
    assert controller.list_applications() == (
        Application(application.path, "Updated name"),
    )
    assert renders[-1].selected == (0,)
    assert tree.focused == "0"
    assert tree.focus_set_calls == 1
