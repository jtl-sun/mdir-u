from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.text import Text
from textual import on, events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Label, Static

from .ui.inputs import ThinCursorInput as Input
from .platform_support import open_with_default_app


from . import __version__


VERSION = __version__
CONFIG_PATH = Path.home() / ".config" / "mdir-u" / "config.json"
LEGACY_CONFIG_PATH = Path.home() / ".mdir-u.json"
DEFAULT_COLUMN_WIDTHS = {
    "name": 52,
    "extension": 10,
    "size": 18,
    "modified": 22,
}
CURRENT_COLUMN_LAYOUT_VERSION = 2

COLUMN_MIN_WIDTHS = {
    "name": 12,
    "extension": 9,
    "size": 16,
    "modified": 21,
}

COLUMN_HARD_MIN_WIDTHS = {
    "name": 6,
    "extension": 4,
    "size": 10,
    "modified": 8,
}

COLUMN_ORDER = ("name", "extension", "size", "modified")
EXTENSION_GAP = "  "
SIZE_MODIFIED_GAP = "  "

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"
}

TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".ps1", ".bat", ".cmd", ".ini", ".cfg", ".conf",
    ".json", ".xml", ".yaml", ".yml", ".csv", ".log", ".html", ".htm",
    ".css", ".js", ".ts", ".c", ".cpp", ".h", ".hpp", ".java", ".sql"
}

PARENT_DIRECTORY_STYLE = "bold cyan"


def load_config_data() -> dict[str, object]:
    """Read current settings, falling back to the pre-2.17 filename."""
    path = CONFIG_PATH if CONFIG_PATH.exists() else LEGACY_CONFIG_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def display_file_title(path: Path, *, is_directory: bool | None = None) -> str:
    """Return the filename without its final extension for the Name column."""
    directory = path.is_dir() if is_directory is None else is_directory
    if directory or not path.suffix:
        return path.name
    return path.name[: -len(path.suffix)]


def display_extension(extension: str) -> str:
    """Indent extensions so filenames and extensions remain visually distinct."""
    normalized = extension.lstrip(".")
    return f"{EXTENSION_GAP}{normalized}" if normalized else ""


def human_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value):,} B"
            return f"{value:,.1f} {unit}" if value < 10 else f"{value:,.0f} {unit}"
        value /= 1024
    return f"{size:,} B"


def display_file_size(size: int) -> str:
    """Format an exact byte count for file-list Size columns."""
    return f"{max(0, int(size)):,}"


def right_aligned_size(value: str) -> Text:
    """Right-align a file size to the real edge of the Size column."""
    return Text(
        value,
        justify="right",
        no_wrap=True,
        overflow="crop",
        end="",
    )


def centered_directory_size() -> Text:
    """Center the directory marker within the Size column."""
    return Text(
        "<DIR>",
        justify="center",
        no_wrap=True,
        overflow="crop",
        end="",
    )


def display_modified_text(value: str) -> str:
    """Reserve a visible two-cell gutter before the Modified column."""
    return SIZE_MODIFIED_GAP + value


def fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def file_name_text(path: Path, marked: bool = False) -> Text:
    """Simple Total Commander-like coloring.

    - Directories: cyan
    - Executables / scripts: green
    - Normal files: light gray
    - Marked items: yellow
    """
    prefix = "* " if marked else "  "
    text = Text(prefix + display_file_title(path))

    if marked:
        text.stylize("bold bright_yellow")
        return text

    if path.is_dir():
        text.stylize("bold bright_cyan")
        return text

    ext = path.suffix.lower()
    if ext in {".exe", ".com", ".msi", ".bat", ".cmd", ".ps1"}:
        text.stylize("bright_green")
    else:
        text.stylize("bright_white")

    return text


def safe_folder_size(path: Path, max_files: int = 20000) -> tuple[int, int, bool]:
    """Return size, file_count, truncated. Stops early on very large trees."""
    total = 0
    count = 0
    truncated = False

    try:
        for root, _, files in os.walk(path):
            for name in files:
                count += 1
                if count > max_files:
                    truncated = True
                    return total, count - 1, truncated
                try:
                    total += (Path(root) / name).stat().st_size
                except OSError:
                    pass
    except OSError:
        pass

    return total, count, truncated


def list_windows_drives() -> list[str]:
    """Return currently usable Windows drive letters.

    Unlike GetLogicalDrives() alone, removable / optical drives are only
    returned when media is actually available. This prevents a physically
    removed USB drive from remaining in the toolbar.
    """
    if os.name != "nt":
        return []

    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        mask = kernel32.GetLogicalDrives()
        drives: list[str] = []

        # Windows GetDriveType values.
        DRIVE_REMOVABLE = 2
        DRIVE_FIXED = 3
        DRIVE_REMOTE = 4
        DRIVE_CDROM = 5
        DRIVE_RAMDISK = 6

        for index in range(26):
            if not (mask & (1 << index)):
                continue

            letter = chr(ord("A") + index)
            drive = f"{letter}:"
            root = drive + "\\"
            dtype = int(kernel32.GetDriveTypeW(root))

            if dtype in {DRIVE_FIXED, DRIVE_REMOTE, DRIVE_RAMDISK}:
                drives.append(drive)
                continue

            if dtype in {DRIVE_REMOVABLE, DRIVE_CDROM}:
                # A drive letter may remain registered even after media is
                # removed. disk_usage succeeds only while media is usable.
                try:
                    shutil.disk_usage(root)
                    drives.append(drive)
                except OSError:
                    pass

        return drives

    except Exception:
        # Fallback: include only roots whose capacity can actually be queried.
        drives = []
        for index in range(26):
            drive = f"{chr(ord('A') + index)}:"
            root = drive + "\\"
            try:
                shutil.disk_usage(root)
                drives.append(drive)
            except OSError:
                pass
        return drives


def drive_usage_text(drive: str) -> str:
    """Return Total Commander-style free/total information."""
    try:
        usage = shutil.disk_usage(drive + "\\")
        free_k = usage.free // 1024
        total_k = usage.total // 1024
        return f"{drive}  {free_k:,} k / {total_k:,} k (Free/Total)"
    except Exception:
        return f"{drive}  usage unavailable"


FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF


def windows_file_attributes(path: Path) -> int:
    """Return Windows file attributes, or 0 when unavailable."""
    if os.name != "nt":
        # On non-Windows, dot-files are treated as hidden below.
        return 0

    try:
        import ctypes
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs == INVALID_FILE_ATTRIBUTES:
            return 0
        return int(attrs)
    except Exception:
        return 0


def is_hidden_or_system(path: Path) -> bool:
    """True for Windows Hidden/System items.

    On non-Windows platforms, names beginning with '.' are treated as hidden.
    """
    if os.name == "nt":
        attrs = windows_file_attributes(path)
        return bool(
            attrs & FILE_ATTRIBUTE_HIDDEN
            or attrs & FILE_ATTRIBUTE_SYSTEM
        )

    return path.name.startswith(".")


class PromptScreen(ModalScreen[Optional[str]]):
    CSS = """
    PromptScreen { align: center middle; }

    #dialog {
        width: 72;
        height: 9;
        border: heavy #00aaff;
        background: #000000;
        padding: 1 2;
    }

    #prompt_label { height: 2; color: white; }
    #prompt_input { margin-top: 1; }
    #prompt_help { margin-top: 1; color: #aaaaaa; }
    """

    def __init__(self, title: str, initial: str = "") -> None:
        super().__init__()
        self.dialog_title = title
        self.initial = initial

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.dialog_title, id="prompt_label")
            yield Input(value=self.initial, id="prompt_input")
            yield Static("Enter = OK    Esc = Cancel", id="prompt_help")

    def on_mount(self) -> None:
        self.query_one("#prompt_input", Input).focus()

    @on(Input.Submitted)
    def submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def key_escape(self) -> None:
        self.dismiss(None)


class ColumnWidthScreen(ModalScreen[Optional[dict[str, int]]]):
    """Dialog for changing the visible width of all four file-list columns."""

    CSS = """
    ColumnWidthScreen { align: center middle; }

    #width_dialog {
        width: 66;
        height: 18;
        border: heavy #00aaff;
        background: #000000;
        padding: 1 2;
    }

    .width_label {
        height: 1;
        color: #dddddd;
        margin-top: 1;
    }

    .width_input {
        height: 3;
    }

    #width_help {
        height: 2;
        margin-top: 1;
        color: #aaaaaa;
    }
    """

    def __init__(self, widths: dict[str, int]) -> None:
        super().__init__()
        self.widths = dict(widths)

    def compose(self) -> ComposeResult:
        with Vertical(id="width_dialog"):
            yield Static("Column widths (terminal character cells)", id="prompt_label")

            yield Label("Name", classes="width_label")
            yield Input(str(self.widths["name"]), id="width_name", classes="width_input")

            yield Label("Extension", classes="width_label")
            yield Input(str(self.widths["extension"]), id="width_extension", classes="width_input")

            yield Label("Size", classes="width_label")
            yield Input(str(self.widths["size"]), id="width_size", classes="width_input")

            yield Label("Modified", classes="width_label")
            yield Input(str(self.widths["modified"]), id="width_modified", classes="width_input")

            yield Static(
                "Tab = next field    Enter = Apply    Esc = Cancel",
                id="width_help",
            )

    def on_mount(self) -> None:
        self.query_one("#width_name", Input).focus()

    def _collect(self) -> Optional[dict[str, int]]:
        values: dict[str, int] = {}
        limits = {
            "name": (12, 120),
            "extension": (5, 30),
            "size": (10, 24),
            "modified": (21, 32),
        }

        for key in ("name", "extension", "size", "modified"):
            raw = self.query_one(f"#width_{key}", Input).value.strip()
            try:
                value = int(raw)
            except ValueError:
                return None

            lo, hi = limits[key]
            values[key] = max(lo, min(hi, value))

        return values

    @on(Input.Submitted)
    def submitted(self, event: Input.Submitted) -> None:
        values = self._collect()
        if values is not None:
            self.dismiss(values)

    def key_escape(self) -> None:
        self.dismiss(None)


