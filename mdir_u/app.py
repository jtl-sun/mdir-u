from __future__ import annotations

import ctypes
import inspect
import os
import subprocess
import sys
import time
import webbrowser
from ctypes import wintypes
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, HorizontalScroll, Vertical
from textual.timer import Timer
from textual.widgets import Button, DataTable, Footer, Header, Static

from .fast_app import FastFileManagerApp, LargeDirectoryFilePane
from . import __version__
from .platform_support import (
    filesystem_usage_text,
    locations,
    open_with_default_app,
    shell_executable,
)
from .preview.document import (
    DocumentPreviewPanel,
    PREVIEW_EXTENSIONS,
    can_preview,
)
from .text_actions import (
    DEFAULT_EDIT_LIMIT,
    DEFAULT_VIEW_LIMIT,
    SafeTextDecision,
    format_file_size,
    inspect_safe_text_file,
)
from .shortcuts import (
    MAX_SHORTCUTS,
    ShortcutDefinition,
    expand_shortcut_text,
    load_shortcuts,
    save_shortcuts,
    shortcut_config_path,
)
from .keymap import load_keymap, save_keymap
from .theme import (
    THEME_NAME,
    TOTAL_COMMANDER_CSS,
    TOTAL_COMMANDER_THEME,
    install_file_colors,
)
from .ui.dialogs import CompactDriveScreen


VERSION = __version__
HOTKEY_POLL_SECONDS = 0.04
HOTKEY_DEDUP_SECONDS = 0.22
VK_CONTROL = 0x11
VK_F3 = 0x72

install_file_colors()

if TYPE_CHECKING:
    from .preview.native import NativePreviewController, PaneLayout


