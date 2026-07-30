from __future__ import annotations

from pathlib import Path
from typing import Protocol

from rich.text import Text
from textual.theme import Theme


THEME_NAME = "total-commander"

BACKGROUND = "#202020"
SURFACE = "#292929"
PANEL = "#242424"
HEADER = "#353535"
SEPARATOR = "#555555"
FOREGROUND = "#d8d8d8"
MUTED = "#a9a9a9"
SELECTION = "#3f6179"
SELECTION_HOVER = "#4d7088"
FOLDER = "#e0bd62"
EXECUTABLE = "#9fbd79"
MARKED = "#f1cd69"
ACCENT = "#7894a8"


TOTAL_COMMANDER_THEME = Theme(
    name=THEME_NAME,
    primary=ACCENT,
    secondary="#78838a",
    warning=MARKED,
    error="#bf6874",
    success=EXECUTABLE,
    accent=FOLDER,
    foreground=FOREGROUND,
    background=BACKGROUND,
    surface=SURFACE,
    panel=PANEL,
    boost="#3b3b3b",
    dark=True,
    variables={
        "footer-background": PANEL,
        "footer-foreground": FOREGROUND,
        "footer-item-background": PANEL,
        "footer-key-background": "#303030",
        "footer-key-foreground": FOLDER,
        "footer-description-background": PANEL,
        "footer-description-foreground": FOREGROUND,
        "block-hover-background": "#3a3a3a",
    },
)


class CachedEntryLike(Protocol):
    path: Path
    is_directory: bool


EXECUTABLE_EXTENSIONS = {
    ".exe",
    ".com",
    ".msi",
    ".bat",
    ".cmd",
    ".ps1",
}

_current_foreground = FOREGROUND
_current_folder = FOLDER
_current_executable = EXECUTABLE
_current_marked = MARKED


def cached_name_text(entry: CachedEntryLike, marked: bool) -> Text:
    """Render one cached directory entry with the default MDIR theme."""
    prefix = "* " if marked else "  "
    text = Text(prefix + entry.path.name)
    if marked:
        text.stylize(f"bold {_current_marked}")
    elif entry.is_directory:
        text.stylize(f"bold {_current_folder}")
    elif entry.path.suffix.lower() in EXECUTABLE_EXTENSIONS:
        text.stylize(_current_executable)
    else:
        text.stylize(_current_foreground)
    return text


def path_name_text(path: Path, marked: bool = False) -> Text:
    """Render one filesystem path without changing the original MDIR API."""
    prefix = "* " if marked else "  "
    text = Text(prefix + path.name)
    if marked:
        text.stylize(f"bold {_current_marked}")
    elif path.is_dir():
        text.stylize(f"bold {_current_folder}")
    elif path.suffix.lower() in EXECUTABLE_EXTENSIONS:
        text.stylize(_current_executable)
    else:
        text.stylize(_current_foreground)
    return text


def install_file_colors(theme: Theme | None = None) -> None:
    """Install the palette on both cached and legacy file-pane renderers."""
    global _current_foreground
    global _current_folder
    global _current_executable
    global _current_marked

    from . import core as legacy
    from .file_pane import EditablePathFilePane

    if theme is None:
        _current_foreground = FOREGROUND
        _current_folder = FOLDER
        _current_executable = EXECUTABLE
        _current_marked = MARKED
    else:
        colors = theme.to_color_system().generate()
        _current_foreground = colors.get("foreground", FOREGROUND)
        _current_folder = colors.get("accent", FOLDER)
        _current_executable = colors.get("success", EXECUTABLE)
        _current_marked = colors.get("warning", MARKED)

    legacy.PARENT_DIRECTORY_STYLE = f"bold {_current_foreground}"
    legacy.file_name_text = path_name_text
    EditablePathFilePane._name_text = staticmethod(cached_name_text)


