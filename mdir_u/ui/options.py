from __future__ import annotations

from typing import Mapping, Optional

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Label, Static

from .inputs import ThinCursorInput as Input
from ..keymap import (
    KEY_DEFINITIONS,
    effective_keys,
    normalize_shortcut,
    validate_keymap,
)


class OptionsScreen(ModalScreen[Optional[str]]):
    """Small replacement for the generic framework command palette."""

    BINDINGS = [
        Binding("escape", "close_options", "Close", show=False, priority=True),
        Binding("left", "focus_left", "Left", show=False, priority=True),
        Binding("right", "focus_right", "Right", show=False, priority=True),
        Binding("up", "focus_up", "Up", show=False, priority=True),
        Binding("down", "focus_down", "Down", show=False, priority=True),
    ]

    OPTION_IDS = (
        "option_keys",
        "option_links",
        "option_theme",
        "option_help",
        "options_close",
    )

    CSS = """
    OptionsScreen { align: center middle; background: #00000073; }
    #options_dialog {
        width: 54;
        height: 18;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }
    #options_title { height: 2; color: $accent; text-style: bold; }
    #options_description { height: 3; color: $text-muted; }
    #options_actions { height: 7; layout: grid; grid-size: 2 2; grid-gutter: 1 2; }
    #options_actions Button { width: 100%; height: 3; }
    #options_close { width: 100%; height: 3; margin-top: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="options_dialog"):
            yield Label("mDIR Options", id="options_title")
            yield Static(
                "Change settings or open the mDIR user guide.",
                id="options_description",
            )
            with Horizontal(id="options_actions"):
                yield Button("Keys", id="option_keys")
                yield Button("Links", id="option_links")
                yield Button("Theme", id="option_theme")
                yield Button("Help", id="option_help")
            yield Button("Close", id="options_close")

    def on_mount(self) -> None:
        self.query_one("#option_keys", Button).focus()

    def _focused_index(self) -> int:
        focused_id = getattr(self.focused, "id", None)
        try:
            return self.OPTION_IDS.index(focused_id)
        except ValueError:
            return 0

    def _focus_index(self, index: int) -> None:
        index = max(0, min(index, len(self.OPTION_IDS) - 1))
        self.query_one(f"#{self.OPTION_IDS[index]}", Button).focus()

    def action_focus_left(self) -> None:
        index = self._focused_index()
        self._focus_index(index - 1 if index in {1, 3} else index)

    def action_focus_right(self) -> None:
        index = self._focused_index()
        self._focus_index(index + 1 if index in {0, 2} else index)

    def action_focus_up(self) -> None:
        index = self._focused_index()
        if index == 4:
            self._focus_index(2)
        elif index >= 2:
            self._focus_index(index - 2)

    def action_focus_down(self) -> None:
        index = self._focused_index()
        if index <= 1:
            self._focus_index(index + 2)
        elif index <= 3:
            self._focus_index(4)

    @on(Button.Pressed)
    def option_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        option = {
            "option_keys": "keys",
            "option_links": "links",
            "option_theme": "theme",
            "option_help": "help",
        }.get(event.button.id or "")
        self.dismiss(option)

    def action_close_options(self) -> None:
        self.dismiss(None)


class KeyManagerScreen(ModalScreen[Optional[dict[str, str]]]):
    """Edit non-essential application bindings with collision checks."""

    BINDINGS = [
        Binding("escape", "cancel_keys", "Close", show=False, priority=True),
    ]

    CSS = """
    KeyManagerScreen { align: center middle; background: #00000073; }
    #key_dialog {
        width: 82;
        height: 88%;
        min-height: 28;
        max-height: 48;
        border: solid $primary;
        background: $surface;
        padding: 0 1;
    }
    #key_title { height: 2; color: $accent; text-style: bold; }
    #key_table { height: 1fr; min-height: 12; background: $background; }
    #key_editor { height: 3; margin-top: 1; }
    #key_editor Label { width: 12; content-align: left middle; }
    #key_input { width: 1fr; height: 3; }
    #key_apply { width: 12; height: 3; margin-left: 1; }
    #key_status { height: 2; color: $text-muted; }
    #key_actions { height: 3; align-horizontal: right; }
    #key_actions Button { width: auto; min-width: 12; height: 3; margin-left: 1; }
    """

    def __init__(self, overrides: Mapping[str, str]) -> None:
        super().__init__()
        effective = effective_keys(overrides)
        self._keys = {
            definition.action + ":" + definition.default_key: (
                effective.get(definition.binding_id, definition.default_key)
                if definition.editable
                else definition.default_key
            )
            for definition in KEY_DEFINITIONS
        }

    def compose(self) -> ComposeResult:
        with Vertical(id="key_dialog"):
            yield Label("Keys", id="key_title")
            table = DataTable(id="key_table", cursor_type="row", zebra_stripes=True)
            table.add_columns("Action", "Key", "Type")
            yield table
            with Horizontal(id="key_editor"):
                yield Label("New key")
                yield Input(id="key_input", placeholder="Example: ctrl+alt+x")
                yield Button("Apply", id="key_apply", variant="primary")
            yield Static(
                "Fixed keys protect navigation, selection, opening, and Options.",
                id="key_status",
            )
            with Horizontal(id="key_actions"):
                yield Button("Reset Selected", id="key_reset")
                yield Button("Reset All", id="key_reset_all")
                yield Button("Save", id="key_save", variant="success")
                yield Button("Cancel", id="key_cancel")

    def on_mount(self) -> None:
        self._refresh_table(0)

    @staticmethod
    def _definition_key(index: int) -> str:
        definition = KEY_DEFINITIONS[index]
        return definition.action + ":" + definition.default_key

    def _selected_index(self) -> int:
        table = self.query_one("#key_table", DataTable)
        return max(0, min(table.cursor_row, len(KEY_DEFINITIONS) - 1))

    def _refresh_table(self, keep_index: int) -> None:
        table = self.query_one("#key_table", DataTable)
        table.clear()
        for definition in KEY_DEFINITIONS:
            key = self._keys[definition.action + ":" + definition.default_key]
            table.add_row(
                definition.label,
                key,
                "Editable" if definition.editable else "Fixed",
            )
        if table.row_count:
            table.move_cursor(row=max(0, min(keep_index, table.row_count - 1)))
        self._sync_editor()

    def _sync_editor(self) -> None:
        index = self._selected_index()
        definition = KEY_DEFINITIONS[index]
        key_input = self.query_one("#key_input", Input)
        key_input.value = self._keys[self._definition_key(index)]
        key_input.disabled = not definition.editable
        self.query_one("#key_apply", Button).disabled = not definition.editable
        message = (
            f"{definition.label}: fixed essential key"
            if not definition.editable
            else f"{definition.label}: enter one non-conflicting shortcut"
        )
        self.query_one("#key_status", Static).update(message)

    @on(DataTable.RowHighlighted, "#key_table")
    def row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._sync_editor()

    def _candidate_overrides(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for index, definition in enumerate(KEY_DEFINITIONS):
            if definition.editable and definition.binding_id:
                values[definition.binding_id] = self._keys[
                    self._definition_key(index)
                ]
        return validate_keymap(values)

    @on(Button.Pressed, "#key_apply")
    def apply_key(self, event: Button.Pressed) -> None:
        event.stop()
        index = self._selected_index()
        definition = KEY_DEFINITIONS[index]
        if not definition.editable:
            return
        try:
            previous = self._keys[self._definition_key(index)]
            self._keys[self._definition_key(index)] = normalize_shortcut(
                self.query_one("#key_input", Input).value
            )
            self._candidate_overrides()
        except ValueError as exc:
            self._keys[self._definition_key(index)] = previous
            self.query_one("#key_status", Static).update(str(exc))
            return
        self._refresh_table(index)
        self.query_one("#key_status", Static).update(
            "Key updated in the draft. Select Save to keep it."
        )

    @on(Button.Pressed, "#key_reset")
    def reset_selected(self, event: Button.Pressed) -> None:
        event.stop()
        index = self._selected_index()
        definition = KEY_DEFINITIONS[index]
        if definition.editable:
            self._keys[self._definition_key(index)] = definition.default_key
            self._refresh_table(index)

    @on(Button.Pressed, "#key_reset_all")
    def reset_all(self, event: Button.Pressed) -> None:
        event.stop()
        for index, definition in enumerate(KEY_DEFINITIONS):
            self._keys[self._definition_key(index)] = definition.default_key
        self._refresh_table(0)
        self.query_one("#key_status", Static).update("All editable keys reset.")

    @on(Button.Pressed, "#key_save")
    def save_keys(self, event: Button.Pressed) -> None:
        event.stop()
        try:
            self.dismiss(self._candidate_overrides())
        except ValueError as exc:
            self.query_one("#key_status", Static).update(str(exc))

    @on(Button.Pressed, "#key_cancel")
    def cancel_button(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)

    def action_cancel_keys(self) -> None:
        self.dismiss(None)

