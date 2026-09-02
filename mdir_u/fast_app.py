from __future__ import annotations

import asyncio
import faulthandler
import itertools
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual import events, work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Static

from .ui.search import AdvancedSearchScreen
from .file_pane import (
    CachedEntry,
    DirectoryPathInput,
    EditablePathFilePane,
    EditablePathApp,
    display_directory_path,
    scan_directory_entries,
)
from .ui.rename import SlowRenameDataTable
from . import core as legacy


LARGE_DIRECTORY_THRESHOLD = 20_000
DRIVE_POLL_INTERVAL_SECONDS = 10.0
DRIVE_USAGE_CACHE_SECONDS = 30.0
DIRECTORY_POLL_INTERVAL_SECONDS = 0.75
FILE_LIST_BACKGROUND = "#1e1e1e"
INITIAL_LISTING_DELAY_SECONDS = 0.01
FIRST_VISIBLE_ROW_BATCH_SIZE = 250
LISTING_ROW_BATCH_SIZE = 1_500
UI_HEARTBEAT_INTERVAL_SECONDS = 1.0
UI_HANG_THRESHOLD_SECONDS = 15.0
UI_HANG_WATCHDOG_INTERVAL_SECONDS = 2.0


class LargeDirectoryFilePane(EditablePathFilePane):
    """File pane optimized for directories containing tens of thousands of files."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.search_rows: list[tuple[int, str]] = []
        self.large_directory_mode = False
        self.last_listing_seconds = 0.0
        self.initial_listing_complete = False
        self._initial_listing_started = False
        self._listing_generation = 0
        self._directory_change_token: tuple[int, int] | None = None

    @staticmethod
    def _read_directory_change_token(path: Path) -> tuple[int, int] | None:
        """Read the inexpensive metadata Windows updates for entry changes."""
        try:
            stat = path.stat()
            return (int(stat.st_mtime_ns), int(stat.st_ctime_ns))
        except OSError:
            return None

    def directory_changed(self, token: tuple[int, int] | None) -> bool:
        """Return whether an external change occurred after the last scan."""
        return (
            self.initial_listing_complete
            and self.cached_path == self.current_path
            and token is not None
            and self._directory_change_token is not None
            and token != self._directory_change_token
        )

    def compose(self) -> ComposeResult:
        """Keep summary and detail information in one fixed bottom area."""
        yield DirectoryPathInput(
            value=display_directory_path(self.current_path),
            id=f"{self.id}_path",
            classes="pane_path",
        )
        table = SlowRenameDataTable(cursor_type="row", zebra_stripes=False)
        self._add_columns(table)
        yield table
        with Vertical(classes="pane_footer"):
            yield Static("", classes="pane_summary")
            yield Static("", classes="pane_info")

    def _scan_directory(self) -> None:
        super()._scan_directory()
        self.large_directory_mode = (
            len(self.cached_entries) >= LARGE_DIRECTORY_THRESHOLD
        )
        self._directory_change_token = self._read_directory_change_token(
            self.current_path
        )

    def _prepare_cached_rows(
        self,
        keep_name: str | None = None,
    ) -> tuple[list[tuple[object, str, str, str]], int]:
        """Build cached table rows without blocking on table insertion."""
        self.table.clear(columns=False)
        self.entries.clear()
        self.row_by_path.clear()
        self.search_rows.clear()
        rows: list[tuple[object, str, str, str]] = []

        if self.current_path.parent != self.current_path:
            rows.append(
                (
                    Text("..", style=legacy.PARENT_DIRECTORY_STYLE),
                    "",
                    legacy.centered_directory_size(),
                    "",
                )
            )
            self.entries.append(None)

        for entry in self.cached_entries:
            row = len(self.entries)
            self.entries.append(entry.path)
            self.row_by_path[entry.path] = row
            self.search_rows.append(
                (
                    row,
                    entry.name_casefold or entry.path.name.casefold(),
                )
            )
            extension, size, modified = self._format_display_values(entry)
            rows.append(
                (
                    self._name_text(
                        entry,
                        entry.path in self.marked,
                    ),
                    extension,
                    size,
                    modified,
                )
            )

        target_row = 0
        if keep_name:
            keep_folded = keep_name.casefold()
            for row, name in self.search_rows:
                if name == keep_folded:
                    target_row = row
                    break
        return rows, target_row

    def _render_cached_rows(self, keep_name: str | None = None) -> None:
        """Render in one batch while reusing preformatted cell strings."""
        rows, target_row = self._prepare_cached_rows(keep_name)
        if rows:
            self.table.add_rows(rows)
        if self.table.row_count:
            self.table.move_cursor(row=target_row, column=0)

        self.update_info()
        self.update_summary()

    def on_mount(self) -> None:
        """Mount an immediately visible pane and defer expensive row insertion."""
        self._last_available_width = max(1, self.size.width - 2)
        self.display_column_widths = self._effective_widths()
        self._apply_column_widths_to_table(self.display_column_widths)
        self._update_path_bar(
            f"{self.current_path}   [Sort: {self.sort_mode.upper()} ASC]"
        )
        self.query_one(".pane_info", Static).update(
            f"Loading directory...\nPath: {self.current_path}"
        )
        self.query_one(".pane_summary", Static).update(
            "Loading directory contents..."
        )
        self.set_timer(
            INITIAL_LISTING_DELAY_SECONDS,
            self._start_initial_listing,
        )

    def on_resize(self, event: events.Resize) -> None:
        """Resize empty or populated columns without rebuilding the listing."""
        available = max(1, int(event.size.width) - 2)
        if available == self._last_available_width:
            return
        self._last_available_width = available
        new_display = self._effective_widths()
        if new_display == self.display_column_widths:
            return
        self.display_column_widths = new_display
        self._apply_column_widths_to_table(new_display)

    def _start_initial_listing(self) -> None:
        if self._initial_listing_started:
            return
        self._initial_listing_started = True
        self._listing_generation += 1
        generation = self._listing_generation
        observed_path = self.current_path
        self.run_worker(
            self._load_directory_listing(generation, observed_path, None),
            name=f"{self.id}-initial-listing",
            group=f"{self.id}-directory-listing",
            exclusive=True,
            exit_on_error=False,
        )

    def _show_listing_loading(self, observed_path: Path) -> None:
        self.table.clear(columns=False)
        self.entries.clear()
        self.row_by_path.clear()
        self.search_rows.clear()
        self.cached_entries.clear()
        self.metadata_by_path.clear()
        self.cached_path = None
        self.total_file_count = self.total_folder_count = self.total_file_size = 0
        self.query_one(".pane_info", Static).update(
            f"Loading directory...\nPath: {observed_path}"
        )
        self.query_one(".pane_summary", Static).update(
            "Scanning directory in background..."
        )

    async def _load_directory_listing(
        self,
        generation: int,
        observed_path: Path,
        keep_name: str | None,
    ) -> None:
        """Scan off the UI thread and reveal the first rows immediately."""
        started = time.perf_counter()
        try:
            scanned = await asyncio.to_thread(
                scan_directory_entries, observed_path, self.show_hidden_system
            )
            token = await asyncio.to_thread(
                self._read_directory_change_token, observed_path
            )
        except (PermissionError, OSError) as exc:
            if generation != self._listing_generation or self.current_path != observed_path:
                return
            self.cached_entries.clear()
            self.metadata_by_path.clear()
            self.row_by_path.clear()
            self.table.clear(columns=False)
            self.entries.clear()
            self.initial_listing_complete = True
            self.query_one(".pane_info", Static).update(
                f"Access error: {exc}"
            )
            self.update_summary()
            return

        if generation != self._listing_generation or self.current_path != observed_path:
            return

        self._apply_scanned_entries(scanned, observed_path)
        self.large_directory_mode = len(scanned) >= LARGE_DIRECTORY_THRESHOLD
        self._directory_change_token = token

        rows, target_row = self._prepare_cached_rows(keep_name)
        total_rows = len(rows)
        self.update_summary()

        offset = 0
        while offset < total_rows:
            if generation != self._listing_generation or self.current_path != observed_path:
                return
            batch_size = FIRST_VISIBLE_ROW_BATCH_SIZE if offset == 0 else LISTING_ROW_BATCH_SIZE
            end = min(offset + batch_size, total_rows)
            self.table.add_rows(rows[offset:end])
            if offset == 0 and self.table.row_count:
                self.table.move_cursor(row=target_row, column=0)
            if end < total_rows:
                self.query_one(".pane_info", Static).update(
                    f"Loading items: {end:,} / {total_rows:,}\n"
                    f"Path: {self.current_path}"
                )
            offset = end
            await asyncio.sleep(0)

        if generation != self._listing_generation or self.current_path != observed_path:
            return
        if self.table.row_count:
            self.table.move_cursor(row=target_row, column=0)
        self.initial_listing_complete = True
        self.last_listing_seconds = time.perf_counter() - started
        self.update_info()
        self.update_summary()

    @staticmethod
    def _format_display_values(
        entry: CachedEntry,
    ) -> tuple[str, Text, str]:
        return (
            legacy.display_extension(
                entry.extension
                or (
                    ""
                    if entry.is_directory
                    else entry.path.suffix.lower().lstrip(".")
                )
            ),
            (
                legacy.centered_directory_size()
                if entry.is_directory
                else legacy.right_aligned_size(
                    entry.size_text or legacy.display_file_size(entry.size)
                )
            ),
            legacy.display_modified_text(
                entry.modified_text or legacy.fmt_time(entry.modified)
            ),
        )

    def refresh_listing(self, keep_name: str | None = None) -> None:
        """Start a non-blocking scan whenever the displayed path changes."""
        self._initial_listing_started = True
        self._listing_generation += 1
        generation = self._listing_generation
        observed_path = self.current_path
        self.initial_listing_complete = False
        arrow = "DESC" if self.sort_reverse else "ASC"
        self._update_path_bar(
            f"{observed_path}   [Sort: {self.sort_mode.upper()} {arrow}]"
        )
        self._show_listing_loading(observed_path)
        self.run_worker(
            self._load_directory_listing(generation, observed_path, keep_name),
            name=f"{self.id}-directory-listing",
            group=f"{self.id}-directory-listing",
            exclusive=True,
            exit_on_error=False,
        )

    def set_sort(self, mode: str) -> None:
        """Cancel partial startup insertion before applying a complete sort."""
        self._listing_generation += 1
        super().set_sort(mode)
        self.initial_listing_complete = True

    def update_summary(self) -> None:
        """Show a loading state until initial metadata is available."""
        if (
            not self.initial_listing_complete
            and self.cached_path != self.current_path
        ):
            self.query_one(".pane_summary", Static).update(
                "Loading directory contents..."
            )
            return
        super().update_summary()

    def find(self, query: str) -> bool:
        """Search a cached case-folded index without allocating row lists."""
        needle = query.casefold()
        if not needle or not self.search_rows:
            return False

        current = max(0, self.table.cursor_row + 1)
        split = 0
        for index, (row, _) in enumerate(self.search_rows):
            if row >= current:
                split = index
                break
        else:
            split = len(self.search_rows)

        for prefix_only in (True, False):
            ordered_indices = itertools.chain(
                range(split, len(self.search_rows)),
                range(0, split),
            )
            for index in ordered_indices:
                row, name = self.search_rows[index]
                matched = (
                    name.startswith(needle)
                    if prefix_only
                    else needle in name
                )
                if matched:
                    if row >= self.table.row_count:
                        continue
                    self.table.move_cursor(row=row, column=0)
                    self.update_info()
                    return True
        return False

    def _apply_column_widths_to_table(
        self,
        display_widths: dict[str, int],
    ) -> bool:
        """Apply mounted column widths without touching any directory rows."""
        try:
            table = self.table
            for key in legacy.COLUMN_ORDER:
                column = table.columns[key]
                column.width = int(display_widths[key])
                column.auto_width = False
                title = self._column_header_title(key)
                builder = (
                    self._centered_header_label
                    if key in {"extension", "size", "modified"}
                    else self._header_label
                )
                column.label = Text(
                    builder(title, display_widths[key])
                )
            table.clear_cached_dimensions()
            table._clear_caches()
            table._update_dimensions(())
            table.refresh(layout=True)
            return True
        except Exception:
            return False

    def set_column_widths(self, widths: dict[str, int]) -> None:
        """Resize columns in place without rebuilding every cached row."""
        self.column_widths = dict(widths)
        new_display = self._effective_widths()
        if new_display == self.display_column_widths:
            return
        self.display_column_widths = new_display

        if not self._apply_column_widths_to_table(new_display):
            if not self.initial_listing_complete:
                self.table.clear(columns=True)
                self._add_columns(self.table)
                return
            current = self.selected_path()
            keep_name = current.name if current else None
            self._rebuild_columns(keep_name)


class FastFileManagerApp(EditablePathApp):
    """File manager with cached, batched large-directory listings."""

    TITLE = "MDIR-U"
    SUB_TITLE = (
        "Ubuntu and Universal File Manager / Large Directory Mode / "
        "Codex Quick"
    )
    CSS = EditablePathApp.CSS + f"""
    FilePane DataTable {{
        height: 1fr;
        min-height: 0;
        background: {FILE_LIST_BACKGROUND};
        scrollbar-background: {FILE_LIST_BACKGROUND};
        scrollbar-background-hover: {FILE_LIST_BACKGROUND};
        scrollbar-background-active: {FILE_LIST_BACKGROUND};
    }}

    FilePane DataTable > .datatable--odd-row {{
        background: {FILE_LIST_BACKGROUND};
    }}

    FilePane DataTable > .datatable--even-row {{
        background: {FILE_LIST_BACKGROUND};
    }}

    FilePane DataTable > .datatable--fixed {{
        background: {FILE_LIST_BACKGROUND};
    }}
    """ + """
    Screen {
        layers: base startup;
    }

    #startup_cover {
        layer: startup;
        dock: top;
        width: 100%;
        height: 100%;
        background: #101010;
        color: #55ccff;
        content-align: center middle;
        text-align: center;
        text-style: bold;
    }

    FilePane .pane_footer {
        /* Keep the detail area in normal layout flow. A docked footer can be
           pushed below the visible pane when Windows Terminal has fewer rows
           after the shortcut bar is added. */
        height: 6;
        min-height: 6;
        max-height: 6;
        padding: 1 0 0 0;
        margin: 0;
        border-top: solid #E6D98A;
        background: #080808;
    }

    FilePane .pane_footer .pane_summary {
        dock: none;
        height: 1;
        min-height: 1;
        max-height: 1;
    }

    FilePane .pane_footer .pane_info {
        dock: none;
        height: 3;
        min-height: 3;
        max-height: 3;
    }
    """

    def __init__(self) -> None:
        self._last_drive_poll = 0.0
        self._drive_usage_cache: dict[str, tuple[float, str]] = {}
        self._directory_poll_running = False
        self._directory_poll_timer = None
        self._ui_heartbeat = time.monotonic()
        self._ui_heartbeat_timer = None
        self._hang_watchdog_stop = threading.Event()
        self._hang_watchdog_thread: threading.Thread | None = None
        self._hang_reported = False
        super().__init__()

    def compose(self) -> ComposeResult:
        """Compose MDIR with an opaque startup cover over the first frames."""
        yield from super().compose()
        yield Static(
            "MDIR-U\nStarting file panels...",
            id="startup_cover",
        )

    def on_mount(self) -> None:
        """Replace the startup cover only after two stable layout frames."""
        super().on_mount()
        self._directory_poll_timer = self.set_interval(
            DIRECTORY_POLL_INTERVAL_SECONDS,
            self._poll_directory_changes,
        )
        self._ui_heartbeat_timer = self.set_interval(
            UI_HEARTBEAT_INTERVAL_SECONDS, self._record_ui_heartbeat
        )
        self._start_hang_watchdog()
        self.call_after_refresh(self._stabilize_startup_frame)
        # A short fallback timer guarantees removal even when a terminal
        # coalesces the two startup refresh notifications into one frame.
        self.set_timer(0.02, self._finish_startup_frame)

    def _stabilize_startup_frame(self) -> None:
        """Force one complete redraw at the final terminal dimensions."""
        self.left.table.refresh(layout=True)
        self.right.table.refresh(layout=True)
        self.refresh(layout=True)
        self.call_after_refresh(self._finish_startup_frame)

    def _finish_startup_frame(self) -> None:
        """Remove the cover without hiding or reopening the terminal window."""
        try:
            cover = self.query_one("#startup_cover", Static)
            cover.display = False
            cover.remove()
        except Exception:
            pass
        self.active.table.focus()

    def _record_ui_heartbeat(self) -> None:
        self._ui_heartbeat = time.monotonic()

    @staticmethod
    def _hang_log_path() -> Path:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
        return base / "mdir-u" / "mdir-hang.log"

    def _start_hang_watchdog(self) -> None:
        if self._hang_watchdog_thread is not None:
            return
        self._hang_watchdog_stop.clear()
        self._hang_watchdog_thread = threading.Thread(
            target=self._watch_ui_heartbeat, name="mdir-u-ui-watchdog", daemon=True
        )
        self._hang_watchdog_thread.start()

    def _watch_ui_heartbeat(self) -> None:
        while not self._hang_watchdog_stop.wait(UI_HANG_WATCHDOG_INTERVAL_SECONDS):
            elapsed = time.monotonic() - self._ui_heartbeat
            if elapsed < UI_HANG_THRESHOLD_SECONDS:
                self._hang_reported = False
                continue
            if self._hang_reported:
                continue
            self._hang_reported = True
            try:
                path = self._hang_log_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as log:
                    log.write(f"\n=== mDIR-U UI hang {datetime.now().isoformat(timespec='seconds')} ({elapsed:.1f}s) ===\n")
                    faulthandler.dump_traceback(file=log, all_threads=True)
            except Exception:
                pass

    def on_app_blur(self, event: events.AppBlur) -> None:
        for pane in (self.left, self.right):
            pane.table.cancel_pointer_interaction()

    def _poll_directory_changes(self) -> None:
        """Check both directory timestamps without blocking the UI thread."""
        if self._directory_poll_running:
            return
        self._directory_poll_running = True
        paths = (
            ("left", self.left.current_path),
            ("right", self.right.current_path),
        )
        self._read_directory_tokens_in_background(paths)

    @work(thread=True, group="mdir-directory-poll")
    def _read_directory_tokens_in_background(
        self,
        paths: tuple[tuple[str, Path], tuple[str, Path]],
    ) -> None:
        snapshots = tuple(
            (
                side,
                path,
                LargeDirectoryFilePane._read_directory_change_token(path),
            )
            for side, path in paths
        )
        self.call_from_thread(self._finish_directory_poll, snapshots)

    def _finish_directory_poll(self, snapshots) -> None:
        self._directory_poll_running = False
        self._apply_directory_changes(snapshots)

    def _apply_directory_changes(
        self,
        snapshots: tuple[
            tuple[str, Path, tuple[int, int] | None],
            ...,
        ],
    ) -> None:
        """Refresh only panes whose displayed directory actually changed."""
        # Large copy/move/delete and ZIP jobs can change a directory hundreds
        # of times per second.  Rebuilding a 20,000-row table for intermediate
        # states wastes time and can make the UI appear stalled.  Each worker
        # performs one authoritative refresh when it finishes.
        if getattr(self, "_file_operation_busy", False) or getattr(
            self, "_archive_busy", False
        ):
            return
        refreshed: list[str] = []
        for side, observed_path, token in snapshots:
            pane = self.left if side == "left" else self.right
            if pane.current_path != observed_path:
                continue
            if not pane.directory_changed(token):
                continue

            selected = pane.selected_path()
            keep_name = selected.name if selected is not None else None
            previous_row = max(0, pane.table.cursor_row)
            pane.refresh_listing(keep_name=keep_name)

            if (
                keep_name is not None
                and selected not in pane.row_by_path
                and pane.table.row_count
            ):
                pane.table.move_cursor(
                    row=min(previous_row, pane.table.row_count - 1),
                    column=0,
                )
                pane.update_info()
            refreshed.append(side.title())

        if refreshed:
            self.set_status(
                "Auto-updated panel" +
                ("s: " if len(refreshed) > 1 else ": ") +
                ", ".join(refreshed)
            )

    def on_unmount(self) -> None:
        if self._directory_poll_timer is not None:
            self._directory_poll_timer.stop()
            self._directory_poll_timer = None
        if self._ui_heartbeat_timer is not None:
            self._ui_heartbeat_timer.stop()
            self._ui_heartbeat_timer = None
        self._hang_watchdog_stop.set()
        super().on_unmount()

    def set_active(self, side: str, *, focus_table: bool = True) -> None:
        """Change focus without recalculating unchanged drive information."""
        self.active_side = side
        self.left.set_active(side == "left")
        self.right.set_active(side == "right")
        self.active.reset_shift_selection_anchor()
        if focus_table:
            self.active.table.focus()

    def action_search(self) -> None:
        """Open advanced conditions and reveal the selected result."""
        source_side = self.active_side
        source_pane = self.active

        def result_selected(path: Path | None) -> None:
            if path is None:
                if self.ai_mode:
                    self.query_one("#ai_panel").focus_prompt()
                else:
                    self.set_active(source_side)
                self.set_status("Search cancelled.")
                return
            self._reveal_search_result(path, source_side)

        self.push_screen(
            AdvancedSearchScreen(
                source_pane.current_path,
                include_hidden_system=self.show_hidden_system,
            ),
            result_selected,
        )

    def action_folder_size(self) -> None:
        """Calculate recursive folder size without blocking the UI thread."""
        path = self.active.selected_path()
        if not path or not path.is_dir():
            self.set_status("Ctrl+G works on a directory.")
            return
        self.set_status(f"Calculating folder size: {path.name} ...")
        self._calculate_folder_size_in_background(path)

    @work(thread=True, exclusive=True, group="mdir-folder-size")
    def _calculate_folder_size_in_background(self, path: Path) -> None:
        size, count, truncated = legacy.safe_folder_size(path)
        self.call_from_thread(
            self._finish_folder_size,
            path,
            size,
            count,
            truncated,
        )

    def _finish_folder_size(
        self,
        path: Path,
        size: int,
        count: int,
        truncated: bool,
    ) -> None:
        extra = " (stopped early)" if truncated else ""
        self.set_status(
            f"{path.name}: {legacy.human_size(size)} "
            f"in {count:,} file(s){extra}"
        )

    def _reveal_search_result(self, path: Path, side: str) -> bool:
        """Open a result's containing directory and highlight its row."""
        try:
            target = path.resolve()
            if not target.exists():
                raise FileNotFoundError("the result no longer exists")
            containing_directory = target.parent
            if not containing_directory.is_dir():
                raise NotADirectoryError(
                    "the containing directory is unavailable"
                )
        except (OSError, RuntimeError) as exc:
            self.set_status(f"Search result is unavailable: {path} ({exc})")
            self.set_active(side)
            return False

        pane = self.left if side == "left" else self.right
        try:
            if (
                not self.show_hidden_system
                and legacy.is_hidden_or_system(target)
            ):
                self.show_hidden_system = True
                self.left.show_hidden_system = True
                self.right.show_hidden_system = True
                self.update_hidden_buttons()

            pane.current_path = containing_directory
            pane.marked.clear()
            pane.refresh_listing(keep_name=target.name)
            pane.update_summary()
            self.set_active(side)
            self._save_paths()
            self.update_drive_bar()
            self.set_status(f"Search result: {target}")
            return True
        except Exception as exc:
            self.set_status(f"Could not show search result: {target} ({exc})")
            self.set_active(side)
            return False

    def _cached_drive_usage_text(self, drive: str) -> str:
        now = time.monotonic()
        cached = self._drive_usage_cache.get(drive)
        if cached and now - cached[0] < DRIVE_USAGE_CACHE_SECONDS:
            return cached[1]
        value = legacy.drive_usage_text(drive)
        self._drive_usage_cache[drive] = (now, value)
        return value

    def update_drive_bar(self) -> None:
        """Update drive buttons while caching potentially slow capacity calls."""
        if os.name != "nt":
            return

        available = {drive.upper() for drive in self.available_drives}
        pane_specs = (
            (self.left, "ldrive_", "#left_drive_info"),
            (self.right, "rdrive_", "#right_drive_info"),
        )
        for pane, prefix, info_id in pane_specs:
            current = (pane.current_path.drive or "").upper()
            for index in range(26):
                letter = chr(ord("A") + index)
                drive = f"{letter}:"
                try:
                    button = self.query_one(
                        f"#{prefix}{letter.lower()}",
                        Button,
                    )
                    button.display = drive in available
                    button.set_class(
                        drive == current and drive in available,
                        "current-drive",
                    )
                except Exception:
                    pass

            if current and current in available:
                info = self._cached_drive_usage_text(current)
            elif current:
                info = f"{current}  drive unavailable"
            else:
                info = "No active drive"
            try:
                self.query_one(info_id, Static).update(info)
            except Exception:
                pass

    def refresh_drives(self) -> None:
        """Refresh drive state explicitly and invalidate capacity text."""
        self._drive_usage_cache.clear()
        super().refresh_drives()

    def auto_detect_drives(self) -> None:
        """Schedule a throttled drive scan outside the UI thread."""
        now = time.monotonic()
        if now - self._last_drive_poll < DRIVE_POLL_INTERVAL_SECONDS:
            return
        self._last_drive_poll = now
        self._scan_drives_in_background()

    @work(thread=True, exclusive=True, group="mdir-drive-scan")
    def _scan_drives_in_background(self) -> None:
        latest = legacy.list_windows_drives()
        self.call_from_thread(self._apply_detected_drives, latest)

    def _apply_detected_drives(self, latest: list[str]) -> None:
        if latest == self.available_drives:
            return

        previous = set(self.available_drives)
        current = set(latest)
        added = sorted(current - previous)
        removed = sorted(previous - current)
        self.available_drives = latest
        self._drive_usage_cache.clear()
        self._sync_drive_buttons()
        self._recover_removed_drive_panes()
        self.update_drive_bar()
        self.update_hidden_buttons()
        self._save_paths()

        messages: list[str] = []
        if added:
            messages.append("Connected: " + ", ".join(added))
        if removed:
            messages.append("Removed: " + ", ".join(removed))
        if messages:
            self.set_status(" | ".join(messages))
