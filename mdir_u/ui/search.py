from __future__ import annotations

import fnmatch
import os
import re
import stat as stat_module
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Input, Label, Select, Static
from textual.worker import Worker


FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4
CONTENT_SEARCH_MAX_BYTES = 16 * 1024 * 1024
DEFAULT_RESULT_LIMIT = 2_000


@dataclass(frozen=True)
class SearchRequest:
    """Validated file-search conditions collected by the search dialog."""

    root: Path
    name_pattern: str = "*"
    regular_expression: bool = False
    case_sensitive: bool = False
    include_subfolders: bool = True
    max_depth: int = -1
    include_files: bool = True
    include_directories: bool = True
    include_hidden_system: bool = False
    content_text: str = ""
    result_limit: int = DEFAULT_RESULT_LIMIT


@dataclass(frozen=True)
class SearchResult:
    """One file-system entry displayed in the result table."""

    path: Path
    is_directory: bool
    size: int
    modified: float


@dataclass(frozen=True)
class SearchOutcome:
    """Completed, truncated, or cancelled search state."""

    results: tuple[SearchResult, ...]
    scanned: int
    inaccessible: int
    elapsed_seconds: float
    truncated: bool = False
    cancelled: bool = False
    error: str = ""


class SearchValidationError(ValueError):
    """A user-facing search-condition validation error."""


def _compile_name_matcher(request: SearchRequest) -> Callable[[str], bool]:
    pattern = request.name_pattern.strip() or "*"
    if request.regular_expression:
        flags = 0 if request.case_sensitive else re.IGNORECASE
        try:
            expression = re.compile(pattern, flags)
        except re.error as exc:
            raise SearchValidationError(f"Invalid regular expression: {exc}") from exc
        return lambda name: expression.search(name) is not None

    patterns = [
        item.strip()
        for item in pattern.split(";")
        if item.strip()
    ] or ["*"]
    if not request.case_sensitive:
        patterns = [item.casefold() for item in patterns]

    def matches(name: str) -> bool:
        candidate = name if request.case_sensitive else name.casefold()
        for item in patterns:
            if item in {"*", "*.*"}:
                return True
            if any(character in item for character in "*?["):
                if fnmatch.fnmatchcase(candidate, item):
                    return True
            elif item in candidate:
                return True
        return False

    return matches


def _is_hidden_or_system(name: str, attributes: int) -> bool:
    if os.name == "nt":
        return bool(
            attributes & FILE_ATTRIBUTE_HIDDEN
            or attributes & FILE_ATTRIBUTE_SYSTEM
        )
    return name.startswith(".")


