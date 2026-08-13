from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Optional, Sequence

from rich.cells import cell_len
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ProgressBar, Select, Static


class CompactConfirmScreen(ModalScreen[bool]):
    """Small confirmation dialog with visible cancel and close controls."""

    CSS = """
    CompactConfirmScreen {
        align: center middle;
        background: #00000073;
    }

    #confirm_dialog {
        border: solid $warning;
        background: $surface;
        padding: 0 1;
    }

    #confirm_header {
        height: 1;
        min-height: 1;
        max-height: 1;
    }

    #confirm_title {
        width: 1fr;
        height: 1;
        color: $warning;
        text-style: bold;
        text-wrap: nowrap;
    }

    #confirm_close {
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

    #confirm_message {
        color: $foreground;
        margin-top: 1;
        text-wrap: nowrap;
        overflow-x: auto;
    }

    #confirm_actions {
        height: 3;
        align-horizontal: right;
    }

    #confirm_actions Button {
        min-width: 11;
        width: auto;
        height: 3;
        margin-left: 1;
    }

    #confirm_help {
        height: 1;
        color: #aaaaaa;
    }
    """

    def __init__(self, message: str, title: str = "Confirm") -> None:
        super().__init__()
        self.message = message
        self.dialog_title = title
        lines = message.splitlines() or [message]
        longest = max((cell_len(line) for line in lines), default=20)
        self.preferred_width = max(
            72,
            longest + 8,
            cell_len("Enter/Y: Yes   N/Esc/X: Cancel") + 6,
        )
        self.preferred_height = max(9, min(20, len(lines) + 7))

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm_dialog"):
            with Horizontal(id="confirm_header"):
                yield Label(self.dialog_title, id="confirm_title")
                yield Button("X", id="confirm_close")
            yield Static(self.message, id="confirm_message")
            with Horizontal(id="confirm_actions"):
                yield Button("Yes", id="confirm_yes", variant="error")
                yield Button("Cancel", id="confirm_cancel")
            yield Static(
                "Enter/Y: Yes   N/Esc/X: Cancel", id="confirm_help"
            )

    def on_mount(self) -> None:
        dialog = self.query_one("#confirm_dialog", Vertical)
        dialog.styles.width = min(
            self.preferred_width,
            max(34, self.size.width - 4),
        )
        dialog.styles.height = min(
            self.preferred_height,
            max(9, self.size.height - 4),
        )
        # File operations are opened only after the user explicitly requests
        # them.  Make Enter confirm that pending operation.  Previously the
        # Cancel button received initial focus, so Enter silently cancelled
        # Move/Delete and made the commands appear broken.
        self.query_one("#confirm_yes", Button).focus()

    def _accept(self) -> None:
        self.dismiss(True)

    def _cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#confirm_yes")
    def yes_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self._accept()

    @on(Button.Pressed, "#confirm_cancel")
    @on(Button.Pressed, "#confirm_close")
    def cancel_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self._cancel()

    def key_y(self) -> None:
        self._accept()

    def key_n(self) -> None:
        self._cancel()

    def key_escape(self) -> None:
        self._cancel()


