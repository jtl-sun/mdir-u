from __future__ import annotations

from pathlib import Path
from typing import Protocol

from rich.text import Text
from textual.theme import Theme

from . import core as legacy
from .selection_style import MARK_FOREGROUND, MARK_PREFIX, CURSOR_BACKGROUND


THEME_NAME = "mDir theme"
OLD_M_THEME_NAME = "old_M_tema"
NORTON_THEME_NAME = "Norton Commander"

# Explicit colors keep selected filenames legible even when Rich Text supplies
# an extension-specific foreground style over the table's CSS foreground.
SELECTION_PALETTES = {
    THEME_NAME: ((CURSOR_BACKGROUND, "#ffffff"), ("#364953", "#ffffff")),
    OLD_M_THEME_NAME: (("#ff5a61", "#000000"), ("#99484d", "#ffffff")),
    NORTON_THEME_NAME: (("#55ffff", "#000066"), ("#315fc2", "#ffffff")),
}
MDIR_THEME_VARIABLE_DEFAULTS = {
    "mdir-cursor-background": CURSOR_BACKGROUND,
    "mdir-selection-foreground": "#ffffff",
    "mdir-inactive-background": "#364953",
    "mdir-inactive-foreground": "#ffffff",
    "mdir-list-background": "#202020",
    "mdir-border": "#45494c",
    "mdir-active-border": "#51cfe2",
    "mdir-path-background": "#353535",
    "mdir-path-foreground": "#f5f5f5",
    "mdir-header-background": "#353535",
    "mdir-header-foreground": "#f5f5f5",
    "mdir-toolbar-background": "#292929",
    "mdir-toolbar-foreground": "#d8d8d8",
}


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


MDIR_THEME = Theme(
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
        "mdir-cursor-background": CURSOR_BACKGROUND,
        "mdir-selection-foreground": "#ffffff",
        "mdir-inactive-background": "#364953",
        "mdir-inactive-foreground": "#ffffff",
        "mdir-list-background": BACKGROUND,
        "mdir-border": "#45494c",
        "mdir-active-border": "#51cfe2",
        "mdir-path-background": HEADER,
        "mdir-path-foreground": FOREGROUND,
        "mdir-header-background": HEADER,
        "mdir-header-foreground": FOREGROUND,
        "mdir-toolbar-background": PANEL,
        "mdir-toolbar-foreground": FOREGROUND,
    },
)


# A respectful retro palette inspired by the classic DOS Mdir III interface.
# It intentionally keeps the modern mDIR layout and features while restoring
# the black workspace, cyan/teal chrome, strong cursor and extension colors
# that made the original M easy to read at a glance.
OLD_M_THEME = Theme(
    name=OLD_M_THEME_NAME,
    primary="#00aaaa",
    secondary="#008888",
    warning="#ffff55",
    error="#ff5a61",
    success="#55ff55",
    accent="#ff5a61",  # Original Mdir: directories are coral/red, not cyan.
    foreground="#d5d5d5",
    background="#000000",
    surface="#000000",
    panel="#000000",
    boost="#004949",
    dark=True,
    variables={
        "footer-background": "#00a6a6",
        "footer-foreground": "#ffffff",
        "footer-item-background": "#00a6a6",
        "footer-key-background": "#bdbdbd",
        "footer-key-foreground": "#000000",
        "footer-description-background": "#00a6a6",
        "footer-description-foreground": "#ffffff",
        "block-hover-background": "#272727",
        "mdir-cursor-background": "#ff5a61",
        "mdir-selection-foreground": "#000000",
        "mdir-inactive-background": "#99484d",
        "mdir-inactive-foreground": "#ffffff",
        "mdir-list-background": "#000000",
        "mdir-border": "#17c8c5",
        "mdir-active-border": "#42ece9",
        "mdir-path-background": "#bdbdbd",
        "mdir-path-foreground": "#000000",
        "mdir-header-background": "#000000",
        "mdir-header-foreground": "#55ffff",
        "mdir-toolbar-background": "#00a6a6",
        "mdir-toolbar-foreground": "#000000",
    },
)