def _decode_searchable_text(data: bytes) -> str:
    """Decode common Windows text encodings without failing on mixed files."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            pass

    encodings = ["utf-8-sig", "cp949"]
    if b"\x00" in data:
        encodings.extend(("utf-16-le", "utf-16-be"))
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _file_contains(
    path: Path,
    file_size: int,
    needle: str,
    case_sensitive: bool,
) -> bool:
    if not needle:
        return True
    if file_size < 0 or file_size > CONTENT_SEARCH_MAX_BYTES:
        return False
    try:
        with path.open("rb") as source:
            data = source.read(CONTENT_SEARCH_MAX_BYTES + 1)
    except OSError:
        return False
    if len(data) > CONTENT_SEARCH_MAX_BYTES:
        return False

    text = _decode_searchable_text(data)
    if case_sensitive:
        return needle in text
    return needle.casefold() in text.casefold()


def search_files(
    request: SearchRequest,
    *,
    cancel_event: Optional[threading.Event] = None,
    progress: Optional[Callable[[int, int, Path], None]] = None,
) -> SearchOutcome:
    """Search iteratively so deep trees do not consume Python call-stack space."""
    started = time.perf_counter()
    root = request.root
    try:
        root = root.resolve()
        if not root.exists():
            raise FileNotFoundError("search location does not exist")
        if not root.is_dir():
            raise NotADirectoryError("search location is not a directory")
        name_matches = _compile_name_matcher(request)
    except (OSError, RuntimeError, SearchValidationError) as exc:
        return SearchOutcome(
            (),
            0,
            0,
            time.perf_counter() - started,
            error=str(exc),
        )

    results: list[SearchResult] = []
    scanned = 0
    inaccessible = 0
    truncated = False
    last_progress = started
    directories: list[tuple[Path, int]] = [(root, 0)]

    def report_progress(directory: Path, *, force: bool = False) -> None:
        nonlocal last_progress
        if progress is None:
            return
        now = time.perf_counter()
        if force or scanned % 250 == 0 or now - last_progress >= 0.15:
            progress(scanned, len(results), directory)
            last_progress = now

    while directories:
        if cancel_event is not None and cancel_event.is_set():
            return SearchOutcome(
                tuple(results),
                scanned,
                inaccessible,
                time.perf_counter() - started,
                cancelled=True,
            )

        current_directory, directory_depth = directories.pop()
        try:
            iterator = os.scandir(current_directory)
        except OSError:
            inaccessible += 1
            continue

        try:
            with iterator:
                for item in iterator:
                    if cancel_event is not None and cancel_event.is_set():
                        return SearchOutcome(
                            tuple(results),
                            scanned,
                            inaccessible,
                            time.perf_counter() - started,
                            cancelled=True,
                        )
                    try:
                        item_stat = item.stat(follow_symlinks=False)
                    except OSError:
                        inaccessible += 1
                        continue

                    is_directory = stat_module.S_ISDIR(item_stat.st_mode)
                    is_file = stat_module.S_ISREG(item_stat.st_mode)
                    if not is_directory and not is_file:
                        continue

                    scanned += 1
                    attributes = int(
                        getattr(item_stat, "st_file_attributes", 0)
                    )
                    hidden_or_system = _is_hidden_or_system(
                        item.name,
                        attributes,
                    )
                    if hidden_or_system and not request.include_hidden_system:
                        report_progress(current_directory)
                        continue

                    path = Path(item.path)
                    should_descend = (
                        is_directory
                        and request.include_subfolders
                        and (
                            request.max_depth < 0
                            or directory_depth < request.max_depth
                        )
                    )
                    if should_descend:
                        directories.append((path, directory_depth + 1))

                    type_matches = (
                        is_file and request.include_files
                    ) or (
                        is_directory and request.include_directories
                    )
                    if not type_matches or not name_matches(item.name):
                        report_progress(current_directory)
                        continue

                    if request.content_text:
                        if not is_file or not _file_contains(
                            path,
                            int(item_stat.st_size),
                            request.content_text,
                            request.case_sensitive,
                        ):
                            report_progress(current_directory)
                            continue

                    results.append(
                        SearchResult(
                            path=path,
                            is_directory=is_directory,
                            size=0 if is_directory else int(item_stat.st_size),
                            modified=float(item_stat.st_mtime),
                        )
                    )
                    if len(results) >= max(1, request.result_limit):
                        truncated = True
                        directories.clear()
                        break

                    report_progress(current_directory)
        except OSError:
            inaccessible += 1

    results.sort(
        key=lambda result: (
            str(result.path.parent).casefold(),
            result.path.name.casefold(),
        )
    )
    report_progress(root, force=True)
    return SearchOutcome(
        tuple(results),
        scanned,
        inaccessible,
        time.perf_counter() - started,
        truncated=truncated,
    )


def _human_size(size: int) -> str:
    value = float(max(0, size))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            if value >= 100:
                return f"{value:.0f} {unit}"
            if value >= 10:
                return f"{value:.1f} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{size} B"


class SearchResultsTable(DataTable):
    """Result table that opens a path with one click or the Enter key."""


class AdvancedSearchScreen(ModalScreen[Optional[Path]]):
    """Advanced search conditions and clickable results in one modal window."""

    BINDINGS = [
        Binding(
            "escape",
            "cancel_or_close",
            "Cancel search or close",
            show=False,
            priority=True,
        ),
    ]

    CSS = """
    AdvancedSearchScreen {
        align: center middle;
        background: #00000073;
    }

    #file_search_dialog {
        width: 94%;
        height: 92%;
        min-width: 72;
        min-height: 32;
        max-width: 170;
        max-height: 62;
        border: solid $primary;
        background: $surface;
        padding: 0 1;
    }

    #file_search_header {
        height: 1;
        min-height: 1;
        max-height: 1;
    }

    #file_search_title {
        width: 1fr;
        height: 1;
        color: $foreground;
        text-style: bold;
        text-wrap: nowrap;
    }

    #file_search_close_x {
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

    .search_row {
        height: 3;
        min-height: 3;
        align-vertical: middle;
    }

    .search_label {
        width: 27;
        min-width: 27;
        height: 3;
        content-align: left middle;
        color: $foreground;
        text-wrap: nowrap;
    }

    .search_row Input {
        width: 1fr;
        height: 3;
    }

    #search_use_pane {
        width: 15;
        min-width: 15;
        height: 3;
        margin-left: 1;
    }

    .search_options {
        height: 3;
        min-height: 3;
        align-vertical: middle;
    }

    .search_options Checkbox {
        width: auto;
        height: 3;
        margin-right: 2;
    }

    .option_label {
        width: auto;
        min-width: 8;
        height: 3;
        content-align: left middle;
        margin-right: 1;
        text-wrap: nowrap;
    }

    .search_options Select {
        width: 18;
        min-width: 14;
        height: 3;
        margin-right: 2;
    }

    #search_actions {
        height: 3;
        min-height: 3;
        align-horizontal: right;
    }

    #search_actions Button {
        min-width: 12;
        width: auto;
        height: 3;
        margin-left: 1;
    }

    #search_status {
        height: 1;
        min-height: 1;
        color: $warning;
        background: $panel;
        text-wrap: nowrap;
    }

    #search_results {
        height: 1fr;
        min-height: 6;
        background: $background;
        scrollbar-size: 1 1;
    }

    #search_results > .datatable--header {
        background: $surface-lighten-1;
        color: $foreground;
        text-style: bold;
    }

    #search_results > .datatable--cursor {
        background: $primary;
        color: $text-primary;
        text-style: bold;
    }

    #search_result_help {
        height: 1;
        min-height: 1;
        color: $text-muted;
        text-wrap: nowrap;
    }
    """

    DEPTH_CHOICES = (
        ("All levels", -1),
        ("1 subfolder level", 1),
        ("2 subfolder levels", 2),
        ("3 subfolder levels", 3),
        ("5 subfolder levels", 5),
        ("10 subfolder levels", 10),
    )
    LIMIT_CHOICES = (
        ("500 results", 500),
        ("1,000 results", 1_000),
        ("2,000 results", 2_000),
        ("5,000 results", 5_000),
        ("10,000 results", 10_000),
    )

    def __init__(
        self,
        initial_root: Path,
        *,
        include_hidden_system: bool = False,
    ) -> None:
        super().__init__()
        self.initial_root = initial_root
        self.initial_include_hidden_system = include_hidden_system
        self.results: list[SearchResult] = []
        self.cancel_event = threading.Event()
        self.search_worker: Optional[Worker[None]] = None
        self.search_running = False

    def compose(self) -> ComposeResult:
        with Vertical(id="file_search_dialog"):
            with Horizontal(id="file_search_header"):
                yield Label("Find Files", id="file_search_title")
                yield Button("X", id="file_search_close_x")
            with Horizontal(classes="search_row"):
                yield Label("File name / pattern:", classes="search_label")
                yield Input(
                    value="*",
                    placeholder="Examples: report; *.jpg; *.png",
                    id="search_name",
                )
            with Horizontal(classes="search_row"):
                yield Label("Search location:", classes="search_label")
                yield Input(value=str(self.initial_root), id="search_root")
                yield Button("Active pane", id="search_use_pane")
            with Horizontal(classes="search_options"):
                yield Checkbox(
                    "Regular expression",
                    False,
                    id="search_regex",
                )
                yield Checkbox(
                    "Case sensitive",
                    False,
                    id="search_case",
                )
                yield Checkbox(
                    "Include subfolders",
                    True,
                    id="search_subfolders",
                )
                yield Checkbox(
                    "Hidden/System",
                    self.initial_include_hidden_system,
                    id="search_hidden",
                )
            with Horizontal(classes="search_options"):
                yield Checkbox("Files", True, id="search_files")
                yield Checkbox("Directories", True, id="search_directories")
                yield Static("Depth:", classes="option_label")
                yield Select(
                    self.DEPTH_CHOICES,
                    value=-1,
                    allow_blank=False,
                    id="search_depth",
                )
                yield Static("Limit:", classes="option_label")
                yield Select(
                    self.LIMIT_CHOICES,
                    value=DEFAULT_RESULT_LIMIT,
                    allow_blank=False,
                    id="search_limit",
                )
            with Horizontal(classes="search_row"):
                yield Label(
                    "Text contains (<=16 MB):",
                    classes="search_label",
                )
                yield Input(
                    placeholder="Optional text inside files",
                    id="search_content",
                )
            with Horizontal(id="search_actions"):
                yield Button(
                    "Search",
                    id="search_start",
                    variant="primary",
                )
                yield Button("Stop", id="search_stop", disabled=True)
                yield Button("Open location", id="search_open", disabled=True)
                yield Button("Cancel", id="search_cancel")
            yield Static(
                "Enter conditions and press Search.",
                id="search_status",
            )
            yield SearchResultsTable(
                cursor_type="row",
                zebra_stripes=False,
                id="search_results",
            )
            yield Static(
                "Click a result or select it and press Enter to show its location. "
                "Esc/X/Cancel: close",
                id="search_result_help",
            )

    def on_mount(self) -> None:
        table = self.query_one("#search_results", SearchResultsTable)
        table.add_columns("Name", "Folder", "Type", "Size", "Modified")
        self.query_one("#search_name", Input).focus()

    def _set_controls_for_search(self, running: bool) -> None:
        self.search_running = running
        self.query_one("#search_start", Button).disabled = running
        self.query_one("#search_stop", Button).disabled = not running
        self.query_one("#search_open", Button).disabled = (
            running or not self.results
        )

    def _resolve_root(self, entered: str) -> Path:
        text = os.path.expandvars(entered.strip().strip('"'))
        if not text:
            raise SearchValidationError("Enter a search location.")
        root = Path(os.path.expanduser(text))
        if not root.is_absolute():
            root = self.initial_root / root
        try:
            root = root.resolve()
            if not root.exists():
                raise FileNotFoundError("location does not exist")
            if not root.is_dir():
                raise NotADirectoryError("location is not a directory")
        except (OSError, RuntimeError) as exc:
            raise SearchValidationError(
                f"Invalid search location: {entered} ({exc})"
            ) from exc
        return root

    def _collect_request(self) -> SearchRequest:
        root = self._resolve_root(
            self.query_one("#search_root", Input).value
        )
        include_files = self.query_one("#search_files", Checkbox).value
        include_directories = self.query_one(
            "#search_directories",
            Checkbox,
        ).value
        if not include_files and not include_directories:
            raise SearchValidationError(
                "Select Files, Directories, or both."
            )

        depth_value = self.query_one("#search_depth", Select).value
        limit_value = self.query_one("#search_limit", Select).value
        include_subfolders = self.query_one(
            "#search_subfolders",
            Checkbox,
        ).value
        request = SearchRequest(
            root=root,
            name_pattern=self.query_one("#search_name", Input).value,
            regular_expression=self.query_one(
                "#search_regex",
                Checkbox,
            ).value,
            case_sensitive=self.query_one(
                "#search_case",
                Checkbox,
            ).value,
            include_subfolders=include_subfolders,
            max_depth=(
                int(depth_value)
                if include_subfolders and depth_value is not Select.BLANK
                else 0
            ),
            include_files=include_files,
            include_directories=include_directories,
            include_hidden_system=self.query_one(
                "#search_hidden",
                Checkbox,
            ).value,
            content_text=self.query_one("#search_content", Input).value,
            result_limit=(
                int(limit_value)
                if limit_value is not Select.BLANK
                else DEFAULT_RESULT_LIMIT
            ),
        )
        _compile_name_matcher(request)
        return request

    @on(Checkbox.Changed, "#search_subfolders")
    def subfolders_changed(self, event: Checkbox.Changed) -> None:
        self.query_one("#search_depth", Select).disabled = not event.value

    @on(Button.Pressed, "#search_use_pane")
    def use_active_pane(self, event: Button.Pressed) -> None:
        event.stop()
        field = self.query_one("#search_root", Input)
        field.value = str(self.initial_root)
        field.focus()

    @on(Button.Pressed, "#search_start")
    def start_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self.start_search()

    @on(Input.Submitted, "#search_name")
    @on(Input.Submitted, "#search_root")
    @on(Input.Submitted, "#search_content")
    def conditions_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.start_search()

    def start_search(self) -> None:
        if self.search_running:
            return
        try:
            request = self._collect_request()
        except SearchValidationError as exc:
            self.app.notify(str(exc), title="Search conditions")
            self.query_one("#search_status", Static).update(str(exc))
            return

        self.cancel_event = threading.Event()
        self.results.clear()
        table = self.query_one("#search_results", SearchResultsTable)
        table.clear(columns=False)
        self._set_controls_for_search(True)
        self.query_one("#search_status", Static).update(
            f"Searching: {request.root}"
        )
        self.search_worker = self._run_search(request)

    def _report_progress(
        self,
        scanned: int,
        found: int,
        directory: Path,
    ) -> None:
        if not self.is_mounted or not self.search_running:
            return
        self.query_one("#search_status", Static).update(
            f"Searching... scanned {scanned:,}, found {found:,}  "
            f"[{directory}]"
        )

    def _thread_progress(
        self,
        scanned: int,
        found: int,
        directory: Path,
    ) -> None:
        try:
            self.app.call_from_thread(
                self._report_progress,
                scanned,
                found,
                directory,
            )
        except Exception:
            pass

    @work(
        thread=True,
        exclusive=True,
        group="advanced-file-search",
        exit_on_error=False,
    )
    def _run_search(self, request: SearchRequest) -> None:
        outcome = search_files(
            request,
            cancel_event=self.cancel_event,
            progress=self._thread_progress,
        )
        try:
            self.app.call_from_thread(self._finish_search, outcome)
        except Exception:
            pass

    def _finish_search(self, outcome: SearchOutcome) -> None:
        if not self.is_mounted:
            return
        self.results = list(outcome.results)
        table = self.query_one("#search_results", SearchResultsTable)
        table.clear(columns=False)
        rows = [
            (
                result.path.name,
                str(result.path.parent),
                "DIR"
                if result.is_directory
                else (
                    result.path.suffix.lower().lstrip(".").upper()
                    or "FILE"
                ),
                "<DIR>"
                if result.is_directory
                else _human_size(result.size),
                datetime.fromtimestamp(result.modified).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
            )
            for result in self.results
        ]
        if rows:
            table.add_rows(rows)
            table.move_cursor(row=0, column=0)
            table.focus()

        self._set_controls_for_search(False)
        if outcome.error:
            status = f"Search failed: {outcome.error}"
        elif outcome.cancelled:
            status = (
                f"Search stopped - {len(self.results):,} result(s), "
                f"{outcome.scanned:,} scanned"
            )
        else:
            status = (
                f"Completed - {len(self.results):,} result(s), "
                f"{outcome.scanned:,} scanned, "
                f"{outcome.inaccessible:,} inaccessible, "
                f"{outcome.elapsed_seconds:.2f}s"
            )
            if outcome.truncated:
                status += " - result limit reached"
        self.query_one("#search_status", Static).update(status)

    def _stop_search(self) -> None:
        if not self.search_running:
            return
        self.cancel_event.set()
        self.query_one("#search_status", Static).update(
            "Stopping search..."
        )
        self.query_one("#search_stop", Button).disabled = True

    @on(Button.Pressed, "#search_stop")
    def stop_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self._stop_search()

    def _selected_result(self) -> Optional[SearchResult]:
        table = self.query_one("#search_results", SearchResultsTable)
        row = table.cursor_row
        if 0 <= row < len(self.results):
            return self.results[row]
        return None

    def _open_result(self, row: Optional[int] = None) -> None:
        if row is not None:
            table = self.query_one("#search_results", SearchResultsTable)
            if table.is_valid_row_index(row):
                table.move_cursor(row=row, column=0)
        result = self._selected_result()
        if result is None:
            return
        self.dismiss(result.path)

    @on(DataTable.RowSelected, "#search_results")
    def result_entered(self, event: DataTable.RowSelected) -> None:
        self._open_result()
        event.stop()

    @on(Button.Pressed, "#search_open")
    def open_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self._open_result()

    def _close(self) -> None:
        self.cancel_event.set()
        self.dismiss(None)

    @on(Button.Pressed, "#search_cancel")
    @on(Button.Pressed, "#file_search_close_x")
    def close_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self._close()

    def action_cancel_or_close(self) -> None:
        if self.search_running:
            self._stop_search()
        else:
            self._close()

    def on_unmount(self) -> None:
        self.cancel_event.set()
