from __future__ import annotations

import os
import stat as stat_module
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.coordinate import Coordinate
from textual.message import Message
from textual.widgets import Input, Static

from .base import BaseApp
from . import core as legacy
from .ui.rename import SlowRenameDataTable


AI_SELECTOR_WIDTH = 30


class DirectoryPathInput(Input):
    """Single-line editable directory path for a file pane."""

    BINDINGS = [
        Binding(
            "escape",
            "cancel_path_edit",
            "Cancel path edit",
            show=False,
            priority=True,
        ),
    ]

    class Cancelled(Message):
        """Request cancellation without changing the current directory."""

    def action_cancel_path_edit(self) -> None:
        self.post_message(self.Cancelled())


BaseFilePane = legacy.FilePane


@dataclass(frozen=True)
class CachedEntry:
    """Filesystem metadata captured once during a directory scan."""

    path: Path
    is_directory: bool
    size: int
    modified: float
    name_casefold: str = ""
    extension: str = ""
    size_text: str = ""
    modified_text: str = ""


class EditablePathFilePane(BaseFilePane):
    """File pane with a directly editable directory path bar."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.cached_entries: list[CachedEntry] = []
        self.metadata_by_path: dict[Path, CachedEntry] = {}
        self.row_by_path: dict[Path, int] = {}
        self.cached_path: Path | None = None
        self.total_file_count = 0
        self.total_folder_count = 0
        self.total_file_size = 0

    def compose(self) -> ComposeResult:
        yield DirectoryPathInput(
            value=str(self.current_path),
            id=f"{self.id}_path",
            classes="pane_path",
        )
        table = SlowRenameDataTable(cursor_type="row", zebra_stripes=False)
        self._add_columns(table)
        yield table
        yield Static("", classes="pane_info")
        yield Static("", classes="pane_summary")

    @staticmethod
    def _name_text(entry: CachedEntry, marked: bool) -> Text:
        """Render a cached entry name without another filesystem query."""
        prefix = "* " if marked else "  "
        text = Text(
            prefix
            + legacy.display_file_title(
                entry.path,
                is_directory=entry.is_directory,
            )
        )
        if marked:
            text.stylize("bold bright_yellow")
        elif entry.is_directory:
            text.stylize("bold bright_cyan")
        elif entry.path.suffix.lower() in {
            ".exe",
            ".com",
            ".msi",
            ".bat",
            ".cmd",
            ".ps1",
        }:
            text.stylize("bright_green")
        else:
            text.stylize("bright_white")
        return text

    def _entry_sort_key(self, entry: CachedEntry):
        name = entry.name_casefold or entry.path.name.casefold()
        if self.sort_mode == "ext":
            return (
                entry.extension
                or entry.path.suffix.lower().lstrip("."),
                name,
            )
        if self.sort_mode == "size":
            return (entry.size, name)
        if self.sort_mode == "modified":
            return (entry.modified, name)
        return name

    def _sort_cached_entries(self) -> None:
        directories = [
            entry for entry in self.cached_entries if entry.is_directory
        ]
        files = [
            entry for entry in self.cached_entries if not entry.is_directory
        ]
        directories.sort(
            key=self._entry_sort_key,
            reverse=self.sort_reverse,
        )
        files.sort(
            key=self._entry_sort_key,
            reverse=self.sort_reverse,
        )
        self.cached_entries = directories + files

    def _scan_directory(self) -> None:
        """Scan once and retain all metadata needed by the table and summary."""
        scanned: list[CachedEntry] = []

        with os.scandir(self.current_path) as directory:
            for item in directory:
                try:
                    stat = item.stat()
                    attributes = int(
                        getattr(stat, "st_file_attributes", 0)
                    )
                    if not self.show_hidden_system:
                        if os.name == "nt":
                            hidden = bool(
                                attributes & legacy.FILE_ATTRIBUTE_HIDDEN
                                or attributes & legacy.FILE_ATTRIBUTE_SYSTEM
                            )
                        else:
                            hidden = item.name.startswith(".")
                        if hidden:
                            continue

                    is_directory = stat_module.S_ISDIR(stat.st_mode)
                    if (
                        not is_directory
                        and not stat_module.S_ISREG(stat.st_mode)
                    ):
                        continue
                    scanned.append(
                        CachedEntry(
                            path=Path(item.path),
                            is_directory=is_directory,
                            size=0 if is_directory else int(stat.st_size),
                            modified=float(stat.st_mtime),
                            name_casefold=item.name.casefold(),
                            extension=(
                                ""
                                if is_directory
                                else os.path.splitext(item.name)[1]
                                .lower()
                                .lstrip(".")
                            ),
                            size_text=(
                                "<DIR>"
                                if is_directory
                                else legacy.human_size(int(stat.st_size))
                            ),
                            modified_text=legacy.fmt_time(
                                float(stat.st_mtime)
                            ),
                        )
                    )
                except OSError:
                    continue

        self.cached_entries = scanned
        self.metadata_by_path = {
            entry.path: entry for entry in scanned
        }
        self.marked.intersection_update(self.metadata_by_path)
        self.cached_path = self.current_path
        self.total_file_count = sum(
            not entry.is_directory for entry in scanned
        )
        self.total_folder_count = len(scanned) - self.total_file_count
        self.total_file_size = sum(
            entry.size for entry in scanned if not entry.is_directory
        )
        self._sort_cached_entries()

    def _render_cached_rows(self, keep_name: str | None = None) -> None:
        """Replace table rows in one batch without touching the filesystem."""
        self.table.clear(columns=False)
        self.entries.clear()
        self.row_by_path.clear()
        rows: list[tuple[object, str, str, str]] = []

        if self.current_path.parent != self.current_path:
            rows.append(
                (
                    Text("..", style=legacy.PARENT_DIRECTORY_STYLE),
                    "",
                    "<DIR>",
                    "",
                )
            )
            self.entries.append(None)

        for entry in self.cached_entries:
            row = len(self.entries)
            self.entries.append(entry.path)
            self.row_by_path[entry.path] = row
            rows.append(
                (
                    self._name_text(
                        entry,
                        entry.path in self.marked,
                    ),
                    (
                        ""
                        if entry.is_directory
                        else legacy.display_extension(entry.path.suffix.lower())
                    ),
                    (
                        "<DIR>"
                        if entry.is_directory
                        else legacy.human_size(entry.size)
                    ),
                    legacy.fmt_time(entry.modified),
                )
            )

        if rows:
            self.table.add_rows(rows)

        if self.table.row_count:
            target_row = 0
            if keep_name:
                for entry in self.cached_entries:
                    if entry.path.name == keep_name:
                        target_row = self.row_by_path[entry.path]
                        break
            self.table.move_cursor(row=target_row, column=0)

        self.update_info()
        self.update_summary()

    def refresh_listing(self, keep_name: str | None = None) -> None:
        """Refresh a large directory with one scan and one table insertion."""
        arrow = "DESC" if self.sort_reverse else "ASC"
        self._update_path_bar(
            f"{self.current_path}   "
            f"[Sort: {self.sort_mode.upper()} {arrow}]"
        )
        try:
            self._scan_directory()
        except (PermissionError, OSError) as exc:
            self.cached_entries.clear()
            self.metadata_by_path.clear()
            self.row_by_path.clear()
            self.total_file_count = 0
            self.total_folder_count = 0
            self.total_file_size = 0
            self.table.clear(columns=False)
            self.entries.clear()
            self.query_one(".pane_info", Static).update(
                f"Access error: {exc}"
            )
            self.update_summary()
            return
        self._render_cached_rows(keep_name)

    def _rebuild_columns(self, keep_name: str | None = None) -> None:
        """Rebuild resized columns from cache instead of rescanning the drive."""
        self.table.clear(columns=True)
        self._add_columns(self.table)
        if self.cached_path == self.current_path:
            self._render_cached_rows(keep_name)
        else:
            self.refresh_listing(keep_name)

    def set_sort(self, mode: str) -> None:
        """Sort cached metadata without issuing new filesystem calls."""
        if self.sort_mode == mode:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_mode = mode
            self.sort_reverse = False
        current = self.selected_path()
        keep_name = current.name if current else None
        if self.cached_path != self.current_path:
            self.refresh_listing(keep_name)
            return
        self._sort_cached_entries()
        self._render_cached_rows(keep_name)

    def update_summary(self) -> None:
        """Calculate counts from cache and selected items only."""
        selected_files = 0
        selected_folders = 0
        selected_size = 0
        for path in self.marked:
            entry = self.metadata_by_path.get(path)
            if entry is None:
                continue
            if entry.is_directory:
                selected_folders += 1
            else:
                selected_files += 1
                selected_size += entry.size

        summary = (
            f"Capacity: {legacy.human_size(selected_size)} / "
            f"{legacy.human_size(self.total_file_size)}"
            f"    Files: {selected_files:,} / "
            f"{self.total_file_count:,}"
            f"    Folders: {selected_folders:,} / "
            f"{self.total_folder_count:,}"
        )
        self.query_one(".pane_summary", Static).update(summary)

    def _update_mark_cell(self, path: Path) -> None:
        row = self.row_by_path.get(path)
        entry = self.metadata_by_path.get(path)
        if row is None or entry is None:
            return
        self.table.update_cell_at(
            Coordinate(row, 0),
            self._name_text(entry, path in self.marked),
            update_width=False,
        )

    def toggle_mark_path(self, path: Path) -> None:
        """Toggle one row without rebuilding a large directory."""
        if path in self.marked:
            self.marked.remove(path)
        else:
            self.marked.add(path)
        self._update_mark_cell(path)
        self.update_info()
        self.update_summary()

    def shift_select(self, delta: int) -> None:
        """Extend a range and repaint only rows whose mark state changed."""
        if self.table.row_count <= 0:
            return
        current_row = max(0, self.table.cursor_row)
        if self.shift_anchor_row is None:
            self.shift_anchor_row = current_row
            self.shift_base_marked = set(self.marked)

        target_row = max(
            0,
            min(self.table.row_count - 1, current_row + delta),
        )
        self.select_range_to(target_row)

    def select_range_to(self, target_row: int) -> None:
        """Select through a mouse/keyboard endpoint and repaint changed rows."""
        if self.table.row_count <= 0:
            return
        current_row = max(0, self.table.cursor_row)
        if self.shift_anchor_row is None:
            self.shift_anchor_row = current_row
            self.shift_base_marked = set(self.marked)

        target_row = max(0, min(self.table.row_count - 1, target_row))
        lo = min(self.shift_anchor_row, target_row)
        hi = max(self.shift_anchor_row, target_row)
        range_paths = {
            path
            for path in self.entries[lo : hi + 1]
            if path is not None
        }
        previous = set(self.marked)
        self.marked = set(self.shift_base_marked) | range_paths
        for path in previous.symmetric_difference(self.marked):
            self._update_mark_cell(path)

        self.table.move_cursor(row=target_row, column=0)
        self.update_info()
        self.update_summary()

    def update_info(self) -> None:
        """Update the always-visible three-line item detail box."""
        box = self.query_one(".pane_info", Static)
        path = self.selected_path()
        if self.selected_is_parent():
            box.update(
                f"Name: ..    Type: Parent directory\n"
                f"Path: {self.current_path.parent}\n"
                f"Current: {self.current_path}"
            )
            return
        if path is None:
            box.update(f"Current: {self.current_path}\n\n")
            return
        entry = self.metadata_by_path.get(path)
        if entry is None:
            box.update(f"Name: {path.name}\nPath: {path}\n")
            return
        kind = (
            "DIR"
            if entry.is_directory
            else (path.suffix.lower().lstrip(".").upper() or "FILE")
        )
        size = (
            "<DIR>"
            if entry.is_directory
            else legacy.human_size(entry.size)
        )
        box.update(
            f"Name: {path.name}\n"
            f"Type: {kind}    Size: {size}    "
            f"Modified: {legacy.fmt_time(entry.modified)}\n"
            f"Path: {path}"
        )

    def _restore_path_and_focus_table(self) -> None:
        path_input = self.query_one(".pane_path", DirectoryPathInput)
        path_input.value = str(self.current_path)
        self.table.focus()

    def navigate_to_path(self, entered_path: str) -> bool:
        """Validate an entered path and navigate without losing pane state."""
        text = os.path.expandvars(entered_path.strip().strip('"'))
        if not text:
            self._restore_path_and_focus_table()
            return False

        candidate = Path(os.path.expanduser(text))
        if not candidate.is_absolute():
            candidate = self.current_path / candidate

        try:
            candidate = candidate.resolve()
            if not candidate.exists():
                raise FileNotFoundError("directory does not exist")
            if not candidate.is_dir():
                raise NotADirectoryError("path is not a directory")
        except (OSError, RuntimeError) as exc:
            self.query_one(".pane_path", DirectoryPathInput).value = str(
                self.current_path
            )
            self.app.set_status(f"Invalid directory: {entered_path} ({exc})")
            return False

        self.current_path = candidate
        self.marked.clear()
        self.refresh_listing()
        self.update_summary()

        app = self.app
        if isinstance(app, legacy.MDir):
            side = "left" if self.id == "left" else "right"
            app.set_active(side)
            app._save_paths()
            app.update_drive_bar()
            app.set_status(f"{side.upper()} pane: {candidate}")
        self.table.focus()
        return True

    @on(Input.Submitted, ".pane_path")
    def path_submitted(self, event: Input.Submitted) -> None:
        self.navigate_to_path(event.value)
        event.stop()

    @on(DirectoryPathInput.Cancelled)
    def path_edit_cancelled(self, event: DirectoryPathInput.Cancelled) -> None:
        self._restore_path_and_focus_table()
        self.app.set_status("Directory path edit cancelled.")
        event.stop()


class EditablePathApp(BaseApp):
    """AI-enabled file manager with editable paths and cached metadata."""

    TITLE = "MDIR-P"
    SUB_TITLE = (
        "Dual Pane File Manager / Codex AI / "
        "Codex Quick / Korean IME"
    )
    CSS = BaseApp.CSS + f"""
    AIPanel Select {{
        width: {AI_SELECTOR_WIDTH};
        min-width: {AI_SELECTOR_WIDTH};
        max-width: {AI_SELECTOR_WIDTH};
    }}

    FilePane .pane_path {{
        height: 1;
        min-height: 1;
        max-height: 1;
        border: none;
        padding: 0 1;
        background: #0000aa;
        color: white;
    }}

    FilePane .pane_path:focus {{
        border: none;
        background: #075985;
        color: white;
    }}
    """

    def switch_pane_to_drive(
        self,
        pane: legacy.FilePane,
        drive: str,
    ) -> None:
        """Use the opposite pane's directory when both panes use one drive."""
        latest = legacy.list_windows_drives()
        if latest != self.available_drives:
            self.available_drives = latest
            self._sync_drive_buttons()
            self.update_hidden_buttons()

        drive = drive.upper().rstrip("\\/")
        if not drive.endswith(":"):
            drive += ":"

        opposite = self.right if pane is self.left else self.left
        opposite_drive = (opposite.current_path.drive or "").upper()
        target = (
            opposite.current_path
            if opposite_drive == drive
            else Path(drive + "\\")
        )

        try:
            if not target.exists() or not target.is_dir():
                self.set_status(f"Directory not available: {target}")
                return
        except OSError as exc:
            self.set_status(f"Drive error: {drive} ({exc})")
            return

        try:
            pane.current_path = target
            pane.marked.clear()
            pane.refresh_listing()
            pane.update_summary()
            self._save_paths()
            self.update_drive_bar()
            self.set_status(f"{pane.id.upper()} pane: {target}")
            pane.table.focus()
        except Exception as exc:
            self.set_status(f"Failed to switch to {target}: {exc}")