class ConfirmScreen(ModalScreen[bool]):
    CSS = """
    ConfirmScreen { align: center middle; }

    #confirm {
        width: 74;
        height: 10;
        border: heavy #ffcc00;
        background: #000000;
        padding: 1 2;
    }

    #confirm_text { color: white; height: 5; }
    #confirm_help { color: #aaaaaa; }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm"):
            yield Static(self.message, id="confirm_text")
            yield Static("Y = Yes    N / Esc = No", id="confirm_help")

    def key_y(self) -> None:
        self.dismiss(True)

    def key_n(self) -> None:
        self.dismiss(False)

    def key_escape(self) -> None:
        self.dismiss(False)


class PropertiesScreen(ModalScreen[None]):
    CSS = """
    PropertiesScreen { align: center middle; }

    #prop_box {
        width: 84;
        height: 18;
        border: heavy #00aaff;
        background: black;
        padding: 1 2;
    }

    #prop_title { height: 2; color: #00ffff; text-style: bold; }
    #prop_text { height: 1fr; color: white; }
    #prop_help { height: 1; color: #aaaaaa; }
    """

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    def compose(self) -> ComposeResult:
        yield from self._content()

    def _content(self) -> ComposeResult:
        p = self.path
        try:
            stat = p.stat()
            kind = "Directory" if p.is_dir() else "File"
            ext = p.suffix or "(none)"
            size_text = "<DIR>" if p.is_dir() else human_size(stat.st_size)
            created = fmt_time(stat.st_ctime)
            modified = fmt_time(stat.st_mtime)
            accessed = fmt_time(stat.st_atime)
            readonly = "Yes" if not os.access(p, os.W_OK) else "No"
        except OSError as exc:
            kind = "Unknown"
            ext = "(unknown)"
            size_text = "(unknown)"
            created = modified = accessed = "(unknown)"
            readonly = "(unknown)"
            err = str(exc)
        else:
            err = ""

        lines = [
            f"Name       : {p.name}",
            f"Type       : {kind}",
            f"Extension  : {ext}",
            f"Size       : {size_text}",
            f"Modified   : {modified}",
            f"Created    : {created}",
            f"Accessed   : {accessed}",
            f"Read-only  : {readonly}",
            f"Path       : {p}",
        ]
        if err:
            lines.append(f"Error      : {err}")

        with Vertical(id="prop_box"):
            yield Static("File Properties", id="prop_title")
            yield Static("\n".join(lines), id="prop_text")
            yield Static("Esc = Close", id="prop_help")

    def key_escape(self) -> None:
        self.dismiss(None)


class ViewerScreen(ModalScreen[None]):
    CSS = """
    ViewerScreen { align: center middle; }

    #viewer_box {
        width: 94%;
        height: 90%;
        border: heavy #00aaff;
        background: black;
        padding: 1;
    }

    #viewer_title { height: 2; color: #00ffff; }
    #viewer_text {
        height: 1fr;
        overflow-y: auto;
        overflow-x: auto;
        color: white;
    }
    #viewer_help { height: 1; color: #aaaaaa; }
    """

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    def compose(self) -> ComposeResult:
        content = self._make_content()
        with Vertical(id="viewer_box"):
            yield Static(str(self.path), id="viewer_title")
            yield Static(content, id="viewer_text")
            yield Static("Esc / F3 = Close", id="viewer_help")

    def _make_content(self):
        if self.path.suffix.lower() in IMAGE_EXTENSIONS:
            return self._image_preview()
        return self._read_text()

    def _read_text(self) -> str:
        try:
            if self.path.stat().st_size > 3 * 1024 * 1024:
                return "[File is larger than 3 MB. Use F4/Edit or Enter/Open instead.]"
            try:
                return self.path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return self.path.read_text(encoding="cp949")
        except Exception as exc:
            return f"[Unable to read file: {exc}]"

    def _image_preview(self):
        try:
            from PIL import Image
        except ImportError:
            return (
                "[Image preview requires Pillow]\n\n"
                "PowerShell:\n"
                "    pip install pillow\n\n"
                "Enter still opens the image with the Windows default viewer."
            )

        try:
            img = Image.open(self.path).convert("RGB")
            original_size = img.size

            max_w, max_h = 64, 42
            scale = min(max_w / img.width, (max_h * 2) / img.height, 1.0)
            new_w = max(1, int(img.width * scale))
            new_h = max(1, int(img.height * scale))
            if new_h % 2:
                new_h += 1

            img = img.resize((new_w, new_h))
            pixels = img.load()

            out = Text()
            out.append(
                f"{self.path.name}  {original_size[0]} x {original_size[1]} px\n\n",
                style="bold cyan",
            )

            for y in range(0, new_h, 2):
                for x in range(new_w):
                    top = pixels[x, y]
                    bottom = pixels[x, min(y + 1, new_h - 1)]
                    out.append(
                        "▀",
                        style=(
                            f"rgb({top[0]},{top[1]},{top[2]}) "
                            f"on rgb({bottom[0]},{bottom[1]},{bottom[2]})"
                        ),
                    )
                out.append("\n")
            return out
        except Exception as exc:
            return f"[Unable to preview image: {exc}]"

    def key_escape(self) -> None:
        self.dismiss(None)

    def key_f3(self) -> None:
        self.dismiss(None)


class MDirDataTable(DataTable):
    """Total Commander-style mouse behavior with accurate draggable separators."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("cell_padding", 0)
        super().__init__(*args, **kwargs)

        self._right_dragging = False
        self._drag_rows_seen: set[int] = set()
        self._right_drag_last_row: Optional[int] = None
        self._right_drag_scroll_direction = 0
        self._right_drag_scroll_timer = None

        self._resize_key: Optional[str] = None
        self._resize_next_key: Optional[str] = None
        self._resize_start_x = 0
        self._resize_start_width = 0
        self._resize_next_start_width = 0
        self._resize_snapshot: dict[str, int] = {}
        self._shift_mouse_click_pending = False

    @staticmethod
    def _read_shift_pressed(event: events.MouseEvent) -> bool:
        """Read Shift from the terminal mouse event on Linux."""
        return bool(getattr(event, "shift", False))

    def _shift_click_active(self, event: events.MouseEvent) -> bool:
        """Keep the MouseDown Shift result available through Click."""
        return self._shift_mouse_click_pending or self._read_shift_pressed(
            event
        )

    def _hover_row(self) -> Optional[int]:
        try:
            coordinate = self.hover_coordinate
            row = int(coordinate.row)
            if 0 <= row < self.row_count:
                return row
        except Exception:
            pass
        return None

    def _event_row(self, event: events.MouseEvent) -> Optional[int]:
        """Resolve the row attached to this event before using hover fallback."""
        try:
            row = int(event.style.meta.get("row", -1))
            if 0 <= row < self.row_count:
                return row
        except Exception:
            pass
        return self._hover_row()

    def _pane(self):
        parent = self.parent
        return parent if isinstance(parent, FilePane) else None

    def _activate_pane(self) -> None:
        pane = self._pane()
        if pane is None:
            return
        try:
            app = self.app
            if isinstance(app, MDir):
                app.set_active("left" if pane.id == "left" else "right")
        except Exception:
            pass

    def _toggle_hovered_row(self) -> None:
        row = self._hover_row()
        self._toggle_row(row)

    def _toggle_row(self, row: Optional[int]) -> None:
        pane = self._pane()
        if row is None or pane is None:
            return

        self.move_cursor(row=row, column=0)
        self._activate_pane()

        if 0 <= row < len(pane.entries):
            path = pane.entries[row]
            if path is not None:
                pane.toggle_mark_path(path)

    def _toggle_drag_range_to(self, row: int) -> None:
        """Toggle every crossed row, even when fast mouse motion skips events."""
        if self._right_drag_last_row is None:
            candidates = (row,)
        else:
            step = 1 if row >= self._right_drag_last_row else -1
            candidates = range(self._right_drag_last_row + step, row + step, step)

        for candidate in candidates:
            if candidate in self._drag_rows_seen:
                continue
            self._drag_rows_seen.add(candidate)
            self._toggle_row(candidate)
        self._right_drag_last_row = row

    def _set_right_drag_auto_scroll(self, direction: int) -> None:
        """Start or pause edge scrolling while a right-button drag is active."""
        direction = -1 if direction < 0 else 1 if direction > 0 else 0
        self._right_drag_scroll_direction = direction

        timer = self._right_drag_scroll_timer
        if not self._right_dragging or direction == 0:
            if timer is not None:
                timer.pause()
            return

        if timer is None:
            self._right_drag_scroll_timer = self.set_interval(
                0.055,
                self._right_drag_auto_scroll_tick,
            )
        else:
            timer.resume()

    def _update_right_drag_auto_scroll(self, mouse_y: int) -> None:
        """Enable scrolling when the captured pointer reaches either edge."""
        height = max(1, int(self.size.height))
        top_edge = max(1, int(self.header_height))
        bottom_edge = max(top_edge + 1, height - 2)

        if mouse_y <= top_edge:
            self._set_right_drag_auto_scroll(-1)
        elif mouse_y >= bottom_edge:
            self._set_right_drag_auto_scroll(1)
        else:
            self._set_right_drag_auto_scroll(0)

    def _right_drag_auto_scroll_tick(self) -> None:
        """Advance one row and keep selection continuous across pages."""
        direction = self._right_drag_scroll_direction
        if not self._right_dragging or direction == 0 or self.row_count <= 0:
            self._set_right_drag_auto_scroll(0)
            return

        current = self._right_drag_last_row
        if current is None:
            try:
                current = int(self.cursor_row)
            except Exception:
                current = 0 if direction > 0 else self.row_count - 1

        target = max(0, min(self.row_count - 1, current + direction))
        if target == current:
            self._set_right_drag_auto_scroll(0)
            return

        self._toggle_drag_range_to(target)
        self.move_cursor(row=target, column=0, animate=False, scroll=True)

    def end_right_drag(self) -> None:
        """Clear right-drag state and stop any pending edge scroll."""
        self._right_dragging = False
        self._right_drag_scroll_direction = 0
        if self._right_drag_scroll_timer is not None:
            self._right_drag_scroll_timer.pause()
        self._drag_rows_seen.clear()
        self._right_drag_last_row = None

    def cancel_pointer_interaction(self) -> None:
        """Release stale mouse state when the terminal loses focus."""
        self._resize_key = None
        self._resize_next_key = None
        self._resize_snapshot.clear()
        self.end_right_drag()
        try:
            self.release_mouse()
        except Exception:
            pass

    def _render_boundaries(self) -> list[tuple[str, int]]:
        """Return actual rendered right-edge x positions for all columns.

        Textual's Column.get_render_width() includes the width the DataTable
        really uses to render the column, so hit-testing stays aligned with the
        visible separators.
        """
        boundaries: list[tuple[str, int]] = []
        x = 0

        try:
            ordered = list(self.ordered_columns)
            for index, column in enumerate(ordered):
                x += int(column.get_render_width(self))
                if index < len(COLUMN_ORDER):
                    boundaries.append((COLUMN_ORDER[index], x - 1))
        except Exception:
            pane = self._pane()
            if pane is None:
                return []
            x = 0
            for key in COLUMN_ORDER:
                x += int(pane.display_column_widths[key])
                boundaries.append((key, x - 1))

        return boundaries

    def _content_mouse_x(self, event_x: int) -> int:
        """Convert visible mouse x to scrolled table-content x."""
        try:
            return int(event_x) + int(self.scroll_offset.x)
        except Exception:
            return int(event_x)

    def _header_resize_hit(self, x: int, y: int) -> Optional[str]:
        if y < 0 or y >= max(1, int(self.header_height)):
            return None

        content_x = self._content_mouse_x(x)

        # Two-cell hit zone on either side of the actual rendered boundary.
        for key, boundary_x in self._render_boundaries():
            if abs(content_x - boundary_x) <= 2:
                return key

        return None

    def _prepare_left_click_row(
        self,
        clicked_row: int,
        previous_cursor_row: int,
    ) -> None:
        """Allow subclasses to classify a row before it becomes selected."""

    async def on_mouse_down(self, event: events.MouseDown) -> None:
        shift_pressed = self._read_shift_pressed(event)
        if event.button in {1, 3}:
            self._shift_mouse_click_pending = shift_pressed

        # Anchor the cursor to the rendered row before focus can scroll the
        # old keyboard cursor back into view on another page.
        if event.button == 1 and not shift_pressed:
            try:
                clicked_row = int(event.style.meta.get("row", -1))
            except Exception:
                clicked_row = -1
            if 0 <= clicked_row < self.row_count:
                try:
                    previous_cursor_row = int(self.cursor_row)
                except Exception:
                    previous_cursor_row = -1
                self._prepare_left_click_row(
                    clicked_row,
                    previous_cursor_row,
                )
                self.move_cursor(
                    row=clicked_row,
                    column=0,
                    animate=False,
                    scroll=False,
                )

        # Empty table space has no row metadata. Activate the pane before
        # hit-testing so the complete list surface switches panes.
        if event.button in {1, 3}:
            self._activate_pane()

        # A right click establishes the range anchor. Shift+left-click extends
        # the range; Shift+right-click remains a normal right-button action.
        if event.button == 1 and shift_pressed:
            row = self._event_row(event)
            pane = self._pane()
            if row is not None and pane is not None:
                pane.select_range_to(row)
                event.stop()
                return

        if event.button == 1:
            key = self._header_resize_hit(event.x, event.y)
            if key is not None:
                pane = self._pane()
                if pane is not None:
                    index = COLUMN_ORDER.index(key)
                    next_key = (
                        COLUMN_ORDER[index + 1]
                        if index + 1 < len(COLUMN_ORDER)
                        else None
                    )

                    self._resize_key = key
                    self._resize_next_key = next_key
                    self._resize_start_x = self._content_mouse_x(event.x)
                    self._resize_snapshot = dict(pane.column_widths)
                    self._resize_start_width = int(pane.column_widths[key])
                    self._resize_next_start_width = (
                        int(pane.column_widths[next_key])
                        if next_key is not None
                        else 0
                    )

                    self._activate_pane()

                    try:
                        self.capture_mouse()
                    except Exception:
                        pass

                    try:
                        app = self.app
                        if isinstance(app, MDir):
                            if next_key is None:
                                app.set_status(
                                    f"Resize {key.title()} right edge"
                                )
                            else:
                                app.set_status(
                                    f"Resize boundary: {key.title()} | "
                                    f"{next_key.title()}"
                                )
                    except Exception:
                        pass

                    event.stop()
                    return

        if event.button == 3:
            self._right_dragging = True
            self._drag_rows_seen.clear()
            self._right_drag_last_row = None
            self._set_right_drag_auto_scroll(0)

            try:
                self.capture_mouse()
            except Exception:
                pass

            row = self._event_row(event)
            if row is not None:
                self._toggle_drag_range_to(row)
                pane = self._pane()
                if pane is not None:
                    pane.set_shift_selection_anchor(row)

            event.stop()

    async def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._resize_key is not None:
            pane = self._pane()
            if pane is None:
                return

            key = self._resize_key
            next_key = self._resize_next_key
            current_x = self._content_mouse_x(event.x)
            raw_delta = current_x - self._resize_start_x

            widths = dict(self._resize_snapshot)

            if next_key is not None:
                # Move a boundary, rather than independently stretching one
                # column. This keeps the divider exactly under the mouse.
                left_min = COLUMN_HARD_MIN_WIDTHS[key]
                right_min = COLUMN_HARD_MIN_WIDTHS[next_key]

                min_delta = left_min - self._resize_start_width
                max_delta = self._resize_next_start_width - right_min
                delta = max(min_delta, min(max_delta, raw_delta))

                widths[key] = self._resize_start_width + delta
                widths[next_key] = self._resize_next_start_width - delta
            else:
                # The final right edge changes only the Modified column.
                new_width = max(
                    COLUMN_HARD_MIN_WIDTHS[key],
                    self._resize_start_width + raw_delta,
                )
                widths[key] = new_width

            # Preview only in the pane being dragged. This avoids the other
            # pane's auto-fit logic fighting the mouse during the drag.
            pane.set_column_widths(widths)

            try:
                app = self.app
                if isinstance(app, MDir):
                    app.column_widths = dict(widths)
                    app.set_status(
                        "Widths: "
                        f"Name {widths['name']} | "
                        f"Ext {widths['extension']} | "
                        f"Size {widths['size']} | "
                        f"Modified {widths['modified']}"
                    )
            except Exception:
                pass

            event.stop()
            return

        if not self._right_dragging:
            return

        self._update_right_drag_auto_scroll(event.y)
        row = self._event_row(event)
        if row is None:
            event.stop()
            return

        self._toggle_drag_range_to(row)
        event.stop()

    async def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._resize_key is not None and event.button == 1:
            self._resize_key = None
            self._resize_next_key = None

            try:
                self.release_mouse()
            except Exception:
                pass

            try:
                app = self.app
                if isinstance(app, MDir):
                    # Synchronize the final widths to both panes only after the
                    # drag finishes, then save them.
                    app.apply_column_widths(
                        dict(app.column_widths),
                        save=True,
                    )
                    app.set_status(
                        "Column widths saved. Drag any visible │ separator."
                    )
            except Exception:
                pass

            event.stop()
            return

        if self._right_dragging and event.button == 3:
            self.end_right_drag()
            try:
                self.release_mouse()
            except Exception:
                pass
            event.stop()

    async def on_key(self, event: events.Key) -> None:
        pane = self._pane()

        if event.key in {"up", "down", "home", "end", "pageup", "pagedown"}:
            if pane is not None:
                pane.reset_shift_selection_anchor()

        if event.key == "enter":
            if pane is not None:
                self._activate_pane()
                try:
                    app = self.app
                    if isinstance(app, MDir):
                        app._open_from_pane(pane)
                        event.stop()
                        return
                except Exception:
                    pass

    async def on_click(self, event: events.Click) -> None:
        if event.button == 3:
            event.stop()
            return

        if event.button == 1 and self._shift_click_active(event):
            event.stop()
            return

        if event.button == 1 and getattr(event, "chain", 1) >= 2:
            pane = self._pane()
            if pane is not None:
                self._activate_pane()
                try:
                    app = self.app
                    if isinstance(app, MDir):
                        app._open_from_pane(pane)
                except Exception:
                    pass
            event.stop()