# Classic Norton Commander is a distinct style: deep blue pane, cyan frame,
# yellow captions, cyan text, with a turquoise cursor and dark letters.
NORTON_THEME = Theme(
    name=NORTON_THEME_NAME,
    primary="#55ffff",
    secondary="#00aaaa",
    warning="#ffff55",
    error="#ff7777",
    success="#55ff55",
    accent="#55ffff",
    foreground="#c9ffff",
    background="#000028",
    surface="#0000aa",
    panel="#0000aa",
    boost="#1515c2",
    dark=True,
    variables={
        "footer-background": "#00aaaa",
        "footer-foreground": "#000000",
        "footer-item-background": "#00aaaa",
        "footer-key-background": "#000000",
        "footer-key-foreground": "#ffff55",
        "footer-description-background": "#00aaaa",
        "footer-description-foreground": "#000000",
        "block-hover-background": "#2525c9",
        "mdir-cursor-background": "#55ffff",
        "mdir-selection-foreground": "#000066",
        "mdir-inactive-background": "#315fc2",
        "mdir-inactive-foreground": "#ffffff",
        "mdir-list-background": "#0000aa",
        "mdir-border": "#55ffff",
        "mdir-active-border": "#ffff55",
        "mdir-path-background": "#00aaaa",
        "mdir-path-foreground": "#000000",
        "mdir-header-background": "#0000aa",
        "mdir-header-foreground": "#ffff55",
        "mdir-toolbar-background": "#00aaaa",
        "mdir-toolbar-foreground": "#000000",
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
_current_theme_name = THEME_NAME
_current_extension_colors: dict[str, str] = {}


def selection_colors(*, active: bool) -> tuple[str, str]:
    """Return selected-row background and foreground for both panes."""
    focused, unfocused = SELECTION_PALETTES.get(
        _current_theme_name, SELECTION_PALETTES[THEME_NAME]
    )
    return focused if active else unfocused


def _file_color(path: Path) -> str:
    """Return a theme-aware filename color without changing file semantics."""
    extension = path.suffix.lower()
    return _current_extension_colors.get(
        extension,
        _current_executable if extension in EXECUTABLE_EXTENSIONS else _current_foreground,
    )


def cached_name_text(entry: CachedEntryLike, marked: bool) -> Text:
    """Render one cached directory entry with the default mDir theme."""
    prefix = MARK_PREFIX if marked else "  "
    text = Text(
        prefix
        + legacy.display_file_title(
            entry.path,
            is_directory=entry.is_directory,
        )
    )
    if marked:
        text.stylize(f"bold {MARK_FOREGROUND}")
    elif entry.is_directory:
        text.stylize(f"bold {_current_folder}")
    else:
        text.stylize(_file_color(entry.path))
    return text


def path_name_text(path: Path, marked: bool = False) -> Text:
    """Render one filesystem path without changing the original MDIR API."""
    prefix = MARK_PREFIX if marked else "  "
    text = Text(prefix + legacy.display_file_title(path))
    if marked:
        text.stylize(f"bold {MARK_FOREGROUND}")
    elif path.is_dir():
        text.stylize(f"bold {_current_folder}")
    else:
        text.stylize(_file_color(path))
    return text


def install_file_colors(theme: Theme | None = None) -> None:
    """Install the palette on both cached and legacy file-pane renderers."""
    global _current_foreground
    global _current_folder
    global _current_executable
    global _current_marked
    global _current_theme_name
    global _current_extension_colors

    from .file_pane import EditablePathFilePane

    if theme is None:
        _current_foreground = FOREGROUND
        _current_folder = FOLDER
        _current_executable = EXECUTABLE
        _current_marked = MARKED
        _current_theme_name = THEME_NAME
        _current_extension_colors = {}
    else:
        colors = theme.to_color_system().generate()
        _current_foreground = colors.get("foreground", FOREGROUND)
        _current_folder = colors.get("accent", FOLDER)
        _current_executable = colors.get("success", EXECUTABLE)
        _current_marked = colors.get("warning", MARKED)
        _current_theme_name = theme.name
        if theme.name == OLD_M_THEME_NAME:
            # Historical Mdir used extension colors as a visual shortcut.
            # Preserve that convention for the retro theme only.
            _current_extension_colors = {
                ".exe": "#55ff55",
                ".msi": "#55ff55",
                ".com": "#55ffff",
                ".bat": "#ffff55",
                ".cmd": "#ffff55",
                ".ps1": "#ff55ff",
                ".zip": "#ff55ff",
                ".rar": "#ff55ff",
                ".7z": "#ff55ff",
            }
        elif theme.name == NORTON_THEME_NAME:
            # Original NC uses a mainly cyan file list on royal blue.
            _current_extension_colors = {}
        else:
            _current_extension_colors = {}

    legacy.PARENT_DIRECTORY_STYLE = f"bold {_current_foreground}"
    legacy.file_name_text = path_name_text
    EditablePathFilePane._name_text = staticmethod(cached_name_text)


MDIR_THEME_CSS = f"""
Screen {{
    background: $background;
    color: $foreground;
}}

Header {{
    background: $mdir-toolbar-background;
    color: $mdir-toolbar-foreground;
}}

#panes,
.pane-wrap {{
    background: $background;
}}

FilePane {{
    border: solid $mdir-border;
    background: $background;
}}

/* Strongly highlight the working side, not the passive side. */
FilePane.active {{
    border: solid $mdir-active-border;
}}

/* Keep the existing green path bar and built-in light theme untouched.
   Retro-only overrides are deliberately scoped to skin classes on each pane. */
FilePane.skin-original,
FilePane.skin-norton {{
    border: solid $mdir-border;
    background: $mdir-list-background;
}}

FilePane.skin-original.active,
FilePane.skin-norton.active {{
    border: solid $mdir-active-border;
}}

FilePane.skin-original DirectoryPathInput.pane_path,
FilePane.skin-original.active DirectoryPathInput.pane_path,
FilePane.skin-original DirectoryPathInput.pane_path:focus,
FilePane.skin-norton DirectoryPathInput.pane_path,
FilePane.skin-norton.active DirectoryPathInput.pane_path,
FilePane.skin-norton DirectoryPathInput.pane_path:focus {{
    background: $mdir-path-background;
    color: $mdir-path-foreground;
    border: none;
}}

FilePane.skin-original .recent-folder-path-button,
FilePane.skin-original.active .recent-folder-path-button,
FilePane.skin-norton .recent-folder-path-button,
FilePane.skin-norton.active .recent-folder-path-button {{
    background: $mdir-path-background;
    color: $mdir-path-foreground;
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

FilePane.skin-original DataTable,
FilePane.skin-norton DataTable,
FilePane.skin-original DataTable > .datatable--odd-row,
FilePane.skin-original DataTable > .datatable--even-row,
FilePane.skin-original DataTable > .datatable--fixed,
FilePane.skin-norton DataTable > .datatable--odd-row,
FilePane.skin-norton DataTable > .datatable--even-row,
FilePane.skin-norton DataTable > .datatable--fixed {{
    background: $mdir-list-background;
}}

FilePane DataTable > .datatable--header {{
    background: $surface-lighten-1;
    color: $foreground;
    text-style: bold;
}}

FilePane.skin-original DataTable > .datatable--header,
FilePane.skin-norton DataTable > .datatable--header {{
    background: $mdir-header-background;
    color: $mdir-header-foreground;
    text-style: bold;
}}

FilePane DataTable > .datatable--cursor {{
    background: $mdir-inactive-background;
    color: $mdir-inactive-foreground;
    text-style: none;
}}

FilePane.active DataTable > .datatable--cursor {{
    background: $mdir-cursor-background;
    color: $mdir-selection-foreground;
    text-style: bold;
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
    /* A one-row summary cannot also contain a Textual border: the border
       consumes its only content row and hides Capacity / Files / Folders. */
    border-top: none;
}}

FilePane .pane_info {{
    background: $background;
    color: $foreground;
    /* Keep all three detail rows (Name, metadata, and Path) visible. */
    border-top: none;
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
