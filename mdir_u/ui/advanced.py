from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Label, Static


@dataclass(frozen=True)
class AdvancedResult:
    category: str
    name: str
    location: str
    details: str
    path: Path


class AdvancedResultsScreen(ModalScreen[Path | None]):
    """Shared lightweight result browser for mIndex, duplicates and compare."""

    CSS = """
    AdvancedResultsScreen { align: center middle; background: #00000088; }
    #advanced_dialog {
        width: 96%; height: 90%; border: solid $primary;
        background: $surface; padding: 1 2;
    }
    #advanced_title { height: 1; text-style: bold; color: $foreground; }
    #advanced_summary { height: 2; color: #b7b7b7; margin-top: 1; }
    #advanced_results { height: 1fr; }
    #advanced_actions { height: 3; align-horizontal: right; margin-top: 1; }
    #advanced_actions Button { min-width: 12; height: 3; }
    """

    def __init__(
        self,
        title: str,
        summary: str,
        results: list[AdvancedResult],
    ) -> None:
        super().__init__()
        self.dialog_title = title
        self.summary = summary
        self.results = results

    def compose(self) -> ComposeResult:
        with Vertical(id="advanced_dialog"):
            yield Label(self.dialog_title, id="advanced_title")
            yield Static(self.summary, id="advanced_summary")
            yield DataTable(id="advanced_results", cursor_type="row")
            with Horizontal(id="advanced_actions"):
                yield Button("Open", id="advanced_open", disabled=not self.results)
                yield Button("Location", id="advanced_location", disabled=not self.results)
                yield Button("Close", id="advanced_close")

    def on_mount(self) -> None:
        table = self.query_one("#advanced_results", DataTable)
        table.add_columns("Group/Status", "Name", "Location", "Details")
        if self.results:
            table.add_rows(
                (item.category, item.name, item.location, item.details)
                for item in self.results
            )
            table.focus()

    def _selected(self) -> AdvancedResult | None:
        row = self.query_one("#advanced_results", DataTable).cursor_row
        return self.results[row] if 0 <= row < len(self.results) else None

    def _open(self) -> None:
        result = self._selected()
        if result is None:
            return
        if result.path.is_dir():
            self.dismiss(result.path)
        else:
            opener = getattr(self.app, "open_external_path", None)
            if callable(opener):
                opener(result.path)

    @on(Button.Pressed, "#advanced_open")
    def open_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self._open()

    @on(DataTable.RowSelected, "#advanced_results")
    def row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self._open()

    @on(Button.Pressed, "#advanced_location")
    def location_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        result = self._selected()
        if result is not None:
            self.dismiss(result.path)

    @on(Button.Pressed, "#advanced_close")
    def close_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)

    def key_escape(self) -> None:
        self.dismiss(None)
