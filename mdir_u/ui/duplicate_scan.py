"""Visible, cancellable progress for recursive duplicate scans.

Progress display is read-only: pressing Cancel only stops scanning. It never
deletes, relocates, edits or marks any discovered file.
"""
from __future__ import annotations

from pathlib import Path
import re
from threading import Event

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


_HASH_PROGRESS = re.compile(r"SHA-256:\s*([\d,]+)/([\d,]+)")

def duplicate_scan_status(description: str, count: int = 0) -> str:
    """Format honest phase-specific progress for the live footer.

    Directory discovery and similar-image enumeration have unknown totals;
    never invent an overall percentage for those phases.
    """
    matched = _HASH_PROGRESS.search(description)
    if matched:
        done = int(matched.group(1).replace(",", ""))
        total = int(matched.group(2).replace(",", ""))
        percentage = min(100.0, done * 100.0 / total) if total else 100.0
        return f"DUP SCAN SHA-256 {percentage:.1f}% ({done:,}/{total:,}) [Ctrl+Alt+D]"
    if description.startswith("SHA-256 done"):
        return "DUP SCAN: checking similar images (total unknown) [Ctrl+Alt+D]"
    if "Scan complete:" in description:
        return "DUP SCAN: preparing SHA-256 candidates [Ctrl+Alt+D]"
    if "similar" in description.lower():
        return "DUP SCAN: checking similar images (total unknown) [Ctrl+Alt+D]"
    return f"DUP SCAN: discovering files ({count:,} found; total unknown) [Ctrl+Alt+D]"


class DuplicateScanProgressScreen(ModalScreen[None]):
    CSS = """
    DuplicateScanProgressScreen {
        align: center middle;
        background: #00000088;
    }
    #duplicate_scan_dialog {
        width: 84%;
        max-width: 110;
        height: 19;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }
    #duplicate_scan_title { height: 1; text-style: bold; }
    #duplicate_scan_root { height: 3; color: $text-muted; }
    #duplicate_scan_phase { height: 4; color: $foreground; }
    #duplicate_scan_help { height: 3; color: $text-muted; }
    #duplicate_scan_actions { height: 3; align-horizontal: right; }
    #duplicate_scan_actions Button { min-width: 17; margin-left: 2; }
    """

    def __init__(self, root: Path, cancel_event: Event) -> None:
        super().__init__()
        self.root = root
        self.cancel_event = cancel_event
        self.progress_count = 0
        self.progress_phase = "Starting recursive file scan..."

    def compose(self) -> ComposeResult:
        with Vertical(id="duplicate_scan_dialog"):
            yield Label("Duplicate Search — IN PROGRESS", id="duplicate_scan_title")
            yield Static(
                f"Search root: {self.root}\nIncludes this directory and all accessible subdirectories.",
                id="duplicate_scan_root",
            )
            yield Static(
                f"{duplicate_scan_status(self.progress_phase, self.progress_count)}\n"
                f"{self.progress_phase}",
                id="duplicate_scan_phase",
            )
            yield Static(
                "In foreground, Duplicate Review opens automatically at completion.\n"
                "Background mode lets you work in mDIR. Ctrl+Alt+D reopens "
                "progress or completed results. No files are changed.",
                id="duplicate_scan_help",
            )
            with Horizontal(id="duplicate_scan_actions"):
                yield Button("Background", id="duplicate_scan_background")
                yield Button("Cancel Scan", id="duplicate_scan_cancel", variant="error")

    def on_mount(self) -> None:
        self.query_one("#duplicate_scan_cancel", Button).focus()

    def update_progress(self, count: int, description: str) -> None:
        self.progress_count = count
        self.progress_phase = description
        if self.is_mounted:
            self.query_one("#duplicate_scan_phase", Static).update(
                f"{duplicate_scan_status(description, count)}\n{description}"
            )

    def request_cancel(self) -> None:
        if self.cancel_event.is_set():
            return
        self.cancel_event.set()
        self.progress_phase = (
            "Cancellation requested. Stopping after the current file operation. "
            "No results from an incomplete scan will be used."
        )
        if self.is_mounted:
            self.query_one("#duplicate_scan_phase", Static).update(self.progress_phase)
            self.query_one("#duplicate_scan_cancel", Button).disabled = True

    @on(Button.Pressed, "#duplicate_scan_background")
    def background_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self.app._background_duplicate_scan(self)

    @on(Button.Pressed, "#duplicate_scan_cancel")
    def cancel_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self.request_cancel()

    def key_escape(self) -> None:
        self.request_cancel()