class FileOperationProgressScreen(ModalScreen[None]):
    """Responsive progress window for long copy, move, and delete batches."""

    CSS = """
    FileOperationProgressScreen {
        align: center middle;
        background: #00000073;
    }

    #file_operation_dialog {
        width: 72;
        max-width: 94%;
        height: 12;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }

    #file_operation_title {
        height: 1;
        color: $foreground;
        text-style: bold;
    }

    #file_operation_item {
        height: 1;
        margin-top: 1;
        color: #bbbbbb;
        text-overflow: ellipsis;
        text-wrap: nowrap;
    }

    #file_operation_progress {
        margin-top: 1;
    }

    #file_operation_actions {
        height: 3;
        margin-top: 1;
        align-horizontal: right;
    }

    #file_operation_cancel {
        min-width: 12;
        height: 3;
    }
    """

    def __init__(self, operation: str, total: int, cancel_event: Event) -> None:
        super().__init__()
        self.operation = operation.title()
        self.total = total
        self.cancel_event = cancel_event

    def compose(self) -> ComposeResult:
        with Vertical(id="file_operation_dialog"):
            yield Label(
                f"{self.operation}: 0 / {self.total}",
                id="file_operation_title",
            )
            yield Static("Preparing...", id="file_operation_item")
            yield ProgressBar(
                total=max(1, self.total),
                show_eta=True,
                id="file_operation_progress",
            )
            with Horizontal(id="file_operation_actions"):
                yield Button("Cancel", id="file_operation_cancel")

    def on_mount(self) -> None:
        self.query_one("#file_operation_cancel", Button).focus()

    def update_progress(self, completed: int, item_name: str) -> None:
        self.query_one("#file_operation_title", Label).update(
            f"{self.operation}: {completed:,} / {self.total:,}"
        )
        self.query_one("#file_operation_item", Static).update(item_name)
        self.query_one("#file_operation_progress", ProgressBar).update(
            progress=completed,
            total=max(1, self.total),
        )

    def request_cancel(self) -> None:
        self.cancel_event.set()
        self.query_one("#file_operation_item", Static).update(
            "Cancelling after the current item..."
        )
        button = self.query_one("#file_operation_cancel", Button)
        button.disabled = True
        button.label = "Cancelling..."

    @on(Button.Pressed, "#file_operation_cancel")
    def cancel_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self.request_cancel()

    def key_escape(self) -> None:
        self.request_cancel()


@dataclass(frozen=True)
class CopyRequest:
    """User choices returned by the compact copy dialog."""

    new_name: Optional[str]