class MDirApp(FastFileManagerApp):
    """MDIR-U for Ubuntu and other modern terminal environments."""

    TITLE = f"MDIR-U {VERSION}"
    SUB_TITLE = "Dual Pane File Manager"
    CSS = FastFileManagerApp.CSS + """
    #document_preview {
        display: none;
    }

    #shortcut_bar {
        width: 100%;
        height: 2;
        min-height: 2;
        max-height: 2;
        padding: 0;
        background: $panel;
        scrollbar-size-horizontal: 1;
    }

    #shortcut_bar Button {
        height: 2;
        min-height: 2;
        min-width: 8;
        width: auto;
        margin: 0 1 0 0;
        padding: 0 1;
        border: none;
        background: $surface;
        color: $foreground;
        content-align: center middle;
    }

    #shortcut_bar Button:hover {
        background: $primary;
        color: $text-primary;
    }

    #shortcut_edit {
        color: $accent;
        text-style: bold;
    }

    #shortcut_reload {
        color: $success;
    }

    #right_wrap.preview-mode #right {
        display: none;
    }

    #right_wrap.preview-mode #ai_panel {
        display: none;
    }

    #right_wrap.preview-mode #right_drive_bar,
    #right_wrap.preview-mode #right_drive_info {
        display: block;
    }

    #right_wrap.preview-mode #document_preview {
        display: block;
        width: 100%;
        height: 1fr;
        min-height: 0;
    }
    """ + TOTAL_COMMANDER_CSS
    BINDINGS = FastFileManagerApp.BINDINGS + [
        Binding(
            "ctrl+f3",
            "toggle_preview",
            "Preview",
            show=True,
            priority=True,
            id="mdir.preview",
        ),
    ]

    def __init__(self) -> None:
        self.preview_enabled = False
        self.preview_mode = False
        self._ctrl_f3_latched = False
        self._last_preview_toggle = -1.0
        self._terminal_window_handle = 0
        self._hotkey_timer: Optional[Timer] = None
        self._preview_layout_timer: Optional[Timer] = None
        self._native_preview: Optional["NativePreviewController"] = None
        self.shortcuts = load_shortcuts()
        self.shortcut_project = Path(__file__).resolve().parent.parent
        super().__init__()
        self.user_keymap = load_keymap()
        self.set_keymap(self.user_keymap)
        self.register_theme(TOTAL_COMMANDER_THEME)
        self.theme = THEME_NAME

    @property
    def native_preview(self) -> "NativePreviewController":
        """Create the Windows overlay only when Preview is first requested."""
        if self._native_preview is None:
            from .preview.native import NativePreviewController

            self._native_preview = NativePreviewController(
                self,
                open_callback=self._native_open_document,
                full_view_callback=self._native_full_view,
                files_callback=self._native_restore_files,
            )
        return self._native_preview

    def _watch_theme(self, theme_name: str) -> None:
        """Apply theme colors to CSS, file cells, and native Preview."""
        super()._watch_theme(theme_name)
        install_file_colors(self.current_theme)
        if self.is_running:
            native_preview = self._native_preview
            if native_preview is not None:
                native_preview.update_theme()
            self.call_after_refresh(self._refresh_themed_file_rows)

    def _refresh_themed_file_rows(self) -> None:
        """Rebuild cached cells without another filesystem scan."""
        for pane in (self.left, self.right):
            if not getattr(pane, "initial_listing_complete", False):
                continue
            selected = pane.selected_path()
            keep_name = selected.name if selected is not None else None
            pane._render_cached_rows(keep_name)

    def compose(self) -> ComposeResult:
        yield Header()
        with HorizontalScroll(id="shortcut_bar"):
            yield Button(
                "Edit Links",
                id="shortcut_edit",
                tooltip="Edit the MDIR-U shortcut configuration",
            )
            for index in range(MAX_SHORTCUTS):
                shortcut = (
                    self.shortcuts[index]
                    if index < len(self.shortcuts)
                    else None
                )
                yield Button(
                    shortcut.label if shortcut else "",
                    id=f"shortcut_{index}",
                    classes="shortcut-button",
                    tooltip=(
                        self._shortcut_tooltip(shortcut)
                        if shortcut
                        else ""
                    ),
                )
            yield Button(
                "Reload",
                id="shortcut_reload",
                tooltip="Reload shortcuts after editing the JSON file",
            )
        with Horizontal(id="panes"):
            with Vertical(id="left_wrap", classes="pane-wrap"):
                with Horizontal(id="left_drive_bar", classes="drive-bar"):
                    yield from self._drive_buttons("left")
                yield Static("", id="left_drive_info", classes="drive-info")
                yield LargeDirectoryFilePane(
                    "left",
                    self.left_start,
                    self.column_widths,
                    self.show_hidden_system,
                )

            with Vertical(id="right_wrap", classes="pane-wrap"):
                with Horizontal(id="right_drive_bar", classes="drive-bar"):
                    yield from self._drive_buttons("right")
                yield Static("", id="right_drive_info", classes="drive-info")
                yield LargeDirectoryFilePane(
                    "right",
                    self.right_start,
                    self.column_widths,
                    self.show_hidden_system,
                )
                yield DocumentPreviewPanel(id="document_preview")

        yield Static("", id="status")
        yield Footer()
        yield Static(
            f"{self.TITLE}\nStarting file panels...",
            id="startup_cover",
        )

    @staticmethod
    def _drive_buttons(side: str):
        prefix = "l" if side == "left" else "r"
        label = side.upper()
        for key, text in (
            ("root", "Root"),
            ("home", "Home"),
            ("mnt", "Mnt"),
            ("media", "Media"),
        ):
            yield Button(
                text,
                id=f"{prefix}location_{key}",
                classes="drive-button",
                tooltip=f"Switch {label} pane to {text}",
            )
        yield Button(
            "Hidden",
            id=f"{side}_hidden_toggle",
            classes="hidden-toggle",
            tooltip="Show or hide Hidden/System files",
        )

    @property
    def document_preview(self) -> DocumentPreviewPanel:
        return self.query_one("#document_preview", DocumentPreviewPanel)

    def on_mount(self) -> None:
        super().on_mount()
        self._sync_shortcut_buttons()
        self.document_preview.disabled = True
        if os.name == "nt":
            self._terminal_window_handle = self._active_window_handle()
            self._hotkey_timer = self.set_interval(
                HOTKEY_POLL_SECONDS,
                self._poll_ctrl_f3,
            )
        self.update_drive_bar()

    @staticmethod
    def _shortcut_tooltip(shortcut: ShortcutDefinition) -> str:
        return f"{shortcut.kind.title()}: {shortcut.target}"

    def _sync_shortcut_buttons(self) -> None:
        """Update fixed shortcut slots without rebuilding the widget tree."""
        for index in range(MAX_SHORTCUTS):
            button = self.query_one(f"#shortcut_{index}", Button)
            if index < len(self.shortcuts):
                shortcut = self.shortcuts[index]
                button.label = shortcut.label
                button.tooltip = self._shortcut_tooltip(shortcut)
                button.display = True
            else:
                button.display = False

    def _expanded_shortcut_text(self, value: str) -> str:
        return expand_shortcut_text(
            value,
            current=self.active.current_path,
            left=self.left.current_path,
            right=self.right.current_path,
            project=self.shortcut_project,
            selected=self.active.selected_path(),
            left_selected=self.left.selected_path(),
            right_selected=self.right.selected_path(),
        )

    def _shortcut_pane(self, shortcut: ShortcutDefinition):
        if shortcut.pane == "left":
            return self.left
        if shortcut.pane == "right":
            return self.right
        return self.active

    def _open_shortcut_folder(self, shortcut: ShortcutDefinition) -> None:
        target = Path(self._expanded_shortcut_text(shortcut.target))
        try:
            target = target.resolve()
            if not target.is_dir():
                raise NotADirectoryError("directory does not exist")
        except (OSError, RuntimeError) as exc:
            self.set_status(f"Shortcut folder unavailable: {target} ({exc})")
            return

        pane = self._shortcut_pane(shortcut)
        side = "left" if pane is self.left else "right"
        self.set_active(side)
        self.switch_pane_to_location(pane, target)
        self.set_status(f"Shortcut: {shortcut.label} -> {target}")

    def _launch_shortcut_process(
        self,
        shortcut: ShortcutDefinition,
        *,
        command: bool = False,
    ) -> None:
        target = self._expanded_shortcut_text(shortcut.target)
        working_directory = str(self.active.current_path)
        if command:
            if os.name == "nt":
                arguments = ["powershell.exe", "-NoExit", "-Command", target]
            else:
                executable = shell_executable() or "/bin/sh"
                arguments = [executable, "-lc", target]
        else:
            arguments = [
                target,
                *(self._expanded_shortcut_text(arg) for arg in shortcut.args),
            ]
        process_options = (
            {"creationflags": subprocess.CREATE_NEW_CONSOLE}
            if os.name == "nt"
            else {"start_new_session": True}
        )
        subprocess.Popen(
            arguments,
            cwd=working_directory,
            **process_options,
        )
        self.set_status(f"Launched shortcut: {shortcut.label}")

    async def _run_shortcut_action(self, shortcut: ShortcutDefinition) -> None:
        allowed_actions = {
            "toggle_ai_terminal",
            "toggle_preview",
            "search",
            "powershell_here",
            "refresh_all",
            "hidden_system",
        }
        if shortcut.target not in allowed_actions:
            raise ValueError(f"unsupported action: {shortcut.target}")
        method = getattr(self, f"action_{shortcut.target}")
        result = method()
        if inspect.isawaitable(result):
            await result

    async def _activate_shortcut(self, shortcut: ShortcutDefinition) -> None:
        try:
            if shortcut.kind == "folder":
                self._open_shortcut_folder(shortcut)
            elif shortcut.kind == "file":
                target = Path(self._expanded_shortcut_text(shortcut.target))
                if not target.is_file():
                    raise FileNotFoundError(target)
                open_with_default_app(target)
                self.set_status(f"Opened shortcut: {shortcut.label}")
            elif shortcut.kind == "program":
                self._launch_shortcut_process(shortcut)
            elif shortcut.kind == "command":
                self._launch_shortcut_process(shortcut, command=True)
            elif shortcut.kind == "web":
                target = self._expanded_shortcut_text(shortcut.target)
                if not webbrowser.open(target, new=2):
                    raise OSError("the default browser did not accept the URL")
                self.set_status(f"Opened website: {shortcut.label}")
            elif shortcut.kind == "action":
                await self._run_shortcut_action(shortcut)
        except Exception as exc:
            self.set_status(f"Shortcut failed: {shortcut.label} ({exc})")

    def _open_link_manager(self) -> None:
        from .ui.shortcuts import ShortcutManagerScreen

        def links_edited(
            shortcuts: Optional[list[ShortcutDefinition]],
        ) -> None:
            if shortcuts is None:
                self.set_status("Link editing cancelled.")
                self.set_active(self.active_side)
                return
            try:
                config_path = save_shortcuts(shortcuts)
                self.shortcuts = shortcuts
                self._sync_shortcut_buttons()
                self.set_status(
                    f"Saved {len(shortcuts)} link(s): {config_path}"
                )
            except Exception as exc:
                self.set_status(f"Could not save links: {exc}")
            self.set_active(self.active_side)

        self.push_screen(
            ShortcutManagerScreen(
                self.shortcuts,
                self.active.current_path,
            ),
            links_edited,
        )

    def _open_key_manager(self) -> None:
        from .ui.options import KeyManagerScreen

        def keys_edited(keymap: Optional[dict[str, str]]) -> None:
            if keymap is None:
                self.set_status("Key editing cancelled.")
                self.set_active(self.active_side)
                return
            try:
                config_path = save_keymap(keymap)
                self.user_keymap = keymap
                self.set_keymap(keymap)
                self.set_status(f"Saved custom keys: {config_path}")
            except Exception as exc:
                self.set_status(f"Could not save keys: {exc}")
            self.set_active(self.active_side)

        self.push_screen(KeyManagerScreen(self.user_keymap), keys_edited)

    def action_options(self) -> None:
        from .ui.options import OptionsScreen

        def option_selected(option: Optional[str]) -> None:
            if option == "keys":
                self._open_key_manager()
            elif option == "links":
                self._open_link_manager()
            elif option == "theme":
                self.action_change_theme()
            elif option == "help":
                readme_path = self._readme_path()
                if readme_path.is_file():
                    self.push_screen(self.VIEWER_SCREEN(readme_path))
                else:
                    self.set_status(f"README.md not found: {readme_path}")
            else:
                self.set_active(self.active_side)

        self.push_screen(OptionsScreen(), option_selected)

    def _readme_path(self) -> Path:
        """Locate the guide in source, wheel, or portable installations."""
        candidates = (
            self.shortcut_project / "README.md",
            Path(sys.prefix) / "share" / "mdir-u" / "README.md",
            Path(sys.executable).resolve().parent / "README.md",
        )
        return next((path for path in candidates if path.is_file()), candidates[0])

    @on(Button.Pressed, "#shortcut_bar Button")
    async def shortcut_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        event.stop()

        if button_id == "shortcut_edit":
            self._open_link_manager()
            return

        if button_id == "shortcut_reload":
            self.shortcuts = load_shortcuts()
            self._sync_shortcut_buttons()
            self.set_status(
                f"Reloaded {len(self.shortcuts)} shortcut(s) from "
                f"{shortcut_config_path()}"
            )
            return

        if not button_id.startswith("shortcut_"):
            return
        try:
            index = int(button_id.removeprefix("shortcut_"))
            shortcut = self.shortcuts[index]
        except (ValueError, IndexError):
            return
        await self._activate_shortcut(shortcut)

    def _location_for_key(self, key: str) -> Path | None:
        mapping = {
            "root": Path("/"),
            "home": Path.home(),
            "mnt": Path("/mnt"),
            "media": Path("/media"),
        }
        candidate = mapping.get(key)
        return candidate if candidate is not None and candidate.is_dir() else None

    @on(Button.Pressed)
    def location_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        for prefix, pane, side in (
            ("llocation_", self.left, "left"),
            ("rlocation_", self.right, "right"),
        ):
            if not button_id.startswith(prefix):
                continue
            target = self._location_for_key(button_id.removeprefix(prefix))
            if target is None:
                self.set_status("That location is not available.")
            else:
                self.set_active(side)
                self.switch_pane_to_location(pane, target)
            event.stop()
            return

    def switch_pane_to_location(self, pane, target: Path) -> None:
        try:
            target = target.expanduser().resolve()
            if not target.is_dir():
                raise NotADirectoryError(target)
            pane.current_path = target
            pane.marked.clear()
            pane.refresh_listing()
            pane.update_summary()
            self._save_paths()
            self.update_drive_bar()
            pane.table.focus()
            self.set_status(f"{pane.id.upper()} pane: {target}")
        except (OSError, RuntimeError) as exc:
            self.set_status(f"Could not open location: {exc}")

    def update_drive_bar(self) -> None:
        if os.name == "nt":
            super().update_drive_bar()
            return
        for pane, prefix, info_id in (
            (self.left, "llocation_", "#left_drive_info"),
            (self.right, "rlocation_", "#right_drive_info"),
        ):
            current = pane.current_path
            for key in ("root", "home", "mnt", "media"):
                try:
                    button = self.query_one(f"#{prefix}{key}", Button)
                    target = self._location_for_key(key)
                    button.display = target is not None
                    button.set_class(
                        target is not None and current == target,
                        "current-drive",
                    )
                except Exception:
                    pass
            try:
                self.query_one(info_id, Static).update(
                    filesystem_usage_text(current)
                )
            except Exception:
                pass

    def _prompt_drive(self, pane) -> None:
        choices = [
            (f"{item.label}  {item.path}", str(item.path))
            for item in locations()
        ]
        current = str(pane.current_path)

        def selected(value: str | None) -> None:
            if value:
                self.switch_pane_to_location(pane, Path(value))
            else:
                self.set_status("Location selection cancelled.")

        self.push_screen(CompactDriveScreen(choices, current), selected)

    @staticmethod
    def _active_window_handle() -> int:
        if os.name != "nt":
            return 0
        try:
            get_foreground = ctypes.windll.user32.GetForegroundWindow
            get_foreground.restype = wintypes.HWND
            return int(get_foreground() or 0)
        except Exception:
            return 0

    @staticmethod
    def _read_ctrl_f3_pressed() -> bool:
        if os.name != "nt":
            return False
        try:
            get_key_state = ctypes.windll.user32.GetAsyncKeyState
            get_key_state.argtypes = [ctypes.c_int]
            get_key_state.restype = ctypes.c_short
            return bool(
                get_key_state(VK_CONTROL) & 0x8000
                and get_key_state(VK_F3) & 0x8000
            )
        except Exception:
            return False

    def _poll_ctrl_f3(self) -> None:
        pressed = self._read_ctrl_f3_pressed()
        if not pressed:
            self._ctrl_f3_latched = False
            return
        if self._ctrl_f3_latched:
            return
        self._ctrl_f3_latched = True
        if (
            self._terminal_window_handle
            and self._active_window_handle() == self._terminal_window_handle
        ):
            self.action_toggle_preview()

    def _native_preview_layout(self) -> Optional[PaneLayout]:
        if os.name != "nt":
            return None
        from .preview.native import PaneLayout

        try:
            widget = self.document_preview if self.preview_mode else self.right
            region = widget.region
            if region.width <= 0 or region.height <= 0:
                region = self.right.region
            if region.width <= 0 or region.height <= 0:
                return None
            return PaneLayout(
                x=region.x,
                y=region.y,
                width=region.width,
                height=region.height,
                columns=max(1, self.size.width),
                rows=max(1, self.size.height),
            )
        except Exception:
            return None

    def _sync_native_preview_layout(self) -> None:
        if not self.preview_mode:
            return
        pane_layout = self._native_preview_layout()
        if pane_layout is not None:
            self.native_preview.update_layout(pane_layout)

    def _schedule_preview_layout(self, delay: float) -> None:
        self.call_after_refresh(self._sync_native_preview_layout)
        if self._preview_layout_timer is not None:
            self._preview_layout_timer.stop()
        self._preview_layout_timer = self.set_timer(
            delay,
            self._sync_native_preview_layout,
        )

    def _show_document_preview(self, path: Path) -> None:
        if not self.preview_enabled or self.ai_mode or not can_preview(path):
            return

        pane_layout = self._native_preview_layout()
        shown = (
            self.native_preview.show(path, pane_layout=pane_layout)
            if os.name == "nt"
            else False
        )
        wrap = self.query_one("#right_wrap", Vertical)
        self.preview_mode = True
        self.right.disabled = True
        wrap.set_class(False, "ai-mode")
        wrap.set_class(True, "preview-mode")

        if shown:
            self.document_preview.cancel()
            self.document_preview.disabled = True
            self.document_preview.canvas.update(
                f"Loading native preview...\n\n{path.name}"
            )
            self.set_status(
                f"Preview: {path.name} | background loading | "
                "Wheel: zoom | Drag: pan | Ctrl+F3: on/off"
            )
        else:
            self.document_preview.disabled = False
            self.document_preview.show_path(path)
            self.set_status(
                f"Preview: {path.name} | Ctrl+F3 toggles preview | "
                "Right/Tab restores files"
            )
        self._schedule_preview_layout(0.08)

    def _hide_document_preview(
        self,
        *,
        restore_right_focus: bool = False,
        wait_for_native: bool = False,
    ) -> None:
        if self._native_preview is not None:
            self._native_preview.hide(wait=wait_for_native)
        if not self.preview_mode:
            return
        self.preview_mode = False
        self.document_preview.cancel()
        self.document_preview.disabled = True
        self.right.disabled = False
        self.query_one("#right_wrap", Vertical).set_class(
            False,
            "preview-mode",
        )
        if restore_right_focus:
            self.set_active("right")

    def _preview_current_left_selection(self) -> None:
        if self.ai_mode or not self.preview_enabled:
            return
        path = self.left.selected_path()
        if can_preview(path):
            self._show_document_preview(path)
        else:
            self._hide_document_preview(restore_right_focus=False)

    @on(DataTable.RowHighlighted)
    def preview_row_highlighted(
        self,
        event: DataTable.RowHighlighted,
    ) -> None:
        try:
            if event.data_table is self.left.table:
                self._preview_current_left_selection()
        except Exception:
            pass

    def action_toggle_preview(self) -> None:
        now = time.monotonic()
        if now - self._last_preview_toggle < HOTKEY_DEDUP_SECONDS:
            return
        self._last_preview_toggle = now

        self.preview_enabled = not self.preview_enabled
        if self.preview_enabled:
            self._preview_current_left_selection()
            if not self.preview_mode:
                self.set_status(
                    "Preview enabled. Select an image, PDF, Office, CSV, "
                    "text, or Markdown file."
                )
            self._restore_preview_file_focus()
            self.call_after_refresh(self._restore_preview_file_focus)
            self.set_timer(0.08, self._restore_preview_file_focus)
            self.set_timer(0.22, self._restore_preview_file_focus)
        else:
            self._hide_document_preview(restore_right_focus=False)
            self.set_status("Automatic document preview disabled.")

    def _restore_preview_file_focus(self) -> None:
        if not self.preview_enabled or not self.preview_mode or self.ai_mode:
            return
        if self._native_preview is not None:
            self._native_preview.restore_terminal_focus()
        self.set_active("left")
        self.left.table.refresh()
        self.left.table.focus()

    def action_focus_right(self) -> None:
        if self.preview_mode:
            self._hide_document_preview(restore_right_focus=True)
            self.set_status("Right file pane restored.")
            return
        super().action_focus_right()

    def action_switch_pane(self) -> None:
        if self.preview_mode and self.active_side == "left":
            self._hide_document_preview(restore_right_focus=True)
            self.set_status("Right file pane restored.")
            return
        super().action_switch_pane()

    async def action_toggle_ai_terminal(self) -> None:
        if self.preview_mode:
            self._hide_document_preview(restore_right_focus=False)
        await super().action_toggle_ai_terminal()

    @on(DocumentPreviewPanel.CloseRequested)
    def close_document_preview(
        self,
        event: DocumentPreviewPanel.CloseRequested,
    ) -> None:
        event.stop()
        self._hide_document_preview(restore_right_focus=True)
        self.set_status("Right file pane restored.")

    @on(DocumentPreviewPanel.FullViewRequested)
    def full_document_preview(
        self,
        event: DocumentPreviewPanel.FullViewRequested,
    ) -> None:
        event.stop()
        self.action_view()

    @on(DocumentPreviewPanel.OpenRequested)
    def open_previewed_document(
        self,
        event: DocumentPreviewPanel.OpenRequested,
    ) -> None:
        event.stop()
        path = self.left.selected_path()
        if path is None:
            return
        try:
            self.open_external_path(path)
            self.set_status(f"Opened with the default application: {path}")
        except Exception as exc:
            self.set_status(f"Could not open {path.name}: {exc}")

    def _native_full_view(self) -> None:
        self.action_view()

    def _native_open_document(self, path: Path) -> None:
        try:
            if self.preview_mode:
                self._hide_document_preview(restore_right_focus=False)
            super().open_external_path(path)
            self.set_status(f"Opened with the default application: {path}")
        except Exception as exc:
            self.set_status(f"Could not open {path.name}: {exc}")

    def open_external_path(self, path: Path) -> None:
        """Remove Preview before giving the file to another application."""
        if self.preview_mode:
            self._hide_document_preview(
                restore_right_focus=False,
                wait_for_native=True,
            )
        super().open_external_path(path)

    def _native_restore_files(self) -> None:
        self._hide_document_preview(restore_right_focus=True)
        self.set_status("Right file pane restored.")

    def _selected_action_file(self, action_name: str) -> Path | None:
        path = self.active.selected_path()
        if path is None or path.is_dir():
            self.set_status(
                f"{action_name} works on supported text files only."
            )
            return None
        return path

    def _safe_text_action_allowed(
        self,
        path: Path,
        *,
        action_name: str,
        limit: int,
    ) -> bool:
        decision = inspect_safe_text_file(path, max_bytes=limit)
        if decision.allowed:
            return True
        self.set_status(
            self._safe_text_block_message(
                path,
                action_name=action_name,
                decision=decision,
            )
        )
        return False

    @staticmethod
    def _safe_text_block_message(
        path: Path,
        *,
        action_name: str,
        decision: SafeTextDecision,
    ) -> str:
        prefix = f"{action_name} ignored: {path.name}"
        if decision.reason == "unsupported_type":
            file_type = path.suffix.lower() or "extensionless file"
            return (
                f"{prefix} ({file_type}) is not a supported text format. "
                "Use Enter or Preview instead."
            )
        if decision.reason == "too_large":
            return (
                f"{prefix} is {format_file_size(decision.size)}; "
                f"the safety limit is {format_file_size(decision.limit)}."
            )
        if decision.reason == "binary_content":
            return f"{prefix} contains binary data and was not opened."
        if decision.reason == "not_file":
            return f"{action_name} works on supported text files only."
        return f"{prefix} could not be read."

    def action_view(self) -> None:
        path = self._selected_action_file("F3 View")
        if path is None:
            return
        if not self._safe_text_action_allowed(
            path,
            action_name="F3 View",
            limit=DEFAULT_VIEW_LIMIT,
        ):
            return
        if self._native_preview is not None:
            self._native_preview.hide()
        super().action_view()

    def action_edit(self) -> None:
        path = self._selected_action_file("F4 Edit")
        if path is None:
            return
        if not self._safe_text_action_allowed(
            path,
            action_name="F4 Edit",
            limit=DEFAULT_EDIT_LIMIT,
        ):
            return
        super().action_edit()

    def on_resize(self, event: events.Resize) -> None:
        if self.preview_mode:
            self._schedule_preview_layout(0.12)

    def on_unmount(self) -> None:
        if self._preview_layout_timer is not None:
            self._preview_layout_timer.stop()
            self._preview_layout_timer = None
        if self._hotkey_timer is not None:
            self._hotkey_timer.stop()
            self._hotkey_timer = None
        if self._native_preview is not None:
            self._native_preview.shutdown()
        super().on_unmount()


def self_check() -> int:
    """Run a dependency-light structural check for the current package."""
    print(f"MDIR-U {VERSION} package self-check")
    print(f"Default theme: {THEME_NAME}")
    print("Preview starts disabled and uses bounded background rendering")
    print("F3/F4 accept bounded text files only")
    print("Large directories use cached metadata and batched row insertion")
    print("Copy, Move, and Delete use cancellable background workers")
    print(f"Top shortcut bar supports up to {MAX_SHORTCUTS} user links")
    required = {".jpg", ".png", ".pdf", ".xlsx", ".xls"}
    if not required.issubset(PREVIEW_EXTENSIONS):
        print("ERROR - required Preview formats are missing.")
        return 1
    app = MDirApp()
    if app.preview_enabled:
        print("ERROR - Preview must start disabled.")
        return 1
    if app.theme != THEME_NAME:
        print("ERROR - default theme was not installed.")
        return 1
    print("OK - MDIR-U package is ready.")
    return 0
