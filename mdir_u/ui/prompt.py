from __future__ import annotations

from typing import Optional

from rich.cells import cell_len
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class CompactPromptScreen(ModalScreen[Optional[str]]):
    """Wide auto-sized input dialog that keeps the MDIR screen visible."""

    CSS = """
    CompactPromptScreen {
        align: center middle;
        background: #00000073;
    }

    #compact_dialog {
        height: 10;
        border: solid $primary;
        background: $surface;
        padding: 0 1;
    }

    #compact_header {
        height: 1;
        min-height: 1;
        max-height: 1;
    }

    #compact_label {
        width: 1fr;
        height: 1;
        color: $foreground;
        text-wrap: nowrap;
    }

    #compact_close {
        width: 3;
        min-width: 3;
        height: 1;
        min-height: 1;
        max-height: 1;
        padding: 0;
        margin: 0;
        border: none;
        background: $error-darken-1;
        color: $text-error;
        text-style: bold;
    }

    #compact_close:hover {
        background: $error;
    }

    #compact_input {
        height: 3;
        margin: 0;
    }

    #compact_actions {
        height: 3;
        align-horizontal: right;
    }

    #compact_actions Button {
        min-width: 10;
        width: auto;
        height: 3;
        margin-left: 1;
    }

    #compact_help {
        height: 1;
        color: $text-muted;
    }
    """

    def __init__(self, title: str, initial: str = "") -> None:
        super().__init__()
        self.dialog_title = title
        self.initial = initial
        content_width = max(
            cell_len(title) + 7,
            cell_len(initial) + 6,
            cell_len("Enter: OK   X/Esc: Cancel") + 4,
        )
        # Do not cap the width before it is fitted to the terminal. Long file
        # and directory names should remain on one line whenever space allows.
        minimum_width = (
            80
            if title.strip().lower().startswith("new directory")
            else 72
        )
        self.preferred_width = max(minimum_width, content_width)

    def compose(self) -> ComposeResult:
        with Vertical(id="compact_dialog"):
            with Horizontal(id="compact_header"):
                yield Label(self.dialog_title, id="compact_label")
                yield Button("X", id="compact_close")
            yield Input(value=self.initial, id="compact_input")
            with Horizontal(id="compact_actions"):
                yield Button("OK", id="compact_ok", variant="primary")
                yield Button("Cancel", id="compact_cancel")
            yield Static("Enter: OK   X/Esc: Cancel", id="compact_help")

    def on_mount(self) -> None:
        dialog = self.query_one("#compact_dialog", Vertical)
        dialog.styles.width = max(
            26,
            min(self.preferred_width, max(26, self.size.width - 4)),
        )
        field = self.query_one("#compact_input", Input)
        field.focus()
        if self.initial:
            field.action_select_all()

    @on(Input.Submitted, "#compact_input")
    def submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    @on(Button.Pressed, "#compact_ok")
    def ok_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        value = self.query_one("#compact_input", Input).value.strip()
        self.dismiss(value)

    @on(Button.Pressed, "#compact_cancel")
    def cancel_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)

    @on(Button.Pressed, "#compact_close")
    def close_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)

    def key_escape(self) -> None:
        self.dismiss(None)