TOTAL_COMMANDER_CSS = f"""
Screen {{
    background: $background;
    color: $foreground;
}}

Header {{
    background: $panel;
    color: $foreground;
}}

#panes,
.pane-wrap {{
    background: $background;
}}

FilePane {{
    border: solid $surface-lighten-2;
    background: $background;
}}

FilePane.active {{
    border: solid $primary;
}}

FilePane .pane_path {{
    background: $surface-lighten-1;
    color: $foreground;
    border: none;
    padding-left: 1;
}}

FilePane .pane_path:focus {{
    background: $primary;
    color: $text-primary;
}}

FilePane DataTable {{
    background: $background;
    color: $foreground;
    scrollbar-background: $background;
    scrollbar-color: $surface-lighten-2;
    scrollbar-color-hover: $surface-lighten-3;
    scrollbar-color-active: $primary;
}}

FilePane DataTable > .datatable--odd-row,
FilePane DataTable > .datatable--even-row,
FilePane DataTable > .datatable--fixed {{
    background: $background;
}}

FilePane DataTable > .datatable--header {{
    background: $surface-lighten-1;
    color: $foreground;
    text-style: bold;
}}

FilePane DataTable > .datatable--cursor {{
    background: $primary;
    color: $text-primary;
    text-style: none;
}}

FilePane DataTable > .datatable--hover {{
    background: $surface;
}}

FilePane .pane_footer {{
    background: $background;
}}

FilePane .pane_summary {{
    background: $panel;
    color: $foreground;
    border-top: solid $surface-lighten-2;
}}

FilePane .pane_info {{
    background: $background;
    color: $foreground;
    border-top: solid $surface-lighten-1;
}}

.drive-bar,
.drive-info,
#status,
Footer {{
    background: $panel;
    color: $foreground;
}}

.drive-bar Button,
.hidden-toggle {{
    background: $surface;
    color: $foreground;
    border: none;
}}

.drive-bar Button:hover,
.hidden-toggle:hover {{
    background: $surface-lighten-1;
}}

.drive-bar Button.current-drive {{
    background: $primary;
    color: $text-primary;
}}

.hidden-toggle.showing {{
    background: $warning-darken-2;
    color: $text-warning;
}}

AIPanel {{
    background: $background;
    border-left: solid $surface-lighten-2;
}}

AIPanel .ai-toolbar,
#ai_context,
#ai_activity {{
    background: $panel;
    color: $foreground;
}}

#ai_log {{
    background: $background;
    color: $foreground;
}}

#ai_prompt_row {{
    background: $background;
}}

DocumentPreviewPanel {{
    background: $background;
    border-left: solid $surface-lighten-2;
}}

DocumentPreviewPanel #document_preview_header {{
    background: $surface-lighten-1;
    border-bottom: solid $surface-lighten-2;
}}

DocumentPreviewPanel #document_preview_title {{
    color: $foreground;
}}

DocumentPreviewPanel #document_preview_scroll,
DocumentPreviewPanel #document_preview_canvas {{
    background: $background;
}}

DocumentPreviewPanel #document_preview_info {{
    background: $panel;
    color: $foreground;
    border-top: solid $surface-lighten-2;
}}

#compact_dialog,
#confirm_dialog,
#copy_dialog,
#drive_dialog,
#compact_viewer,
#file_search_dialog {{
    background: $surface;
    border: solid $primary;
    color: $foreground;
}}

#compact_header,
#confirm_header,
#copy_header,
#drive_header,
#viewer_header,
#file_search_header {{
    background: $surface-lighten-1;
    color: $foreground;
}}

#compact_help,
#confirm_help,
#copy_help,
#drive_help,
#viewer_help,
#search_result_help {{
    color: $text-muted;
}}

#search_results {{
    background: $background;
    color: $foreground;
}}

#search_results > .datatable--header {{
    background: $surface-lighten-1;
    color: $foreground;
}}

#search_results > .datatable--cursor {{
    background: $primary;
    color: $text-primary;
}}
"""