class FilePane(Vertical):
    DEFAULT_CSS = """
    FilePane {
        width: 1fr;
        height: 1fr;
        border: round #555555;
        background: black;
    }

    FilePane.active { border: heavy #00aaff; }

    .pane_path {
        height: 1;
        background: #0000aa;
        color: white;
        padding-left: 1;
    }

    .pane_info {
        height: 4;
        min-height: 4;
        dock: bottom;
        border-top: solid #444444;
        background: #080808;
        color: #dddddd;
        padding: 0 1;
    }

    .pane_summary {
        height: 1;
        min-height: 1;
        max-height: 1;
        background: #202020;
        color: #ffffff;
        text-style: bold;
        padding: 0 1;
    }

    DataTable {
        height: 1fr;
        background: black;
        color: white;
    }

    DataTable > .datatable--header {
        background: #0000cc;
        color: white;
        text-style: bold;
    }

    DataTable > .datatable--cursor {
        background: #12659a;
        color: white;
        text-style: bold;
    }

    DataTable > .datatable--hover {
        background: #303030;
    }
    """

    def __init__(
        self,
        pane_id: str,
        start_path: Path,
        column_widths: Optional[dict[str, int]] = None,
        show_hidden_system: bool = False,
    ) -> None:
        super().__init__(id=pane_id)
        self.current_path = start_path
        self.entries: list[Optional[Path]] = []
        self.marked: set[Path] = set()
        self.sort_mode = "name"
        self.sort_reverse = False
        self.show_hidden_system = bool(show_hidden_system)

        # Shift+Arrow range-selection state.
        self.shift_anchor_row: Optional[int] = None
        self.shift_base_marked: set[Path] = set()

        self.column_widths = dict(column_widths or DEFAULT_COLUMN_WIDTHS)
        self.display_column_widths = dict(self.column_widths)
        self._last_available_width = 0

    def compose(self) -> ComposeResult:
        yield Static("", classes="pane_path")
        table = MDirDataTable(cursor_type="row", zebra_stripes=False)
        self._add_columns(table)
        yield table
        yield Static("", classes="pane_info")
        yield Static("", classes="pane_summary")

    async def on_mouse_down(self, event: events.MouseDown) -> None:
        """Activate this side when any non-table area of the pane is clicked."""
        if event.button not in {1, 3}:
            return
        try:
            app = self.app
            if isinstance(app, MDir):
                side = "left" if self.id == "left" else "right"
                target = getattr(event, "widget", None)
                app.set_active(side, focus_table=not isinstance(target, Input))
        except Exception:
            pass

    @staticmethod
    def _fit_widths(
        preferred: dict[str, int],
        available: int,
    ) -> dict[str, int]:
        available = max(1, int(available))
        result = {key: max(1, int(preferred[key])) for key in COLUMN_ORDER}

        if sum(result.values()) <= available:
            return result

        for minimums in (COLUMN_MIN_WIDTHS, COLUMN_HARD_MIN_WIDTHS):
            excess = sum(result.values()) - available

            while excess > 0:
                changed = False

                for key in ("name", "modified", "extension", "size"):
                    minimum = minimums[key]
                    if result[key] > minimum:
                        result[key] -= 1
                        excess -= 1
                        changed = True

                        if excess <= 0:
                            return result

                if not changed:
                    break

        excess = sum(result.values()) - available

        while excess > 0:
            changed = False

            for key in ("name", "modified", "extension", "size"):
                if result[key] > 1:
                    result[key] -= 1
                    excess -= 1
                    changed = True

                    if excess <= 0:
                        return result

            if not changed:
                break

        return result

    def _effective_widths(self) -> dict[str, int]:
        available = self._last_available_width or max(1, self.size.width - 2)
        return self._fit_widths(self.column_widths, available)

    @staticmethod
    def _header_label(title: str, width: int) -> str:
        """Place the separator on the real right edge of the column."""
        width = max(1, int(width))

        if width == 1:
            return "│"

        visible_title = title[: max(0, width - 2)]
        return visible_title.ljust(width - 1) + "│"

    @staticmethod
    def _centered_header_label(title: str, width: int) -> str:
        """Center a title while retaining the right-edge separator."""
        width = max(1, int(width))
        if width == 1:
            return "│"
        visible_title = title[: max(0, width - 2)]
        return visible_title.center(width - 1) + "│"

    def _column_header_title(self, key: str) -> str:
        titles = {
            "name": "Name",
            "extension": "Ext",
            "size": "Size",
            "modified": "Modified",
        }
        mode_by_key = {
            "name": "name",
            "extension": "ext",
            "size": "size",
            "modified": "modified",
        }
        title = titles[key]
        if self.sort_mode == mode_by_key[key]:
            arrow = "▼" if self.sort_reverse else "▲"
            return f"{arrow} {title}"
        return title

    def _update_sort_headers(self) -> None:
        """Refresh header labels after the sort field or direction changes."""
        try:
            table = self.table
            for key in COLUMN_ORDER:
                title = self._column_header_title(key)
                width = self.display_column_widths[key]
                builder = (
                    self._centered_header_label
                    if key in {"extension", "size", "modified"}
                    else self._header_label
                )
                table.columns[key].label = Text(builder(title, width))
            table.clear_cached_dimensions()
            table._clear_caches()
            table.refresh()
        except Exception:
            pass

    def _add_columns(self, table: MDirDataTable) -> None:
        widths = self.display_column_widths

        table.add_column(
            self._header_label(
                self._column_header_title("name"), widths["name"]
            ),
            width=widths["name"],
            key="name",
        )
        table.add_column(
            self._centered_header_label(
                self._column_header_title("extension"),
                widths["extension"],
            ),
            width=widths["extension"],
            key="extension",
        )
        table.add_column(
            self._centered_header_label(
                self._column_header_title("size"), widths["size"]
            ),
            width=widths["size"],
            key="size",
        )
        table.add_column(
            self._centered_header_label(
                self._column_header_title("modified"), widths["modified"]
            ),
            width=widths["modified"],
            key="modified",
        )

    def _rebuild_columns(self, keep_name: Optional[str] = None) -> None:
        self.table.clear(columns=True)
        self._add_columns(self.table)
        self.refresh_listing(keep_name=keep_name)

    def set_column_widths(self, widths: dict[str, int]) -> None:
        keep = self.selected_path()
        keep_name = keep.name if keep else None

        self.column_widths = dict(widths)
        new_display = self._effective_widths()

        if new_display != self.display_column_widths:
            self.display_column_widths = new_display
            self._rebuild_columns(keep_name=keep_name)
        else:
            self.refresh_listing(keep_name=keep_name)

    def on_mount(self) -> None:
        self._last_available_width = max(1, self.size.width - 2)
        self.display_column_widths = self._effective_widths()
        self._rebuild_columns()

    def on_resize(self, event: events.Resize) -> None:
        available = max(1, int(event.size.width) - 2)

        if available == self._last_available_width:
            return

        self._last_available_width = available
        new_display = self._effective_widths()

        if new_display == self.display_column_widths:
            return

        keep = self.selected_path()
        keep_name = keep.name if keep else None

        self.display_column_widths = new_display
        self._rebuild_columns(keep_name=keep_name)

    @property
    def table(self) -> MDirDataTable:
        return self.query_one(DataTable)

    def set_active(self, active: bool) -> None:
        self.set_class(active, "active")

    def _sort_key(self, path: Path):
        try:
            stat = path.stat()

            if self.sort_mode == "name":
                return path.name.lower()

            if self.sort_mode == "ext":
                return (path.suffix.lower().lstrip("."), path.name.lower())

            if self.sort_mode == "size":
                # Directories stay together; files sort by actual byte size.
                return (stat.st_size, path.name.lower())

            if self.sort_mode == "modified":
                return (stat.st_mtime, path.name.lower())

        except OSError:
            pass

        return path.name.lower()

    def set_sort(self, mode: str) -> None:
        if self.sort_mode == mode:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_mode = mode
            self.sort_reverse = False
        self._update_sort_headers()
        current = self.selected_path()
        self.refresh_listing(keep_name=current.name if current else None)

    def _update_path_bar(self, text: str) -> None:
        """Update either the legacy label or an editable path input."""
        path_widget = self.query_one(".pane_path")
        if isinstance(path_widget, Input):
            path_widget.value = str(self.current_path)
        else:
            path_widget.update(text)

    def refresh_listing(self, keep_name: Optional[str] = None) -> None:
        arrow = "▼" if self.sort_reverse else "▲"
        self._update_path_bar(
            f"{self.current_path}   [Sort: {self.sort_mode.upper()} {arrow}]"
        )

        self.table.clear(columns=False)
        self.entries.clear()

        if self.current_path.parent != self.current_path:
            self.table.add_row(
                Text("..", style=PARENT_DIRECTORY_STYLE),
                "",
                centered_directory_size(),
                "",
            )
            self.entries.append(None)

        try:
            items = list(self.current_path.iterdir())
        except (PermissionError, OSError) as exc:
            self.query_one(".pane_info", Static).update(f"Access error: {exc}")
            return

        if not self.show_hidden_system:
            items = [p for p in items if not is_hidden_or_system(p)]

        dirs = [p for p in items if p.is_dir()]
        files = [p for p in items if p.is_file()]

        dirs.sort(key=self._sort_key, reverse=self.sort_reverse)
        files.sort(key=self._sort_key, reverse=self.sort_reverse)

        for path in [*dirs, *files]:
            try:
                stat = path.stat()
                name = file_name_text(path, path in self.marked)
                extension = (
                    ""
                    if path.is_dir()
                    else display_extension(path.suffix.lower())
                )
                size = (
                    centered_directory_size()
                    if path.is_dir()
                    else right_aligned_size(display_file_size(stat.st_size))
                )
                self.table.add_row(
                    name,
                    extension,
                    size,
                    display_modified_text(fmt_time(stat.st_mtime)),
                )
                self.entries.append(path)
            except OSError:
                continue

        if self.table.row_count:
            target_row = 0
            if keep_name:
                for i, entry in enumerate(self.entries):
                    if entry is not None and entry.name == keep_name:
                        target_row = i
                        break
            self.table.move_cursor(row=target_row, column=0)

        self.update_info()

    def set_hidden_system_visibility(self, show: bool) -> None:
        """Show or hide Hidden/System items in this pane."""
        self.show_hidden_system = bool(show)
        self.marked = {
            p for p in self.marked
            if p.exists() and (show or not is_hidden_or_system(p))
        }
        self.refresh_listing()

    def update_summary(self) -> None:
        """Show selected / total size, file count and folder count."""
        total_files = 0
        total_dirs = 0
        total_size = 0

        selected_files = 0
        selected_dirs = 0
        selected_size = 0

        for path in self.entries:
            if path is None:
                continue

            try:
                if path.is_dir():
                    total_dirs += 1
                    if path in self.marked:
                        selected_dirs += 1
                elif path.is_file():
                    total_files += 1
                    size = path.stat().st_size
                    total_size += size

                    if path in self.marked:
                        selected_files += 1
                        selected_size += size
            except OSError:
                continue

        summary = (
            f"Capacity: {human_size(selected_size)} / {human_size(total_size)}"
            f"    Files: {selected_files:,} / {total_files:,}"
            f"    Folders: {selected_dirs:,} / {total_dirs:,}"
        )

        self.query_one(".pane_summary", Static).update(summary)

    def reset_shift_selection_anchor(self) -> None:
        """End the current Shift+Arrow range-selection session."""
        self.shift_anchor_row = None
        self.shift_base_marked = set()

    def set_shift_selection_anchor(self, row: int) -> None:
        """Use an explicit mouse-selected row as the next Shift range start."""
        if self.table.row_count <= 0:
            self.reset_shift_selection_anchor()
            return
        self.shift_anchor_row = max(
            0,
            min(self.table.row_count - 1, int(row)),
        )
        self.shift_base_marked = set(self.marked)

    def shift_select(self, delta: int) -> None:
        """Extend or shrink a contiguous selection with Shift+Up/Down.

        The first Shift+Arrow press establishes an anchor at the current row.
        Moving farther extends the selected range. Moving back toward the
        anchor shrinks it, similar to Explorer-style range selection.
        Existing marks outside the range are preserved.
        """
        if self.table.row_count <= 0:
            return

        current_row = self.table.cursor_row
        if current_row < 0:
            current_row = 0

        if self.shift_anchor_row is None:
            self.shift_anchor_row = current_row
            self.shift_base_marked = set(self.marked)

        target_row = max(
            0,
            min(self.table.row_count - 1, current_row + delta),
        )

        self.select_range_to(target_row)

    def select_range_to(self, target_row: int) -> None:
        """Select from the keyboard/mouse anchor through an explicit row."""
        if self.table.row_count <= 0:
            return

        current_row = max(0, self.table.cursor_row)
        if self.shift_anchor_row is None:
            self.shift_anchor_row = current_row
            self.shift_base_marked = set(self.marked)

        target_row = max(0, min(self.table.row_count - 1, target_row))

        # Build a range between anchor and target, skipping the synthetic "..".
        lo = min(self.shift_anchor_row, target_row)
        hi = max(self.shift_anchor_row, target_row)

        range_paths: set[Path] = set()
        for row in range(lo, hi + 1):
            if 0 <= row < len(self.entries):
                path = self.entries[row]
                if path is not None:
                    range_paths.add(path)

        self.marked = set(self.shift_base_marked) | range_paths

        target_path = (
            self.entries[target_row]
            if 0 <= target_row < len(self.entries)
            else None
        )
        keep_name = target_path.name if target_path is not None else None

        # Repaint '*' marks, then restore the cursor to the target row/name.
        self.refresh_listing(keep_name=keep_name)

        # If target is "..", keep_name is None, so explicitly restore its row.
        if target_path is None and self.table.row_count:
            self.table.move_cursor(row=target_row, column=0)

        self.update_info()
        self.update_summary()

    def selected_path(self) -> Optional[Path]:
        row = self.table.cursor_row
        if row < 0 or row >= len(self.entries):
            return None
        return self.entries[row]

    def selected_is_parent(self) -> bool:
        row = self.table.cursor_row
        return 0 <= row < len(self.entries) and self.entries[row] is None

    def selected_items(self) -> list[Path]:
        if self.marked:
            return sorted(self.marked, key=lambda p: p.name.lower())
        selected = self.selected_path()
        return [selected] if selected else []

    def toggle_mark_path(self, path: Path) -> None:
        if path in self.marked:
            self.marked.remove(path)
        else:
            self.marked.add(path)
        self.refresh_listing(keep_name=path.name)
        self.update_summary()

    def toggle_mark(self) -> None:
        self.reset_shift_selection_anchor()
        path = self.selected_path()
        if not path:
            return
        self.toggle_mark_path(path)

    def find(self, query: str) -> bool:
        query = query.lower()
        if not query:
            return False

        total = len(self.entries)
        if total == 0:
            return False

        start = max(0, self.table.cursor_row + 1)
        indices = list(range(start, total)) + list(range(0, start))

        for starts in (True, False):
            for i in indices:
                path = self.entries[i]
                if path is None:
                    continue
                name = path.name.lower()
                match = name.startswith(query) if starts else query in name
                if match:
                    self.table.move_cursor(row=i, column=0)
                    self.update_info()
                    return True
        return False

    def update_info(self) -> None:
        box = self.query_one(".pane_info", Static)
        path = self.selected_path()
        marked_count = len(self.marked)

        if self.selected_is_parent():
            parent = self.current_path.parent
            box.update(
                f"Name: ..    Type: Parent directory\n"
                f"Path: {parent}\n"
                f"Current: {self.current_path}\n"
                f"Marked: {marked_count}"
            )
            return

        if not path:
            box.update(
                f"Current: {self.current_path}\n\n\nMarked: {marked_count}"
            )
            return

        try:
            stat = path.stat()
            kind = "DIR" if path.is_dir() else (path.suffix.lower().lstrip(".").upper() or "FILE")
            size = "<DIR>" if path.is_dir() else human_size(stat.st_size)
            modified = fmt_time(stat.st_mtime)
            line1 = f"Name: {path.name}"
            line2 = f"Type: {kind}    Size: {size}    Modified: {modified}"
            line3 = f"Path: {path}"
            line4 = f"Marked: {marked_count}"
            box.update(f"{line1}\n{line2}\n{line3}\n{line4}")
        except OSError as exc:
            box.update(f"Name: {path.name}\nError: {exc}\nPath: {path}\nMarked: {marked_count}")


