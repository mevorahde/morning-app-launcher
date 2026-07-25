"""Compact, responsive Tkinter view for Morning App Launcher."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from functools import partial
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from ..controller import ApplicationController
from .presentation import (
    KEY_BINDINGS,
    CloseCoordinator,
    Command,
    CommandRouter,
    WindowPresenter,
    WindowState,
)


class MainWindow:
    def __init__(self, root: tk.Tk, controller: ApplicationController) -> None:
        self._root = root
        self._controller = controller
        self._presenter = WindowPresenter(controller)
        self._message = tk.StringVar(value="Ready.")
        self._empty_message = tk.StringVar()
        self._buttons: dict[Command, ttk.Button] = {}
        self._tree = ttk.Treeview(root)
        self._close_coordinator = CloseCoordinator(self._close_once)
        self._router = CommandRouter(
            {
                Command.ADD: self._add,
                Command.EDIT_NAME: self._edit_name,
                Command.REMOVE_SELECTED: self._remove_selected,
                Command.OPEN_SELECTED: self._open_selected,
                Command.OPEN_ALL: self._open_all,
                Command.REFRESH: self._refresh_status,
                Command.SELECT_ALL: self._select_all,
                Command.CLEAR_SELECTION: self._clear_selection,
                Command.CLOSE: self.close,
            }
        )
        self._build()
        self._render(self._presenter.state())

    def _build(self) -> None:
        self._root.title("Morning App Launcher")
        self._root.geometry("680x430")
        self._root.minsize(560, 340)
        self._root.columnconfigure(0, weight=1)
        self._root.rowconfigure(0, weight=1)

        frame = ttk.Frame(self._root, padding=18)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(3, weight=1)

        ttk.Label(frame, text="Morning App Launcher", font=("TkDefaultFont", 16, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            frame,
            text="Keep a short list of applications and open the ones you need to start your day.",
            wraplength=620,
        ).grid(row=1, column=0, sticky="ew", pady=(2, 12))
        ttk.Label(frame, text="Applications", font=("TkDefaultFont", 10, "bold")).grid(
            row=2, column=0, sticky="w", pady=(0, 4)
        )

        list_frame = ttk.Frame(frame)
        list_frame.grid(row=3, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self._tree = ttk.Treeview(
            list_frame,
            columns=("name", "status"),
            show="headings",
            selectmode="extended",
            takefocus=True,
            height=8,
        )
        self._tree.heading("name", text="Application name")
        self._tree.heading("status", text="Status")
        self._tree.column("name", minwidth=220, width=460, stretch=True)
        self._tree.column("status", minwidth=80, width=100, stretch=False, anchor="center")
        self._tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self._tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._tree.configure(yscrollcommand=scrollbar.set)

        self._empty_label = ttk.Label(
            list_frame,
            textvariable=self._empty_message,
            anchor="center",
            justify="center",
            wraplength=440,
            padding=24,
        )

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=4, column=0, sticky="ew", pady=(12, 10))
        for column in range(6):
            button_frame.columnconfigure(column, weight=1)
        self._add_button(button_frame, Command.ADD, "Add applications", 0)
        self._add_button(button_frame, Command.EDIT_NAME, "Edit name", 1)
        self._add_button(button_frame, Command.REMOVE_SELECTED, "Remove selected", 2)
        self._add_button(button_frame, Command.OPEN_SELECTED, "Open selected", 3)
        self._add_button(button_frame, Command.OPEN_ALL, "Open all", 4)
        self._add_button(button_frame, Command.REFRESH, "Refresh status", 5)

        ttk.Separator(frame).grid(row=5, column=0, sticky="ew")
        ttk.Label(
            frame,
            textvariable=self._message,
            anchor="w",
            wraplength=620,
            takefocus=True,
        ).grid(row=6, column=0, sticky="ew", pady=(8, 0))

        self._tree.bind("<<TreeviewSelect>>", self._on_selection_changed)
        for sequence, command in KEY_BINDINGS.items():
            self._root.bind(sequence, self._keyboard_handler(command), add="+")
        self._root.protocol("WM_DELETE_WINDOW", self.close)

    def _add_button(
        self,
        parent: ttk.Frame,
        command: Command,
        label: str,
        column: int,
    ) -> None:
        button = ttk.Button(
            parent,
            text=label,
            command=partial(self._router.dispatch, command),
            takefocus=True,
        )
        button.grid(row=0, column=column, padx=3, sticky="ew")
        self._buttons[command] = button

    def _keyboard_handler(
        self, command: Command
    ) -> Callable[[tk.Event[tk.Misc]], object]:
        def handle(_event: tk.Event[tk.Misc]) -> str:
            self._router.dispatch(command)
            return "break"

        return handle

    def _selected_indices(self) -> tuple[int, ...]:
        return tuple(int(item) for item in self._tree.selection())

    def _on_selection_changed(self, _event: object) -> None:
        self._render(self._presenter.select(self._selected_indices()), rebuild_rows=False)

    def _add(self) -> None:
        selected = filedialog.askopenfilenames(
            parent=self._root,
            title="Select applications",
            filetypes=(("Applications", "*.exe"), ("All files", "*.*")),
        )
        self._render(self._presenter.add(Path(path) for path in selected))

    def _remove_selected(self) -> None:
        selected = self._selected_indices()
        self._presenter.select(selected)
        confirmed = bool(selected) and messagebox.askyesno(
            "Remove applications",
            f"Remove {len(selected)} selected application(s) from the list?",
            parent=self._root,
        )
        self._render(self._presenter.remove_selected(confirmed))

    def _edit_name(self) -> None:
        selected = self._selected_indices()
        state = self._presenter.select(selected)
        if len(selected) != 1:
            self._render(self._presenter.edit_name(None), rebuild_rows=False)
            return
        current_name = state.rows[selected[0]].name
        name = simpledialog.askstring(
            "Edit application name",
            "Application name:",
            initialvalue=current_name,
            parent=self._root,
        )
        self._render(self._presenter.edit_name(name))
        self._tree.focus(str(selected[0]))
        self._tree.focus_set()

    def _open_selected(self) -> None:
        self._presenter.select(self._selected_indices())
        self._render(self._presenter.open_selected(), rebuild_rows=False)

    def _open_all(self) -> None:
        self._render(self._presenter.open_all(), rebuild_rows=False)

    def _refresh_status(self) -> None:
        self._render(self._presenter.refresh())

    def _select_all(self) -> None:
        children = self._tree.get_children()
        if children:
            self._tree.selection_set(children)
        self._render(self._presenter.select_all(), rebuild_rows=False)

    def _clear_selection(self) -> None:
        self._tree.selection_remove(self._tree.selection())
        self._render(self._presenter.clear_selection(), rebuild_rows=False)

    def _render(self, state: WindowState, *, rebuild_rows: bool = True) -> None:
        if rebuild_rows:
            self._tree.delete(*self._tree.get_children())
            for row in state.rows:
                self._tree.insert("", "end", iid=str(row.index), values=(row.name, row.status))
            selected_items = tuple(str(index) for index in state.selected)
            if selected_items:
                self._tree.selection_set(selected_items)
                self._tree.focus(selected_items[0])
            if state.empty_message:
                self._empty_message.set(state.empty_message)
                self._tree.grid_remove()
                self._empty_label.grid(row=0, column=0, columnspan=2, sticky="nsew")
            else:
                self._empty_label.grid_remove()
                self._tree.grid()
        self._message.set(state.message)
        self._set_enabled(Command.EDIT_NAME, state.actions.edit_name)
        self._set_enabled(Command.REMOVE_SELECTED, state.actions.remove_selected)
        self._set_enabled(Command.OPEN_SELECTED, state.actions.open_selected)
        self._set_enabled(Command.OPEN_ALL, state.actions.open_all)

    def _set_enabled(self, command: Command, enabled: bool) -> None:
        self._buttons[command].configure(state="normal" if enabled else "disabled")

    def close(self) -> None:
        self._close_coordinator.close()

    def _close_once(self) -> None:
        self._controller.close()
        try:
            self._root.destroy()
        except tk.TclError:
            return
