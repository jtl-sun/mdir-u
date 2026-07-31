from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Sequence

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.coordinate import Coordinate
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Select, Static

from ..shortcuts import MAX_SHORTCUTS, SHORTCUT_KINDS, ShortcutDefinition


KIND_CHOICES = tuple((kind.title(), kind) for kind in sorted(SHORTCUT_KINDS))
PANE_CHOICES = (
    ("Active pane", "active"),
    ("Left pane", "left"),
    ("Right pane", "right"),
)


class ShortcutManagerScreen(
    ModalScreen[Optional[list[ShortcutDefinition]]]
):
    """Edit the top shortcut bar without exposing raw JSON to most users."""

    BINDINGS = [
        Binding(
            "escape",
            "cancel_manager",
            "Close without saving",
            show=False,
            priority=True,
        ),
    ]

    CSS = """
    ShortcutManagerScreen {
        align: center middle;
        background: #00000073;
    }

    #shortcut_manager_dialog {
        width: 92%;
        height: 88%;
        min-width: 76;
        min-height: 30;
        max-width: 150;
        max-height: 48;
        border: solid $primary;
        background: $surface;
        padding: 0 1;
    }

    #shortcut_manager_header {
        height: 1;
        min-height: 1;
        max-height: 1;
    }

    #shortcut_manager_title {
        width: 1fr;
        color: $accent;
        text-style: bold;
    }

    #shortcut_manager_close {
        width: 3;
        min-width: 3;
        height: 1;
        min-height: 1;
        max-height: 1;
        padding: 0;
        border: none;
        background: $error-darken-1;
        color: $text-error;
        text-style: bold;
        content-align: center middle;
    }

    #shortcut_manager_table {
        height: 1fr;
        min-height: 8;
        margin-top: 1;
        background: $background;
    }

    .shortcut_editor_row {
        height: 3;
        min-height: 3;
    }

    .shortcut_editor_label {
        width: 12;
        height: 3;
        content-align: left middle;
    }

    #shortcut_name,
    #shortcut_target,
    #shortcut_args {
        height: 3;
    }

    #shortcut_name,
    #shortcut_target {
        width: 1fr;
    }

    #shortcut_type {
        width: 24;
        margin-right: 2;
    }

    #shortcut_pane {
        width: 24;
    }

    #shortcut_args {
        width: 1fr;
    }

    #shortcut_row_actions,
    #shortcut_manager_actions {
        height: 3;
    }

    #shortcut_row_actions Button,
    #shortcut_manager_actions Button {
        height: 3;
        min-width: 10;
        width: auto;
        margin-right: 1;
    }

    #shortcut_manager_actions {
        align-horizontal: right;
    }

    #shortcut_manager_status {
        height: 1;
        color: $text-muted;
        text-wrap: nowrap;
        overflow-x: auto;
    }
    """

    def __init__(
        self,
        shortcuts: Sequence[ShortcutDefinition],
        current_path: Path,
    ) -> None:
        super().__init__()
        self.current_path = current_path
        self._drafts = [
            {
                "label": shortcut.label,
                "kind": shortcut.kind,
                "target": shortcut.target,
                "pane": shortcut.pane,
                "args": json.dumps(list(shortcut.args), ensure_ascii=False),
            }
            for shortcut in shortcuts[:MAX_SHORTCUTS]
        ]
        self._editing_index: int | None = None
        self._syncing_editor = False

    def compose(self) -> ComposeResult:
        with Vertical(id="shortcut_manager_dialog"):
            with Horizontal(id="shortcut_manager_header"):
                yield Label("Link Manager", id="shortcut_manager_title")
                yield Button("X", id="shortcut_manager_close")

            table = DataTable(
                id="shortcut_manager_table",
                cursor_type="row",
                zebra_stripes=True,
            )
            table.add_columns("Name", "Type", "URL / Path / Action", "Pane")
            yield table

            with Horizontal(classes="shortcut_editor_row"):
                yield Label("Name", classes="shortcut_editor_label")
                yield Input(id="shortcut_name", placeholder="Button name")

            with Horizontal(classes="shortcut_editor_row"):
                yield Label("Type / Pane", classes="shortcut_editor_label")
                yield Select(
                    KIND_CHOICES,
                    value="folder",
                    allow_blank=False,
                    id="shortcut_type",
                )
                yield Select(
                    PANE_CHOICES,
                    value="active",
                    allow_blank=False,
                    id="shortcut_pane",
                )

            with Horizontal(classes="shortcut_editor_row"):
                yield Label("Target", classes="shortcut_editor_label")
                yield Input(
                    id="shortcut_target",
                    placeholder="File, folder, program, URL, command, or action",
                )

            with Horizontal(classes="shortcut_editor_row"):
                yield Label("Arguments", classes="shortcut_editor_label")
                yield Input(
                    id="shortcut_args",
                    value="[]",
                    placeholder='Program arguments as JSON, for example ["-x"]',
                )

            with Horizontal(id="shortcut_row_actions"):
                yield Button("Add", id="shortcut_add", variant="primary")
                yield Button("Remove", id="shortcut_remove")
                yield Button("Move Up", id="shortcut_up")
                yield Button("Move Down", id="shortcut_down")
                yield Button("Browse File", id="shortcut_browse_file")
                yield Button("Browse Folder", id="shortcut_browse_folder")

            yield Static(
                "Select a row, edit its fields, then Save. Esc/X cancels all changes.",
                id="shortcut_manager_status",
            )

            with Horizontal(id="shortcut_manager_actions"):
                yield Button("Save", id="shortcut_save", variant="success")
                yield Button("Cancel", id="shortcut_cancel")

    @property
    def table(self) -> DataTable:
        return self.query_one("#shortcut_manager_table", DataTable)

    def on_mount(self) -> None:
        self._render_rows(0 if self._drafts else None)
        if not self._drafts:
            self._set_editor_enabled(False)
            self.query_one("#shortcut_add", Button).focus()

    def _set_editor_enabled(self, enabled: bool) -> None:
        for selector in (
            "#shortcut_name",
            "#shortcut_type",
            "#shortcut_pane",
            "#shortcut_target",
            "#shortcut_args",
            "#shortcut_remove",
            "#shortcut_up",
            "#shortcut_down",
            "#shortcut_browse_file",
            "#shortcut_browse_folder",
        ):
            self.query_one(selector).disabled = not enabled

    def _render_rows(self, selected_index: int | None) -> None:
        self._syncing_editor = True
        try:
            self.table.clear(columns=False)
            for draft in self._drafts:
                self.table.add_row(
                    draft["label"],
                    draft["kind"].title(),
                    draft["target"],
                    draft["pane"].title(),
                )
            if selected_index is not None and self._drafts:
                selected_index = max(0, min(len(self._drafts) - 1, selected_index))
                self.table.move_cursor(row=selected_index, column=0)
                self._load_editor(selected_index)
        finally:
            self._syncing_editor = False

    def _load_editor(self, index: int) -> None:
        if not 0 <= index < len(self._drafts):
            return
        draft = self._drafts[index]
        self._editing_index = index
        self._set_editor_enabled(True)
        self.query_one("#shortcut_name", Input).value = draft["label"]
        self.query_one("#shortcut_type", Select).value = draft["kind"]
        self.query_one("#shortcut_pane", Select).value = draft["pane"]
        self.query_one("#shortcut_target", Input).value = draft["target"]
        self.query_one("#shortcut_args", Input).value = draft["args"]

    def _sync_draft_from_editor(self) -> None:
        index = self._editing_index
        if self._syncing_editor or index is None or index >= len(self._drafts):
            return
        draft = self._drafts[index]
        draft["label"] = self.query_one("#shortcut_name", Input).value
        draft["kind"] = str(self.query_one("#shortcut_type", Select).value)
        draft["pane"] = str(self.query_one("#shortcut_pane", Select).value)
        draft["target"] = self.query_one("#shortcut_target", Input).value
        draft["args"] = self.query_one("#shortcut_args", Input).value

        if index < self.table.row_count:
            values = (
                draft["label"],
                draft["kind"].title(),
                draft["target"],
                draft["pane"].title(),
            )
            for column, value in enumerate(values):
                self.table.update_cell_at(
                    Coordinate(index, column),
                    value,
                    update_width=False,
                )

    @on(Input.Changed, "#shortcut_name, #shortcut_target, #shortcut_args")
    def editor_input_changed(self, event: Input.Changed) -> None:
        self._sync_draft_from_editor()

    @on(Select.Changed, "#shortcut_type, #shortcut_pane")
    def editor_select_changed(self, event: Select.Changed) -> None:
        self._sync_draft_from_editor()

    @on(DataTable.RowHighlighted, "#shortcut_manager_table")
    def row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self._syncing_editor:
            return
        row = event.data_table.cursor_row
        self._syncing_editor = True
        try:
            self._load_editor(row)
        finally:
            self._syncing_editor = False

    @on(Button.Pressed, "#shortcut_add")
    def add_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        if len(self._drafts) >= MAX_SHORTCUTS:
            self.app.notify(
                f"The shortcut bar supports up to {MAX_SHORTCUTS} links.",
                title="Link limit",
            )
            return
        self._drafts.append(
            {
                "label": "New Link",
                "kind": "folder",
                "target": str(self.current_path),
                "pane": "active",
                "args": "[]",
            }
        )
        self._render_rows(len(self._drafts) - 1)
        name = self.query_one("#shortcut_name", Input)
        name.focus()
        name.action_select_all()

    @on(Button.Pressed, "#shortcut_remove")
    def remove_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        index = self._editing_index
        if index is None or not 0 <= index < len(self._drafts):
            return
        del self._drafts[index]
        self._editing_index = None
        if self._drafts:
            self._render_rows(min(index, len(self._drafts) - 1))
        else:
            self.table.clear(columns=False)
            self._set_editor_enabled(False)

    def _move_current(self, delta: int) -> None:
        index = self._editing_index
        if index is None:
            return
        target = index + delta
        if not 0 <= target < len(self._drafts):
            return
        self._drafts[index], self._drafts[target] = (
            self._drafts[target],
            self._drafts[index],
        )
        self._render_rows(target)

    @on(Button.Pressed, "#shortcut_up")
    def up_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self._move_current(-1)

    @on(Button.Pressed, "#shortcut_down")
    def down_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self._move_current(1)

    @staticmethod
    def _browse_script(folder: bool, initial_directory: Path) -> str:
        initial = str(initial_directory).replace("'", "''")
        if folder:
            return (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
                f"$dialog.SelectedPath = '{initial}'; "
                "if ($dialog.ShowDialog() -eq 'OK') { $dialog.SelectedPath }"
            )
        return (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dialog = New-Object System.Windows.Forms.OpenFileDialog; "
            f"$dialog.InitialDirectory = '{initial}'; "
            "$dialog.Filter = 'All files (*.*)|*.*'; "
            "if ($dialog.ShowDialog() -eq 'OK') { $dialog.FileName }"
        )

    @work(thread=True, exclusive=True, group="shortcut-browser")
    def _browse(self, folder: bool) -> None:
        try:
            process_options: dict[str, object] = {}
            if os.name == "nt":
                command = [
                    "powershell.exe",
                    "-NoProfile",
                    "-STA",
                    "-Command",
                    self._browse_script(folder, self.current_path),
                ]
                process_options["creationflags"] = subprocess.CREATE_NO_WINDOW
            elif zenity := shutil.which("zenity"):
                command = [
                    zenity,
                    "--file-selection",
                    f"--filename={self.current_path}{os.sep}",
                ]
                if folder:
                    command.append("--directory")
            elif kdialog := shutil.which("kdialog"):
                command = [
                    kdialog,
                    "--getexistingdirectory" if folder else "--getopenfilename",
                    str(self.current_path),
                ]
            else:
                self.app.call_from_thread(
                    self.app.notify,
                    "Install zenity or kdialog to use Browse on Linux.",
                    title="Browse unavailable",
                )
                return

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
                **process_options,
            )
            selected = result.stdout.strip()
            if selected:
                self.app.call_from_thread(self._set_browsed_target, selected)
        except Exception as exc:
            self.app.call_from_thread(
                self.app.notify,
                f"Could not open the browser: {exc}",
                title="Browse failed",
            )

    def _set_browsed_target(self, target: str) -> None:
        field = self.query_one("#shortcut_target", Input)
        field.value = target
        field.focus()

    @on(Button.Pressed, "#shortcut_browse_file")
    def browse_file_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self._browse(False)

    @on(Button.Pressed, "#shortcut_browse_folder")
    def browse_folder_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self._browse(True)

    def _validated_shortcuts(self) -> list[ShortcutDefinition] | None:
        self._sync_draft_from_editor()
        validated: list[ShortcutDefinition] = []
        for index, draft in enumerate(self._drafts, start=1):
            label = draft["label"].strip()
            kind = draft["kind"].strip().lower()
            target = draft["target"].strip()
            pane = draft["pane"].strip().lower()
            if not label or not target or kind not in SHORTCUT_KINDS:
                self.app.notify(
                    f"Row {index} needs a name, a valid type, and a target.",
                    title="Invalid link",
                )
                return None
            try:
                args_value = json.loads(draft["args"].strip() or "[]")
                if not isinstance(args_value, list):
                    raise ValueError("arguments must be a JSON list")
            except (json.JSONDecodeError, ValueError) as exc:
                self.app.notify(
                    f"Row {index} has invalid arguments: {exc}",
                    title="Invalid arguments",
                )
                return None
            validated.append(
                ShortcutDefinition(
                    label=label,
                    kind=kind,
                    target=target,
                    args=tuple(str(value) for value in args_value),
                    pane=pane,
                )
            )
        return validated

    @on(Button.Pressed, "#shortcut_save")
    def save_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        shortcuts = self._validated_shortcuts()
        if shortcuts is not None:
            self.dismiss(shortcuts)

    @on(Button.Pressed, "#shortcut_cancel")
    @on(Button.Pressed, "#shortcut_manager_close")
    def cancel_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)

    def action_cancel_manager(self) -> None:
        self.dismiss(None)