class CompactCopyScreen(ModalScreen[Optional[CopyRequest]]):
    """Copy dialog that supports Save As for a single selected item."""

    CSS = """
    CompactCopyScreen {
        align: center middle;
        background: #00000073;
    }

    #copy_dialog {
        height: 14;
        border: solid $primary;
        background: $surface;
        padding: 0 1;
    }

    #copy_header {
        height: 1;
        min-height: 1;
        max-height: 1;
    }

    #copy_title {
        width: 1fr;
        height: 1;
        color: $foreground;
        text-style: bold;
        text-wrap: nowrap;
    }

    #copy_close {
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

    .copy_info {
        height: 1;
        color: $foreground;
        text-wrap: nowrap;
    }

    #copy_name_label {
        height: 1;
        margin-top: 1;
        color: $foreground;
    }

    #copy_name {
        height: 3;
    }

    #copy_actions {
        height: 3;
        align-horizontal: right;
    }

    #copy_actions Button {
        min-width: 11;
        width: auto;
        height: 3;
        margin-left: 1;
    }

    #copy_help {
        height: 1;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        items: Sequence[Path],
        destination: Path,
    ) -> None:
        super().__init__()
        self.items = list(items)
        self.destination = destination
        self.single_item = len(self.items) == 1
        if self.single_item:
            self.source_summary = self.items[0].name
            self.initial_name = self.items[0].name
        else:
            self.source_summary = f"{len(self.items)} selected items"
            self.initial_name = "(original names)"

        content_width = max(
            cell_len(self.source_summary) + 14,
            cell_len(str(destination)) + 16,
            cell_len(self.initial_name) + 10,
            48,
        )
        self.preferred_width = max(80, content_width)

    def compose(self) -> ComposeResult:
        with Vertical(id="copy_dialog"):
            with Horizontal(id="copy_header"):
                yield Label("Copy", id="copy_title")
                yield Button("X", id="copy_close")
            yield Static(f"Source: {self.source_summary}", classes="copy_info")
            yield Static(f"Destination: {self.destination}", classes="copy_info")
            yield Label("Save as:", id="copy_name_label")
            yield Input(
                value=self.initial_name,
                id="copy_name",
                disabled=not self.single_item,
            )
            with Horizontal(id="copy_actions"):
                yield Button("Copy", id="copy_ok", variant="primary")
                yield Button("Cancel", id="copy_cancel")
            yield Static("Enter: Copy   Esc/X: Cancel", id="copy_help")

    def on_mount(self) -> None:
        dialog = self.query_one("#copy_dialog", Vertical)
        dialog.styles.width = min(
            self.preferred_width,
            max(46, self.size.width - 4),
        )
        if self.single_item:
            field = self.query_one("#copy_name", Input)
            field.focus()
            field.action_select_all()
        else:
            self.query_one("#copy_ok", Button).focus()

    def _submit(self) -> None:
        if not self.single_item:
            self.dismiss(CopyRequest(None))
            return

        name = self.query_one("#copy_name", Input).value.strip()
        if (
            not name
            or name in {".", ".."}
            or Path(name).name != name
            or "/" in name
            or "\\" in name
        ):
            self.app.notify(
                "Enter a file or folder name, not a path.",
                title="Invalid name",
            )
            return
        self.dismiss(CopyRequest(name))

    @on(Input.Submitted, "#copy_name")
    def submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._submit()

    @on(Button.Pressed, "#copy_ok")
    def copy_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self._submit()

    @on(Button.Pressed, "#copy_cancel")
    @on(Button.Pressed, "#copy_close")
    def cancel_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)

    def key_escape(self) -> None:
        self.dismiss(None)


class CompactDriveScreen(ModalScreen[Optional[str]]):
    """Mouse- and keyboard-friendly dropdown for selecting a drive."""

    CSS = """
    CompactDriveScreen {
        align: center middle;
        background: #00000073;
    }

    #drive_dialog {
        height: 11;
        border: solid $primary;
        background: $surface;
        padding: 0 1;
    }

    #drive_header {
        height: 1;
        min-height: 1;
        max-height: 1;
    }

    #drive_title {
        width: 1fr;
        height: 1;
        color: $foreground;
        text-style: bold;
        text-wrap: nowrap;
    }

    #drive_close {
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

    #drive_prompt {
        height: 1;
        margin-top: 1;
        color: $foreground;
        text-wrap: nowrap;
    }

    #drive_select {
        height: 3;
        width: 1fr;
    }

    #drive_actions {
        height: 3;
        align-horizontal: right;
    }

    #drive_actions Button {
        min-width: 11;
        width: auto;
        height: 3;
        margin-left: 1;
    }

    #drive_help {
        height: 1;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        choices: Sequence[tuple[str, str]],
        current_drive: str,
    ) -> None:
        super().__init__()
        self.choices = list(choices)
        values = {value for _, value in self.choices}
        self.initial = (
            current_drive if current_drive in values else self.choices[0][1]
        )
        self._accept_changes = False
        longest = max((cell_len(label) for label, _ in self.choices), default=36)
        self.preferred_width = max(
            72,
            longest + 10,
            cell_len(
                "Enter: list/select   Up/Down: move   Esc/X: Cancel"
            )
            + 6,
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="drive_dialog"):
            with Horizontal(id="drive_header"):
                yield Label("Select Drive", id="drive_title")
                yield Button("X", id="drive_close")
            yield Static("Available drives:", id="drive_prompt")
            yield Select(
                self.choices,
                value=self.initial,
                allow_blank=False,
                id="drive_select",
            )
            with Horizontal(id="drive_actions"):
                yield Button("Open", id="drive_open", variant="primary")
                yield Button("Cancel", id="drive_cancel")
            yield Static(
                "Enter: list/select   Up/Down: move   Esc/X: Cancel",
                id="drive_help",
            )

    def on_mount(self) -> None:
        dialog = self.query_one("#drive_dialog", Vertical)
        dialog.styles.width = min(
            self.preferred_width,
            max(48, self.size.width - 4),
        )
        self.query_one("#drive_select", Select).focus()
        self.call_after_refresh(self._enable_change_submit)

    def _enable_change_submit(self) -> None:
        self._accept_changes = True

    def _submit(self) -> None:
        value = self.query_one("#drive_select", Select).value
        if value is Select.BLANK:
            return
        self.dismiss(str(value))

    @on(Button.Pressed, "#drive_open")
    def open_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self._submit()

    @on(Select.Changed, "#drive_select")
    def drive_changed(self, event: Select.Changed) -> None:
        if self._accept_changes and event.value is not Select.BLANK:
            self.dismiss(str(event.value))

    @on(Button.Pressed, "#drive_cancel")
    @on(Button.Pressed, "#drive_close")
    def cancel_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)

    def key_escape(self) -> None:
        self.dismiss(None)