class MDir(App):
    PROMPT_SCREEN = PromptScreen
    CONFIRM_SCREEN = ConfirmScreen
    VIEWER_SCREEN = ViewerScreen
    TITLE = f"MDIR-U {VERSION}"
    SUB_TITLE = "Ubuntu and Universal Dual Pane File Manager"
    ENABLE_COMMAND_PALETTE = False

    CSS = """
    Screen { background: black; }

    .pane-wrap {
        width: 1fr;
        height: 1fr;
    }

    .drive-bar {
        height: 1;
        min-height: 1;
        max-height: 1;
        background: #202020;
        padding: 0;
        align-vertical: top;
    }

    .drive-bar Button {
        min-width: 4;
        width: 4;
        height: 1;
        min-height: 1;
        max-height: 1;
        margin: 0 1 0 0;
        padding: 0;
        background: #303030;
        color: #dddddd;
        border: none;
    }

    .drive-bar Button:hover {
        background: #464646;
        color: white;
    }

    .drive-bar Button.current-drive {
        background: #075985;
        color: white;
        text-style: bold;
    }

    .drive-info {
        height: 1;
        min-height: 1;
        max-height: 1;
        background: #202020;
        color: #cfcfcf;
        padding: 0;
    }

    .hidden-toggle {
        min-width: 9;
        width: 9;
        height: 1;
        min-height: 1;
        max-height: 1;
        margin: 0 0 0 1;
        padding: 0;
        border: none;
        background: #303030;
        color: #dddddd;
    }

    .hidden-toggle:hover {
        background: #464646;
        color: white;
    }

    .hidden-toggle.showing-hidden {
        background: #7c2d12;
        color: white;
        text-style: bold;
    }

    #panes { height: 1fr; }

    #status {
        height: 1;
        background: #202830;
        color: white;
        padding-left: 1;
    }

    Footer { background: #202830; }
    """

    BINDINGS = [
        Binding("ctrl+q", "ignore", "", show=False, priority=True, system=True),
        Binding("tab", "switch_pane", "Pane", show=False),
        Binding("left", "focus_left", "Left", show=False),
        Binding("right", "focus_right", "Right", show=False),
        Binding("enter", "open_item", "Open", show=False),
        Binding("backspace", "parent", "Parent"),
        Binding("space", "mark", "Mark"),
        Binding("shift+up", "shift_select_up", "Select Up", show=False, priority=True),
        Binding("shift+down", "shift_select_down", "Select Down", show=False, priority=True),
        Binding("shift+home", "shift_select_home", "Select to Top", show=False, priority=True),
        Binding("shift+end", "shift_select_end", "Select to Bottom", show=False, priority=True),
        Binding("shift+pageup", "shift_select_page_up", "Select Page Up", show=False, priority=True),
        Binding("shift+pagedown", "shift_select_page_down", "Select Page Down", show=False, priority=True),
        Binding("f2", "rename", "Rename", id="mdir.rename"),
        Binding("ctrl+f2", "batch_rename", "Batch Rename", show=False, id="mdir.batch_rename"),
        Binding("f3", "view", "View", id="mdir.view"),
        Binding("f4", "edit", "Edit", id="mdir.edit"),
        Binding("f5", "copy", "Copy", id="mdir.copy"),
        Binding("f6", "move", "Move", id="mdir.move"),
        Binding("alt+f5", "compress_zip", "ZIP", show=False, id="mdir.compress_zip"),
        Binding("alt+f6", "extract_zip", "Unzip", show=False, id="mdir.extract_zip"),
        Binding("f7", "mkdir", "MkDir", id="mdir.mkdir"),
        Binding("f8", "delete", "Delete", id="mdir.delete"),
        Binding("delete", "delete", "Delete", show=False, id="mdir.delete_alias"),
        Binding("f9", "drive", "Drive", id="mdir.drive"),
        Binding("f10", "options", "Option"),
        Binding("ctrl+f", "search", "Find", show=False, id="mdir.search"),
        Binding("ctrl+shift+f", "mindex", "mIndex", show=False, id="mdir.mindex"),
        Binding("ctrl+shift+d", "find_duplicates", "Duplicates", show=False, id="mdir.duplicates"),
        Binding("ctrl+shift+c", "compare_folders", "Compare", show=False, id="mdir.compare"),
        Binding("ctrl+shift+y", "safe_sync", "Safe sync", show=False, id="mdir.safe_sync"),
        Binding("ctrl+shift+m", "toggle_macro_recording", "Record macro", show=False, id="mdir.record_macro"),
        Binding("ctrl+alt+m", "play_macro", "Play macro", show=False, id="mdir.play_macro"),
        Binding("ctrl+z", "undo_last", "Undo", show=False, id="mdir.undo"),
        Binding("ctrl+shift+s", "save_workspace", "Save workspace", show=False, id="mdir.save_workspace"),
        Binding("ctrl+shift+l", "load_workspace", "Load workspace", show=False, id="mdir.load_workspace"),
        Binding("ctrl+n", "sort_name", "Name sort", show=False, id="mdir.sort_name"),
        Binding("ctrl+e", "sort_ext", "Ext sort", show=False, id="mdir.sort_ext"),
        Binding("ctrl+s", "sort_size", "Size sort", show=False, id="mdir.sort_size"),
        Binding("ctrl+d", "sort_date", "Modified sort", show=False, id="mdir.sort_date"),
        Binding("ctrl+r", "refresh_all", "Refresh", show=False, id="mdir.refresh"),
        Binding("f11", "refresh_drives", "Refresh Drives", show=False, id="mdir.refresh_drives"),
        Binding("ctrl+h", "hidden_system", "Hidden/System", show=False, id="mdir.hidden_system"),
        Binding("ctrl+w", "column_widths", "Column widths", show=False, id="mdir.column_widths"),
        Binding("ctrl+shift+w", "reset_column_widths", "Reset widths", show=False, id="mdir.reset_widths"),
        Binding("alt+enter", "properties", "Properties", show=False, id="mdir.properties"),
        Binding("ctrl+g", "folder_size", "Folder size", show=False, id="mdir.folder_size"),
        Binding("shift+f10", "powershell_here", "Terminal", show=False, id="mdir.terminal"),
        Binding("alt+f1", "drive_left", "Left location", show=False, id="mdir.drive_left"),
        Binding("alt+f2", "drive_right", "Right location", show=False, id="mdir.drive_right"),
    ]

    def action_ignore(self) -> None:
        """Deliberately suppress the framework's generic Ctrl+Q command."""
        return None

    def __init__(self) -> None:
        super().__init__()
        start = Path.cwd()
        left, right = self._load_saved_paths(start)
        self.left_start = left
        self.right_start = right
        self.column_widths = self._load_column_widths()
        try:
            self.show_hidden_system = self._load_hidden_system_setting()
        except Exception:
            self.show_hidden_system = False
        self.active_side = "left"
        self.available_drives = list_windows_drives()

    @staticmethod
    def _default_other_path(start: Path) -> Path:
        if os.name == "nt" and start.drive:
            return Path(f"{start.drive}\\")
        return Path.home()

    def _load_saved_paths(self, start: Path) -> tuple[Path, Path]:
        default_right = self._default_other_path(start)
        try:
            data = load_config_data()
            left = Path(data.get("left", str(start)))
            right = Path(data.get("right", str(default_right)))
            if not left.exists():
                left = start
            if not right.exists():
                right = default_right
            return left, right
        except Exception:
            return start, default_right

    def _load_column_widths(self) -> dict[str, int]:
        """Load saved column widths, falling back safely to defaults."""
        widths = dict(DEFAULT_COLUMN_WIDTHS)

        try:
            data = load_config_data()
            saved = data.get("column_widths", {})

            if not isinstance(saved, dict):
                return widths

            try:
                layout_version = int(data.get("column_layout_version", 0))
            except (TypeError, ValueError):
                layout_version = 0
            migrate_extension_width = (
                layout_version < CURRENT_COLUMN_LAYOUT_VERSION
            )

            limits = {
                "name": (12, 120),
                "extension": (5, 30),
                "size": (10, 24),
                "modified": (21, 32),
            }

            for key, default_value in DEFAULT_COLUMN_WIDTHS.items():
                try:
                    value = int(saved.get(key, default_value))
                except (TypeError, ValueError):
                    value = default_value

                if key == "extension" and migrate_extension_width:
                    value -= 2

                lo, hi = limits[key]
                widths[key] = max(lo, min(hi, value))

            if migrate_extension_width:
                data["column_widths"] = dict(widths)
                data["column_layout_version"] = CURRENT_COLUMN_LAYOUT_VERSION
                try:
                    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
                    CONFIG_PATH.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except OSError:
                    pass

        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return dict(DEFAULT_COLUMN_WIDTHS)

        return widths

    def _load_hidden_system_setting(self) -> bool:
        """Load Hidden/System visibility setting.

        Default is False so Hidden/System files are not shown.
        A missing, old, or invalid config file must never prevent startup.
        """
        try:
            data = load_config_data()
            return bool(data.get("show_hidden_system", False))

        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return False

    def _save_paths(self) -> None:
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(
                json.dumps(
                    {
                        "left": str(self.left.current_path),
                        "right": str(self.right.current_path),
                        "column_widths": dict(self.column_widths),
                        "column_layout_version": CURRENT_COLUMN_LAYOUT_VERSION,
                        "show_hidden_system": bool(self.show_hidden_system),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="panes"):
            with Vertical(id="left_wrap", classes="pane-wrap"):
                with Horizontal(id="left_drive_bar", classes="drive-bar"):
                    for index in range(26):
                        letter = chr(ord("A") + index)
                        yield Button(
                            letter,
                            id=f"ldrive_{letter.lower()}",
                            classes="drive-button",
                            tooltip=f"Switch LEFT pane to {letter}:\\",
                        )
                    yield Button(
                        "Hidden",
                        id="left_hidden_toggle",
                        classes="hidden-toggle",
                        tooltip="Show or hide Hidden/System files",
                    )
                yield Static("", id="left_drive_info", classes="drive-info")
                yield FilePane(
                    "left",
                    self.left_start,
                    self.column_widths,
                    self.show_hidden_system,
                )

            with Vertical(id="right_wrap", classes="pane-wrap"):
                with Horizontal(id="right_drive_bar", classes="drive-bar"):
                    for index in range(26):
                        letter = chr(ord("A") + index)
                        yield Button(
                            letter,
                            id=f"rdrive_{letter.lower()}",
                            classes="drive-button",
                            tooltip=f"Switch RIGHT pane to {letter}:\\",
                        )
                    yield Button(
                        "Hidden",
                        id="right_hidden_toggle",
                        classes="hidden-toggle",
                        tooltip="Show or hide Hidden/System files",
                    )
                yield Static("", id="right_drive_info", classes="drive-info")
                yield FilePane(
                    "right",
                    self.right_start,
                    self.column_widths,
                    self.show_hidden_system,
                )

        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.set_active("left")
        self.refresh_drives()
        self._sync_drive_buttons()
        self.update_hidden_buttons()
        self.left.update_summary()
        self.right.update_summary()
        self.set_status("")

        # Automatic drive hot-plug detection.
        self.set_interval(1.5, self.auto_detect_drives)

    def on_unmount(self) -> None:
        self._save_paths()

    @property
    def left(self) -> FilePane:
        return self.query_one("#left", FilePane)

    @property
    def right(self) -> FilePane:
        return self.query_one("#right", FilePane)

    @property
    def active(self) -> FilePane:
        return self.left if self.active_side == "left" else self.right

    @property
    def passive(self) -> FilePane:
        return self.right if self.active_side == "left" else self.left

    def set_active(self, side: str, *, focus_table: bool = True) -> None:
        self.active_side = side
        self.left.set_active(side == "left")
        self.right.set_active(side == "right")
        self.active.reset_shift_selection_anchor()
        if focus_table:
            self.active.table.focus()

        # During very early mount the toolbar may not exist yet.
        try:
            self.update_drive_bar()
        except Exception:
            pass

    def update_hidden_buttons(self) -> None:
        """Update Hidden/System toggle appearance for both panes."""
        label = "Hide H/S" if self.show_hidden_system else "Show H/S"

        for button_id in (
            "#left_hidden_toggle",
            "#right_hidden_toggle",
        ):
            try:
                button = self.query_one(button_id, Button)
                button.label = label
                button.set_class(
                    self.show_hidden_system,
                    "showing-hidden",
                )
            except Exception:
                pass

    def toggle_hidden_system(self) -> None:
        """Toggle Hidden/System visibility globally for both panes."""
        self.show_hidden_system = not self.show_hidden_system

        self.left.set_hidden_system_visibility(self.show_hidden_system)
        self.right.set_hidden_system_visibility(self.show_hidden_system)

        self.update_hidden_buttons()
        self._save_paths()

        if self.show_hidden_system:
            self.set_status("Hidden/System files are now visible.")
        else:
            self.set_status("Hidden/System files are hidden.")

    def _sync_drive_buttons(self) -> None:
        """Show buttons for available drives and hide all others.

        Buttons are created once during compose(), avoiding runtime remove/mount
        races that could make one pane's drive bar disappear.
        """
        available = {drive.upper() for drive in self.available_drives}

        for prefix in ("ldrive_", "rdrive_"):
            for index in range(26):
                letter = chr(ord("A") + index)
                drive = f"{letter}:"
                try:
                    button = self.query_one(
                        f"#{prefix}{letter.lower()}",
                        Button,
                    )
                    button.display = drive in available
                except Exception:
                    pass

    def _recover_removed_drive_panes(self) -> None:
        """Move a pane away from a drive that has just disappeared."""
        available = {drive.upper() for drive in self.available_drives}
        if not available:
            return

        fallback = "C:" if "C:" in available else sorted(available)[0]

        for pane in (self.left, self.right):
            current = (pane.current_path.drive or "").upper()
            if current and current not in available:
                root = Path(fallback + "\\")
                try:
                    pane.current_path = root
                    pane.marked.clear()
                    pane.refresh_listing()
                    pane.update_summary()
                except Exception:
                    pass

    def auto_detect_drives(self) -> None:
        """Automatically detect connected/disconnected Windows drives."""
        if os.name != "nt":
            return

        latest = list_windows_drives()
        if latest == self.available_drives:
            return

        previous = set(self.available_drives)
        current = set(latest)
        added = sorted(current - previous)
        removed = sorted(previous - current)

        self.available_drives = latest
        self._sync_drive_buttons()
        self._recover_removed_drive_panes()
        self.update_drive_bar()
        self.update_hidden_buttons()
        self._save_paths()

        messages = []
        if added:
            messages.append("Connected: " + ", ".join(added))
        if removed:
            messages.append("Removed: " + ", ".join(removed))
        if messages:
            self.set_status(" | ".join(messages))

    def refresh_drives(self) -> None:
        """Rescan usable Windows drives and synchronize both drive bars."""
        latest = list_windows_drives()
        changed = latest != self.available_drives
        self.available_drives = latest

        self._sync_drive_buttons()
        self._recover_removed_drive_panes()
        self.update_drive_bar()
        self.update_hidden_buttons()

        if changed:
            self._save_paths()
            self.set_status(
                "Drives refreshed: "
                + (", ".join(self.available_drives) if self.available_drives else "none")
            )

    def update_drive_bar(self) -> None:
        """Highlight each pane's current drive and show free/total capacity."""
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

            try:
                if current and current in available:
                    info = drive_usage_text(current)
                elif current:
                    info = f"{current}  drive unavailable"
                else:
                    info = "No active drive"
                self.query_one(info_id, Static).update(info)
            except Exception:
                pass

    def switch_pane_to_drive(self, pane: FilePane, drive: str) -> None:
        """Switch one pane to a Windows drive root safely."""
        # Rescan first so recently connected/removable drives are recognized.
        latest = list_windows_drives()
        if latest != self.available_drives:
            self.available_drives = latest
            self._sync_drive_buttons()
            self.update_hidden_buttons()

        drive = drive.upper().rstrip("\\/")
        if not drive.endswith(":"):
            drive += ":"

        root = Path(drive + "\\")

        try:
            if not root.exists():
                self.set_status(f"Drive not available: {drive}")
                return
        except OSError as exc:
            self.set_status(f"Drive error: {drive} ({exc})")
            return

        try:
            pane.current_path = root
            pane.marked.clear()
            pane.refresh_listing()
            pane.update_summary()

            self._save_paths()
            self.update_drive_bar()
            self.set_status(f"{pane.id.upper()} pane → {drive}\\")
            pane.table.focus()

        except Exception as exc:
            self.set_status(f"Failed to switch to {drive}: {exc}")

    @on(Button.Pressed)
    def drive_button_pressed(self, event: Button.Pressed) -> None:
        """Handle drive buttons and Hidden/System toggle buttons."""
        button_id = event.button.id or ""

        try:
            if button_id in {
                "left_hidden_toggle",
                "right_hidden_toggle",
            }:
                self.toggle_hidden_system()
                event.stop()
                return

            if button_id.startswith("ldrive_"):
                pane = self.left
                letter = button_id.removeprefix("ldrive_").upper()
                self.set_active("left")
            elif button_id.startswith("rdrive_"):
                pane = self.right
                letter = button_id.removeprefix("rdrive_").upper()
                self.set_active("right")
            else:
                return

            if len(letter) != 1 or not letter.isalpha():
                return

            self.switch_pane_to_drive(pane, f"{letter}:")
            event.stop()

        except Exception as exc:
            self.set_status(f"Button action failed: {exc}")
            event.stop()

    def action_refresh_drives(self) -> None:
        self.refresh_drives()

    def action_hidden_system(self) -> None:
        self.toggle_hidden_system()

    def set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def action_switch_pane(self) -> None:
        self.set_active("right" if self.active_side == "left" else "left")

    def action_focus_left(self) -> None:
        self.set_active("left")

    def action_focus_right(self) -> None:
        self.set_active("right")

    def action_refresh_all(self) -> None:
        self.left.refresh_listing()
        self.right.refresh_listing()
        before = list(self.available_drives)
        self.refresh_drives()
        if before == self.available_drives:
            self.set_status("Refreshed.")

    def action_parent(self) -> None:
        pane = self.active
        pane.reset_shift_selection_anchor()
        parent = pane.current_path.parent
        if parent != pane.current_path:
            old_name = pane.current_path.name
            pane.current_path = parent
            pane.marked.clear()
            pane.refresh_listing(keep_name=old_name)
            self._save_paths()
            self.update_drive_bar()

    def _open_from_pane(self, pane: FilePane) -> None:
        """Open the currently selected row in the given pane.

        DataTable consumes Enter and mouse clicks itself, so this method is
        called from DataTable.RowSelected as well as from action_open_item().
        """
        pane.reset_shift_selection_anchor()

        # Make the clicked/selected pane active first.
        self.set_active("left" if pane.id == "left" else "right")

        if pane.selected_is_parent():
            parent = pane.current_path.parent
            if parent != pane.current_path:
                old_name = pane.current_path.name
                pane.current_path = parent
                pane.marked.clear()
                pane.refresh_listing(keep_name=old_name)
                self._save_paths()
            return

        path = pane.selected_path()
        if not path:
            return

        if path.is_dir():
            try:
                pane.current_path = path
                pane.marked.clear()
                pane.refresh_listing()
                self._save_paths()
                self.update_drive_bar()
                self.set_status(f"Directory: {path}")
            except Exception as exc:
                self.set_status(f"Directory open failed: {exc}")
            return

        try:
            self.open_external_path(path)
            self.set_status(f"Opened: {path.name}")
        except Exception as exc:
            self.set_status(f"Open failed: {exc}")

    def open_external_path(self, path: Path) -> None:
        """Open a file through the operating system's default application."""
        open_with_default_app(path)

    def action_open_item(self) -> None:
        self._open_from_pane(self.active)

    def action_shift_select_up(self) -> None:
        self.active.shift_select(-1)

    def action_shift_select_down(self) -> None:
        self.active.shift_select(1)

    def action_shift_select_home(self) -> None:
        self.active.select_range_to(0)

    def action_shift_select_end(self) -> None:
        self.active.select_range_to(self.active.table.row_count - 1)

    def action_shift_select_page_up(self) -> None:
        self.active.shift_select(-max(1, self.active.table.size.height - 2))

    def action_shift_select_page_down(self) -> None:
        self.active.shift_select(max(1, self.active.table.size.height - 2))

    def action_mark(self) -> None:
        self.active.toggle_mark()

    def action_rename(self) -> None:
        path = self.active.selected_path()
        if not path:
            self.set_status("Select a file or directory first.")
            return

        def got_name(name: Optional[str]) -> None:
            if not name or name == path.name:
                return

            target = path.with_name(name)
            if target.exists():
                self.set_status(f"Rename failed: '{name}' already exists.")
                return

            try:
                path.rename(target)

                if path in self.active.marked:
                    self.active.marked.remove(path)
                    self.active.marked.add(target)

                self.active.refresh_listing(keep_name=target.name)
                self.passive.refresh_listing()
                self.set_status(f"Renamed: {path.name} -> {target.name}")
                recorder = getattr(self, "record_operation", None)
                if callable(recorder):
                    recorder("rename", ((path, target),))
            except Exception as exc:
                self.set_status(f"Rename failed: {exc}")

        self.push_screen(self.PROMPT_SCREEN("Rename:", path.name), got_name)

    def action_view(self) -> None:
        path = self.active.selected_path()
        if not path or path.is_dir():
            self.set_status("F3 View works on files.")
            return
        self.push_screen(self.VIEWER_SCREEN(path))

    def action_edit(self) -> None:
        path = self.active.selected_path()
        if not path or path.is_dir():
            self.set_status("F4 Edit works on files.")
            return

        nano = shutil.which("nano")
        if nano is None:
            message = (
                "nano editor is not installed. Install it with: "
                "sudo apt update && sudo apt install nano"
            )
            self.set_status(message)
            self.notify(message, title="Nano editor required")
            return

        try:
            self.set_status(f"Opening nano: {path.name}")
            with self.suspend():
                result = subprocess.run([nano, str(path)], check=False)
            self.active.refresh_listing(keep_name=path.name)
            self.active.update_info()
            if result.returncode:
                self.set_status(
                    f"nano exited with status {result.returncode}: {path.name}"
                )
            else:
                self.set_status(f"Finished editing: {path.name}")
        except Exception as exc:
            self.set_status(f"Could not open nano: {exc}")

    def action_copy(self) -> None:
        items = self.active.selected_items()
        if not items:
            self.set_status("Nothing selected.")
            return

        destination = self.passive.current_path
        names = ", ".join(p.name for p in items[:3])
        if len(items) > 3:
            names += f" (+{len(items) - 3})"

        def confirmed(ok: bool) -> None:
            if not ok:
                return

            errors = []
            for src in items:
                dst = destination / src.name
                try:
                    if src.resolve() == dst.resolve():
                        continue
                    if src.is_dir():
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dst)
                except Exception as exc:
                    errors.append(f"{src.name}: {exc}")

            self.active.marked.clear()
            self.active.refresh_listing()
            self.passive.refresh_listing()

            if errors:
                self.set_status("Copy errors: " + " | ".join(errors[:2]))
            else:
                self.set_status(f"Copied {len(items)} item(s) to {destination}")

        self.push_screen(
            self.CONFIRM_SCREEN(f"Copy {names}\nTO:\n{destination} ?"),
            confirmed,
        )

    def action_move(self) -> None:
        items = self.active.selected_items()
        if not items:
            self.set_status("Nothing selected.")
            return

        destination = self.passive.current_path
        names = ", ".join(p.name for p in items[:3])
        if len(items) > 3:
            names += f" (+{len(items) - 3})"

        def confirmed(ok: bool) -> None:
            if not ok:
                return

            errors = []
            for src in items:
                dst = destination / src.name
                try:
                    if src.resolve() == dst.resolve():
                        continue
                    shutil.move(str(src), str(dst))
                except Exception as exc:
                    errors.append(f"{src.name}: {exc}")

            self.active.marked.clear()
            self.active.refresh_listing()
            self.passive.refresh_listing()

            if errors:
                self.set_status("Move errors: " + " | ".join(errors[:2]))
            else:
                self.set_status(f"Moved {len(items)} item(s) to {destination}")

        self.push_screen(
            self.CONFIRM_SCREEN(f"Move {names}\nTO:\n{destination} ?"),
            confirmed,
        )

    def action_mkdir(self) -> None:
        selected = self.active.selected_path()
        initial_name = selected.name if selected is not None else ""

        def got_name(name: Optional[str]) -> None:
            if not name:
                return

            new_dir = self.active.current_path / name
            try:
                new_dir.mkdir(parents=False, exist_ok=False)
                self.active.refresh_listing(keep_name=name)
                self.set_status(f"Created directory: {name}")
                recorder = getattr(self, "record_operation", None)
                if callable(recorder):
                    recorder("mkdir", ((new_dir, new_dir),))
            except Exception as exc:
                self.set_status(f"MkDir failed: {exc}")

        self.push_screen(
            self.PROMPT_SCREEN("New directory name:", initial_name),
            got_name,
        )

    def action_delete(self) -> None:
        items = self.active.selected_items()
        if not items:
            self.set_status("Nothing selected.")
            return

        names = "\n".join(f"  {p.name}" for p in items[:4])
        if len(items) > 4:
            names += f"\n  ... and {len(items) - 4} more"

        def confirmed(ok: bool) -> None:
            if not ok:
                self.set_status("Delete cancelled.")
                return

            errors = []
            for path in items:
                try:
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                except Exception as exc:
                    errors.append(f"{path.name}: {exc}")

            self.active.marked.clear()
            self.active.refresh_listing()
            self.passive.refresh_listing()

            if errors:
                self.set_status("Delete errors: " + " | ".join(errors[:2]))
            else:
                self.set_status(f"Deleted {len(items)} item(s).")

        self.push_screen(
            self.CONFIRM_SCREEN(
                "PERMANENT DELETE - cannot be undone:\n"
                f"{names}"
            ),
            confirmed,
        )

    def action_drive(self) -> None:
        self._prompt_drive(self.active)

    def action_drive_left(self) -> None:
        self._prompt_drive(self.left)

    def action_drive_right(self) -> None:
        self._prompt_drive(self.right)

    def _prompt_drive(self, pane: FilePane) -> None:
        if os.name != "nt":
            self.set_status("Drive selection is intended for Windows.")
            return

        current_drive = pane.current_path.drive or "C:"
        initial = current_drive.rstrip("\\/")

        def got_drive(value: Optional[str]) -> None:
            if not value:
                return

            value = value.strip().upper()
            if len(value) == 1 and value.isalpha():
                value += ":"

            if not value.endswith(":"):
                self.set_status("Drive example: C: or D:")
                return

            self.switch_pane_to_drive(pane, value)

        self.push_screen(
            self.PROMPT_SCREEN("Drive (example C: or D:):", initial),
            got_drive,
        )

    def action_search(self) -> None:
        def got_query(query: Optional[str]) -> None:
            if not query:
                return
            if self.active.find(query):
                self.set_status(f"Found: {query}")
            else:
                self.set_status(f"Not found: {query}")

        self.push_screen(self.PROMPT_SCREEN("Find file/directory:"), got_query)

    def apply_column_widths(
        self,
        widths: dict[str, int],
        *,
        save: bool = True,
    ) -> None:
        normalized = dict(self.column_widths)

        for key in COLUMN_ORDER:
            try:
                value = int(widths.get(key, normalized[key]))
            except (TypeError, ValueError):
                value = normalized[key]

            normalized[key] = max(COLUMN_HARD_MIN_WIDTHS[key], value)

        self.column_widths = normalized
        self.left.set_column_widths(normalized)
        self.right.set_column_widths(normalized)

        if save:
            self._save_paths()

    def action_column_widths(self) -> None:
        def applied(widths: Optional[dict[str, int]]) -> None:
            if not widths:
                return

            self.apply_column_widths(widths, save=True)
            self.set_status(
                "Column widths: "
                f"Name {widths['name']} | "
                f"Extension {widths['extension']} | "
                f"Size {widths['size']} | "
                f"Modified {widths['modified']}"
            )

        self.push_screen(ColumnWidthScreen(self.column_widths), applied)

    def action_reset_column_widths(self) -> None:
        self.apply_column_widths(dict(DEFAULT_COLUMN_WIDTHS), save=True)
        self.set_status("Column widths reset to defaults.")

    def action_properties(self) -> None:
        path = self.active.selected_path()
        if not path:
            self.set_status("Select a file or directory first.")
            return
        self.push_screen(PropertiesScreen(path))

    def action_folder_size(self) -> None:
        path = self.active.selected_path()
        if not path or not path.is_dir():
            self.set_status("Ctrl+G works on a directory.")
            return

        self.set_status(f"Calculating folder size: {path.name} ...")
        size, count, truncated = safe_folder_size(path)
        extra = " (stopped early)" if truncated else ""
        self.set_status(
            f"{path.name}: {human_size(size)} in {count:,} file(s){extra}"
        )

    def action_powershell_here(self) -> None:
        path = self.active.selected_path()
        target = path if path and path.is_dir() else self.active.current_path

        try:
            if os.name == "nt":
                # Prefer Windows Terminal if available.
                wt = shutil.which("wt.exe")
                if wt:
                    subprocess.Popen([wt, "-d", str(target), "powershell.exe"])
                else:
                    subprocess.Popen(
                        ["powershell.exe", "-NoExit", "-Command", f"Set-Location -LiteralPath '{str(target).replace(chr(39), chr(39)*2)}'"]
                    )
                self.set_status(f"PowerShell opened at: {target}")
            else:
                from .platform_support import terminal_command

                command = terminal_command(target)
                if command is None:
                    self.set_status(
                        "No terminal emulator found. Install "
                        "x-terminal-emulator or gnome-terminal."
                    )
                    return
                subprocess.Popen(command, cwd=target)
                self.set_status(f"Terminal opened at: {target}")
        except Exception as exc:
            self.set_status(f"Terminal open failed: {exc}")

    def _set_sort(self, mode: str) -> None:
        self.active.set_sort(mode)
        direction = "descending" if self.active.sort_reverse else "ascending"
        self.set_status(f"Sort: {mode} ({direction})")

    def action_sort_name(self) -> None:
        self._set_sort("name")

    def action_sort_ext(self) -> None:
        self._set_sort("ext")

    def action_sort_size(self) -> None:
        self._set_sort("size")

    def action_sort_date(self) -> None:
        self._set_sort("modified")

    @on(DataTable.HeaderSelected)
    def header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Click a column header to sort; click again to reverse."""
        try:
            if isinstance(event.data_table, MDirDataTable):
                if event.data_table._resize_key is not None:
                    return

            pane = event.data_table.parent
            if not isinstance(pane, FilePane):
                return

            # Make the pane whose header was clicked the active pane.
            self.set_active("left" if pane.id == "left" else "right")

            column_index = event.column_index
            mode_by_column = {
                0: "name",
                1: "ext",
                2: "size",
                3: "modified",
            }

            mode = mode_by_column.get(column_index)
            if mode is None:
                return

            pane.set_sort(mode)
            direction = "descending" if pane.sort_reverse else "ascending"
            labels = {
                "name": "Name",
                "ext": "Extension",
                "size": "Size",
                "modified": "Modified",
            }
            self.set_status(f"Sort: {labels[mode]} ({direction})")

        except Exception as exc:
            self.set_status(f"Header sort failed: {exc}")

    @on(DataTable.RowHighlighted)
    def row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        try:
            pane = event.data_table.parent
            if isinstance(pane, FilePane):
                pane.update_info()
        except Exception:
            pass


if __name__ == "__main__":
    # Run "python -m mdir --check" to verify the installed build.
    if "--check" in sys.argv:
        required = [
            "_load_saved_paths",
            "_load_column_widths",
            "_save_paths",
            "action_column_widths",
            "action_reset_column_widths",
            "apply_column_widths",
            "update_drive_bar",
            "switch_pane_to_drive",
        ]
        missing = [name for name in required if not hasattr(MDir, name)]

        print(f"MDIR {VERSION} self-check")
        print(f"Config file: {CONFIG_PATH}")
        print(f"Default column widths: {DEFAULT_COLUMN_WIDTHS}")

        if missing:
            print("ERROR - missing methods:", ", ".join(missing))
            raise SystemExit(1)

        print("OK - required methods are present.")
        raise SystemExit(0)

    MDir().run()
