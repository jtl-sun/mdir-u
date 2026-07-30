from __future__ import annotations

import ctypes
import gc
import math
import os
import queue
import threading
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .document import prepare_document_source
from .header import (
    PREVIEW_BADGE_BACKGROUND,
    PREVIEW_BADGE_FOREGROUND,
    PREVIEW_BADGE_TEXT,
)
from ..theme import (
    ACCENT,
    BACKGROUND,
    FOREGROUND,
    PANEL,
    SEPARATOR,
)


class _Win32Rect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


MAX_NATIVE_IMAGE_PIXELS = 40_000_000
WHEEL_ZOOM_FACTOR = 1.20
NATIVE_COMMAND_POLL_MS = 35
NATIVE_INPUT_POLL_MS = 20
NATIVE_FOLLOW_POLL_MS = 180
PANE_TOP_INSET_MIN = 52
BOTTOM_COMMAND_AREA_INSET_MIN = 50


@dataclass(frozen=True)
class WindowRectangle:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(1, self.right - self.left)

    @property
    def height(self) -> int:
        return max(1, self.bottom - self.top)


@dataclass(frozen=True)
class ViewportRenderPlan:
    """A bounded source crop and its destination inside the preview canvas."""

    crop_box: tuple[int, int, int, int]
    display_size: tuple[int, int]
    display_position: tuple[float, float]

    @property
    def display_pixels(self) -> int:
        return self.display_size[0] * self.display_size[1]


@dataclass(frozen=True)
class PaneLayout:
    """A Textual widget rectangle expressed in terminal character cells."""

    x: int
    y: int
    width: int
    height: int
    columns: int
    rows: int


def calculate_pane_rectangle(
    terminal_grid: WindowRectangle,
    layout: PaneLayout,
) -> WindowRectangle:
    """Map a Textual cell region to its physical Windows pixel rectangle."""
    columns = max(1, int(layout.columns))
    rows = max(1, int(layout.rows))
    x1 = max(0, min(columns, int(layout.x)))
    y1 = max(0, min(rows, int(layout.y)))
    x2 = max(x1 + 1, min(columns, x1 + int(layout.width)))
    y2 = max(y1 + 1, min(rows, y1 + int(layout.height)))
    left = terminal_grid.left + round(
        terminal_grid.width * x1 / columns
    )
    top = terminal_grid.top + round(
        terminal_grid.height * y1 / rows
    )
    right = terminal_grid.left + round(
        terminal_grid.width * x2 / columns
    )
    bottom = terminal_grid.top + round(
        terminal_grid.height * y2 / rows
    )
    return WindowRectangle(left, top, right, bottom)


def calculate_terminal_grid_rectangle(
    terminal: WindowRectangle,
    *,
    bridge: Optional[WindowRectangle] = None,
    drag_bar: Optional[WindowRectangle] = None,
) -> WindowRectangle:
    """Return the character grid inside a Windows Terminal host window."""
    if bridge is None:
        frame = max(4, int(round(terminal.width * 0.004)))
        tab_height = max(32, int(round(terminal.height * 0.031)))
        return WindowRectangle(
            terminal.left + frame,
            terminal.top + frame + tab_height,
            terminal.right - frame,
            terminal.bottom - frame,
        )

    frame = max(0, bridge.left - terminal.left)
    grid_top = bridge.top
    if drag_bar is not None:
        grid_top = max(grid_top, drag_bar.bottom + frame)
    return WindowRectangle(
        bridge.left,
        grid_top,
        bridge.right,
        bridge.bottom,
    )


def calculate_viewport_render_plan(
    image_size: tuple[int, int],
    canvas_size: tuple[int, int],
    scale: float,
    offsets: tuple[float, float],
) -> Optional[ViewportRenderPlan]:
    """Crop before resizing so Tk never receives the full off-screen image."""
    image_width, image_height = image_size
    canvas_width, canvas_height = canvas_size
    scale = max(1e-9, float(scale))
    offset_x, offset_y = offsets
    projected_width = image_width * scale
    projected_height = image_height * scale

    visible_left = max(0.0, offset_x)
    visible_top = max(0.0, offset_y)
    visible_right = min(float(canvas_width), offset_x + projected_width)
    visible_bottom = min(float(canvas_height), offset_y + projected_height)
    if visible_right <= visible_left or visible_bottom <= visible_top:
        return None

    source_left = max(
        0,
        min(
            image_width - 1,
            int(math.floor((visible_left - offset_x) / scale)),
        ),
    )
    source_top = max(
        0,
        min(
            image_height - 1,
            int(math.floor((visible_top - offset_y) / scale)),
        ),
    )
    source_right = max(
        source_left + 1,
        min(
            image_width,
            int(math.ceil((visible_right - offset_x) / scale)),
        ),
    )
    source_bottom = max(
        source_top + 1,
        min(
            image_height,
            int(math.ceil((visible_bottom - offset_y) / scale)),
        ),
    )
    crop_width = source_right - source_left
    crop_height = source_bottom - source_top
    display_width = max(1, int(round(crop_width * scale)))
    display_height = max(1, int(round(crop_height * scale)))
    return ViewportRenderPlan(
        crop_box=(
            source_left,
            source_top,
            source_right,
            source_bottom,
        ),
        display_size=(display_width, display_height),
        display_position=(
            offset_x + source_left * scale,
            offset_y + source_top * scale,
        ),
    )


def calculate_preview_rectangle(
    terminal: WindowRectangle,
) -> WindowRectangle:
    """Return the right pane without covering MDIR's status and footer rows."""
    divider = 3
    top_inset = max(
        PANE_TOP_INSET_MIN,
        int(round(terminal.height * 0.045)),
    )
    bottom_inset = max(
        BOTTOM_COMMAND_AREA_INSET_MIN,
        int(round(terminal.height * 0.041)),
    )
    left = terminal.left + terminal.width // 2 + divider
    top = terminal.top + top_inset
    right = terminal.right - 4
    bottom = max(top + 120, terminal.bottom - bottom_inset)
    return WindowRectangle(left, top, right, bottom)


def maximum_safe_scale(
    image_size: tuple[int, int],
    requested_scale: float,
) -> float:
    """Limit only pathological allocations while allowing normal 1:1 views."""
    width, height = image_size
    source_pixels = max(1, width * height)
    allocation_limit = math.sqrt(MAX_NATIVE_IMAGE_PIXELS / source_pixels)
    return max(0.03, min(float(requested_scale), 8.0, allocation_limit))


class NativePreviewController:
    """Own a no-activate Tk window over the terminal's right file pane."""

    def __init__(
        self,
        app,
        *,
        full_view_callback: Optional[Callable[[], None]] = None,
        files_callback: Optional[Callable[[], None]] = None,
    ) -> None:
        self.app = app
        self.full_view_callback = full_view_callback
        self.files_callback = files_callback
        self._commands: queue.Queue[tuple[str, object]] = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._shutdown_complete = threading.Event()
        self._shutdown_lock = threading.Lock()
        self._shutdown_sent = False
        self._started_ok = False
        self._terminal_hwnd = 0
        self._preview_hwnd = 0
        native_setting = os.environ.get(
            "MDIR_NATIVE_PREVIEW",
            "1",
        ).strip().lower()
        self.available = (
            os.name == "nt"
            and native_setting not in {"0", "false", "no", "off"}
        )
        self.last_error = ""

    def _current_theme_palette(self) -> dict[str, str]:
        try:
            colors = self.app.current_theme.to_color_system().generate()
            return {
                "background": colors["background"],
                "surface": colors["surface"],
                "panel": colors["panel"],
                "foreground": colors["foreground"],
                "primary": colors["primary"],
                "separator": colors["surface-lighten-2"],
                "error": colors["error"],
            }
        except Exception:
            return {
                "background": BACKGROUND,
                "surface": "#303030",
                "panel": PANEL,
                "foreground": FOREGROUND,
                "primary": ACCENT,
                "separator": SEPARATOR,
                "error": "#ff6b7f",
            }

    def update_theme(self) -> None:
        """Apply the current Textual theme to an open native Preview."""
        if self._thread is not None:
            self._commands.put(("theme", self._current_theme_palette()))

    @staticmethod
    def _foreground_window() -> int:
        if os.name != "nt":
            return 0
        try:
            get_foreground = ctypes.windll.user32.GetForegroundWindow
            get_foreground.restype = wintypes.HWND
            return int(get_foreground() or 0)
        except Exception:
            return 0

    def start(self) -> bool:
        if not self.available:
            return False
        if self._thread is not None and self._thread.is_alive():
            return True
        self._terminal_hwnd = self._foreground_window()
        self._ready.clear()
        self._shutdown_complete.clear()
        self._shutdown_sent = False
        self._started_ok = False
        self._thread = threading.Thread(
            target=self._thread_main,
            name="MDIR-Native-Preview",
            # A Tcl interpreter must be destroyed by its owning thread before
            # Python exits. Keeping this thread non-daemon prevents Python from
            # finalizing Tcl on the main thread during a late F10 shutdown.
            daemon=False,
        )
        self._thread.start()
        self._ready.wait(timeout=0.8)
        if self._ready.is_set() and not self._started_ok:
            self.available = False
            return False
        return self._thread.is_alive()

    def _replace_pending_show(self, command: tuple[str, object]) -> None:
        retained: list[tuple[str, object]] = []
        try:
            while True:
                item = self._commands.get_nowait()
                if item[0] not in {"show", "hide"}:
                    retained.append(item)
        except queue.Empty:
            pass
        for item in retained:
            self._commands.put(item)
        self._commands.put(command)

    def show(
        self,
        path: Path,
        *,
        pane_layout: Optional[PaneLayout] = None,
    ) -> bool:
        if not self.start():
            return False
        foreground = self._foreground_window()
        if foreground and foreground != self._preview_hwnd:
            self._terminal_hwnd = foreground
        self._replace_pending_show(
            (
                "show",
                {
                    "path": str(path),
                    "terminal_hwnd": self._terminal_hwnd,
                    "pane_layout": pane_layout,
                },
            )
        )
        return True

    def update_layout(self, pane_layout: PaneLayout) -> None:
        """Update the physical target after a Textual layout or window resize."""
        if self._thread is None:
            return
        retained: list[tuple[str, object]] = []
        try:
            while True:
                item = self._commands.get_nowait()
                if item[0] != "layout":
                    retained.append(item)
        except queue.Empty:
            pass
        for item in retained:
            self._commands.put(item)
        self._commands.put(("layout", pane_layout))

    def hide(self) -> None:
        if self._thread is not None:
            self._replace_pending_show(("hide", None))

    def shutdown(self, *, timeout: float = 6.0) -> bool:
        """Stop Preview only after its Tk owner thread releases Tcl."""
        thread = self._thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            return False

        with self._shutdown_lock:
            if not self._shutdown_sent:
                self._shutdown_sent = True
                self._commands.put(("shutdown", None))

        completed = self._shutdown_complete.wait(timeout=max(0.1, timeout))
        thread.join(timeout=0.5 if completed else 0.1)
        stopped = not thread.is_alive()
        if stopped:
            self._thread = None
            self._preview_hwnd = 0
            return True

        self.last_error = (
            "Native Preview cleanup is still finishing on its owner thread."
        )
        return False

    def restore_terminal_focus(self) -> None:
        """Restore focus only when it is still on MDIR or its preview."""
        if os.name != "nt" or not self._terminal_hwnd:
            return
        foreground = self._foreground_window()
        if foreground not in {
            0,
            self._terminal_hwnd,
            self._preview_hwnd,
        }:
            return
        try:
            ctypes.windll.user32.SetForegroundWindow(
                wintypes.HWND(self._terminal_hwnd)
            )
        except Exception:
            pass

    def _invoke_app_callback(
        self,
        callback: Optional[Callable[[], None]],
    ) -> None:
        if callback is None:
            return
        try:
            self.app.call_from_thread(callback)
        except Exception:
            pass

    def _thread_main(self) -> None:
        window: Optional[_NativePreviewWindow] = None
        try:
            window = _NativePreviewWindow(
                self._commands,
                terminal_hwnd=self._terminal_hwnd,
                theme_palette=self._current_theme_palette(),
                full_view_callback=lambda: self._invoke_app_callback(
                    self.full_view_callback
                ),
                files_callback=lambda: self._invoke_app_callback(
                    self.files_callback
                ),
            )
            self._preview_hwnd = window._window_hwnd()
            self._started_ok = True
            self._ready.set()
            window.run()
        except Exception as exc:
            self.last_error = str(exc)
            self.available = False
            self._ready.set()
        finally:
            self._preview_hwnd = 0
            # Tk widgets and ImageTk objects form reference cycles. Collect
            # them here, on the same thread that created Tcl, rather than
            # allowing Python's main thread to finalize them at process exit.
            window = None
            gc.collect()
            self._shutdown_complete.set()


class _NativePreviewWindow:
    """Tk implementation kept entirely inside its dedicated GUI thread."""

    def __init__(
        self,
        commands: queue.Queue[tuple[str, object]],
        *,
        terminal_hwnd: int,
        theme_palette: Optional[dict[str, str]] = None,
        full_view_callback: Callable[[], None],
        files_callback: Callable[[], None],
    ) -> None:
        import tkinter as tk

        self.tk = tk
        self.commands = commands
        self.terminal_hwnd = int(terminal_hwnd)
        self.pane_layout: Optional[PaneLayout] = None
        self.full_view_callback = full_view_callback
        self.files_callback = files_callback
        self.theme_palette = theme_palette or {
            "background": BACKGROUND,
            "surface": "#303030",
            "panel": PANEL,
            "foreground": FOREGROUND,
            "primary": ACCENT,
            "separator": SEPARATOR,
            "error": "#ff6b7f",
        }
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.configure(bg=self.theme_palette["background"])

        self.document_source = None
        self.source_image = None
        self.path: Optional[Path] = None
        self.kind = ""
        self.detail = ""
        self.scale = 1.0
        self.fit_scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.photo = None
        self.canvas_image = None
        self.visible = False
        self._shutdown_requested = False
        self._drag_origin: Optional[tuple[int, int, float, float]] = None
        self._render_after = None
        self._fit_after = None
        self._last_geometry: Optional[WindowRectangle] = None
        self._canvas_screen_rectangle: Optional[WindowRectangle] = None
        self._mouse_hook = 0
        self._mouse_hook_callback = None
        self._mouse_hook_thread: Optional[threading.Thread] = None
        self._mouse_hook_thread_id = 0
        self._mouse_hook_ready = threading.Event()
        self._mouse_hook_stop = threading.Event()
        self._native_input: queue.Queue[
            tuple[int, int, int]
        ] = queue.Queue(maxsize=64)
        self._load_generation = 0
        self._load_requests: queue.Queue[
            Optional[tuple[int, Path]]
        ] = queue.Queue()
        self._load_results: queue.Queue[
            tuple[
                int,
                Path,
                object,
                Optional[Exception],
                threading.Event,
            ]
        ] = queue.Queue()
        self._loader_stop = threading.Event()
        self._loader_thread = threading.Thread(
            target=self._loader_main,
            name="MDIR-Native-Image-Loader",
            daemon=True,
        )
        self._loader_thread.start()

        self._build_ui()
        self.root.update_idletasks()
        self._apply_windows_styles()
        self.root.after(NATIVE_COMMAND_POLL_MS, self._poll_commands)
        self.root.after(NATIVE_COMMAND_POLL_MS, self._poll_load_results)
        self.root.after(NATIVE_INPUT_POLL_MS, self._poll_native_input)
        self.root.after(NATIVE_FOLLOW_POLL_MS, self._follow_terminal)

    def _build_ui(self) -> None:
        tk = self.tk
        toolbar = tk.Frame(
            self.root,
            bg=self.theme_palette["surface"],
            height=38,
            highlightbackground=self.theme_palette["separator"],
            highlightthickness=1,
        )
        self.toolbar = toolbar
        toolbar.pack(side="top", fill="x")
        toolbar.pack_propagate(False)
        self.preview_badge = tk.Label(
            toolbar,
            text=f" {PREVIEW_BADGE_TEXT} ",
            bg=PREVIEW_BADGE_BACKGROUND,
            fg=PREVIEW_BADGE_FOREGROUND,
            font=("Cascadia Mono", 10, "bold"),
            anchor="center",
            padx=5,
        )
        self.preview_badge.pack(
            side="left",
            fill="y",
            padx=(5, 4),
            pady=4,
        )
        self.title_label = tk.Label(
            toolbar,
            text="",
            bg=self.theme_palette["surface"],
            fg=self.theme_palette["foreground"],
            font=("Cascadia Mono", 10, "bold"),
            anchor="w",
            padx=4,
        )
        self.title_label.pack(side="left", fill="both", expand=True)

        buttons = (
            ("Fit", self.fit),
            ("1:1", self.native_size),
            ("F3", self._request_full_view),
            ("Open", self.open_original),
            ("Files", self._request_files),
        )
        self.toolbar_buttons = []
        for label, command in buttons:
            button = tk.Button(
                toolbar,
                text=label,
                command=command,
                bg=self.theme_palette["surface"],
                fg=self.theme_palette["foreground"],
                activebackground=self.theme_palette["primary"],
                activeforeground="white",
                relief="flat",
                borderwidth=0,
                font=("Cascadia Mono", 10, "bold"),
                padx=10,
            )
            button.pack(side="left", fill="y", padx=(1, 0))
            self.toolbar_buttons.append(button)

        self.canvas = tk.Canvas(
            self.root,
            bg=self.theme_palette["background"],
            highlightthickness=0,
            cursor="crosshair",
        )
        self.canvas.pack(side="top", fill="both", expand=True)
        self.status_label = tk.Label(
            self.root,
            text="Wheel: zoom | Drag: pan | Fit | 1:1",
            bg=self.theme_palette["panel"],
            fg=self.theme_palette["foreground"],
            font=("Cascadia Mono", 9),
            anchor="w",
            padx=8,
            pady=3,
        )
        self.status_label.pack(side="bottom", fill="x")

        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<ButtonPress-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)
        self.canvas.bind("<Configure>", self._canvas_resized)

    def _apply_theme_palette(self, palette: dict[str, str]) -> None:
        self.theme_palette = palette
        self.root.configure(bg=palette["background"])
        self.toolbar.configure(
            bg=palette["surface"],
            highlightbackground=palette["separator"],
        )
        self.title_label.configure(
            bg=palette["surface"],
            fg=palette["foreground"],
        )
        for button in self.toolbar_buttons:
            button.configure(
                bg=palette["surface"],
                fg=palette["foreground"],
                activebackground=palette["primary"],
            )
        self.canvas.configure(bg=palette["background"])
        self.status_label.configure(
            bg=palette["panel"],
            fg=palette["foreground"],
        )
        self._schedule_render()

    def _window_hwnd(self) -> int:
        if os.name != "nt":
            return 0
        try:
            hwnd = int(self.root.winfo_id())
            get_ancestor = ctypes.windll.user32.GetAncestor
            get_ancestor.argtypes = [wintypes.HWND, wintypes.UINT]
            get_ancestor.restype = wintypes.HWND
            root_hwnd = int(get_ancestor(hwnd, 2) or 0)
            return root_hwnd or hwnd
        except Exception:
            return 0

    def _apply_windows_styles(self) -> None:
        if os.name != "nt":
            return
        try:
            user32 = ctypes.windll.user32
            hwnd = self._window_hwnd()
            if not hwnd:
                return
            GWL_EXSTYLE = -20
            GWLP_HWNDPARENT = -8
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_NOACTIVATE = 0x08000000
            style = int(user32.GetWindowLongW(hwnd, GWL_EXSTYLE))
            user32.SetWindowLongW(
                hwnd,
                GWL_EXSTYLE,
                style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            )
            if self.terminal_hwnd:
                if ctypes.sizeof(ctypes.c_void_p) == 8:
                    set_owner = user32.SetWindowLongPtrW
                    set_owner.argtypes = [
                        wintypes.HWND,
                        ctypes.c_int,
                        ctypes.c_void_p,
                    ]
                    set_owner.restype = ctypes.c_void_p
                    set_owner(
                        wintypes.HWND(hwnd),
                        GWLP_HWNDPARENT,
                        ctypes.c_void_p(self.terminal_hwnd),
                    )
                else:
                    user32.SetWindowLongW(
                        hwnd,
                        GWLP_HWNDPARENT,
                        self.terminal_hwnd,
                    )
        except Exception:
            pass

    def _terminal_rectangle(self) -> Optional[WindowRectangle]:
        if os.name != "nt" or not self.terminal_hwnd:
            return None

        rectangle = _Win32Rect()
        user32 = ctypes.windll.user32
        is_window = user32.IsWindow
        is_window.argtypes = [wintypes.HWND]
        is_window.restype = wintypes.BOOL
        if not is_window(wintypes.HWND(self.terminal_hwnd)):
            return None
        is_iconic = user32.IsIconic
        is_iconic.argtypes = [wintypes.HWND]
        is_iconic.restype = wintypes.BOOL
        if is_iconic(wintypes.HWND(self.terminal_hwnd)):
            return None
        get_window_rect = user32.GetWindowRect
        get_window_rect.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(_Win32Rect),
        ]
        get_window_rect.restype = wintypes.BOOL
        if not get_window_rect(
            wintypes.HWND(self.terminal_hwnd),
            ctypes.byref(rectangle),
        ):
            return None
        return WindowRectangle(
            rectangle.left,
            rectangle.top,
            rectangle.right,
            rectangle.bottom,
        )

    @staticmethod
    def _window_class(hwnd: int) -> str:
        if os.name != "nt" or not hwnd:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetClassNameW(
                wintypes.HWND(hwnd),
                buffer,
                len(buffer),
            )
            return buffer.value
        except Exception:
            return ""

    @staticmethod
    def _window_rectangle(hwnd: int) -> Optional[WindowRectangle]:
        if os.name != "nt" or not hwnd:
            return None

        rectangle = _Win32Rect()
        get_window_rect = ctypes.windll.user32.GetWindowRect
        get_window_rect.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(_Win32Rect),
        ]
        get_window_rect.restype = wintypes.BOOL
        if not get_window_rect(
            wintypes.HWND(hwnd),
            ctypes.byref(rectangle),
        ):
            return None
        return WindowRectangle(
            rectangle.left,
            rectangle.top,
            rectangle.right,
            rectangle.bottom,
        )

    def _terminal_grid_rectangle(
        self,
        terminal: WindowRectangle,
    ) -> WindowRectangle:
        """Locate Windows Terminal's text grid below its XAML tab strip."""
        if os.name != "nt" or not self.terminal_hwnd:
            return terminal

        bridge: Optional[WindowRectangle] = None
        drag_bar: Optional[WindowRectangle] = None
        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HWND,
            wintypes.LPARAM,
        )

        @callback_type
        def collect(child, parameter):
            nonlocal bridge, drag_bar
            child_handle = int(child or 0)
            class_name = self._window_class(child_handle)
            rectangle = self._window_rectangle(child_handle)
            if rectangle is None:
                return True
            if class_name == "Windows.UI.Composition.DesktopWindowContentBridge":
                if (
                    bridge is None
                    or rectangle.width * rectangle.height
                    > bridge.width * bridge.height
                ):
                    bridge = rectangle
            elif class_name == "DRAG_BAR_WINDOW_CLASS":
                drag_bar = rectangle
            return True

        try:
            ctypes.windll.user32.EnumChildWindows(
                wintypes.HWND(self.terminal_hwnd),
                collect,
                0,
            )
        except Exception:
            bridge = None

        return calculate_terminal_grid_rectangle(
            terminal,
            bridge=bridge,
            drag_bar=drag_bar,
        )

    def _position_over_terminal(self) -> None:
        if self.visible:
            terminal = self._terminal_rectangle()
            if terminal is None:
                self.root.withdraw()
            else:
                if self.pane_layout is not None:
                    terminal_grid = self._terminal_grid_rectangle(terminal)
                    target = calculate_pane_rectangle(
                        terminal_grid,
                        self.pane_layout,
                    )
                else:
                    target = calculate_preview_rectangle(terminal)
                if target != self._last_geometry:
                    self._last_geometry = target
                    self.root.geometry(
                        f"{target.width}x{target.height}"
                        f"+{target.left}+{target.top}"
                    )
                self.root.update_idletasks()
                self._apply_windows_styles()
                if self.root.state() == "withdrawn":
                    self._show_without_activation()
                self._update_canvas_screen_rectangle()
                self._raise_without_activation()
                self._restore_terminal_if_stolen()

    def _show_without_activation(self) -> None:
        """Show the overlay without transferring keyboard focus from MDIR."""
        if os.name != "nt":
            self.root.deiconify()
            return
        try:
            hwnd = self._window_hwnd()
            if not hwnd:
                self.root.deiconify()
                return
            SW_SHOWNOACTIVATE = 4
            ctypes.windll.user32.ShowWindow(
                wintypes.HWND(hwnd),
                SW_SHOWNOACTIVATE,
            )
        except Exception:
            self.root.deiconify()

    def _restore_terminal_if_stolen(self) -> None:
        """Undo an activation caused by Tk before no-activate styles applied."""
        if os.name != "nt" or not self.terminal_hwnd:
            return
        try:
            user32 = ctypes.windll.user32
            foreground = int(user32.GetForegroundWindow() or 0)
            if foreground == self._window_hwnd():
                user32.SetForegroundWindow(
                    wintypes.HWND(self.terminal_hwnd)
                )
        except Exception:
            pass

    def _follow_terminal(self) -> None:
        self._position_over_terminal()
        self.root.after(NATIVE_FOLLOW_POLL_MS, self._follow_terminal)

    def _raise_without_activation(self) -> None:
        if os.name != "nt":
            return
        try:
            hwnd = self._window_hwnd()
            if not hwnd:
                return
            get_foreground = ctypes.windll.user32.GetForegroundWindow
            get_foreground.restype = wintypes.HWND
            foreground = int(get_foreground() or 0)
            if foreground not in {self.terminal_hwnd, hwnd}:
                return
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            set_window_pos = ctypes.windll.user32.SetWindowPos
            set_window_pos.argtypes = [
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]
            set_window_pos.restype = wintypes.BOOL
            set_window_pos(
                wintypes.HWND(hwnd),
                wintypes.HWND(0),
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )
        except Exception:
            pass

    def _poll_commands(self) -> None:
        latest_show = None
        latest_layout = None
        latest_theme = None
        hide_requested = False
        shutdown_requested = False
        try:
            while True:
                command, payload = self.commands.get_nowait()
                if command == "show":
                    latest_show = payload
                    hide_requested = False
                elif command == "hide":
                    hide_requested = True
                    latest_show = None
                elif command == "layout":
                    latest_layout = payload
                elif command == "theme":
                    latest_theme = payload
                elif command == "shutdown":
                    shutdown_requested = True
        except queue.Empty:
            pass

        if shutdown_requested:
            self._shutdown_requested = True
            # Leave destruction to run() after mainloop returns. Destroying
            # the Tcl interpreter from inside its own queued callback can
            # leave Python/Tk reference cycles for the main thread to collect.
            self.root.quit()
            return
        if hide_requested:
            self.visible = False
            self.root.withdraw()
        if latest_theme is not None:
            self._apply_theme_palette(latest_theme)
        if latest_layout is not None:
            self.pane_layout = latest_layout
            self._last_geometry = None
        if latest_show is not None:
            data = latest_show
            self.terminal_hwnd = int(data.get("terminal_hwnd", 0))
            pane_layout = data.get("pane_layout")
            if pane_layout is not None:
                self.pane_layout = pane_layout
                self._last_geometry = None
            self._request_path(Path(data["path"]))
        elif latest_layout is not None and self.visible:
            self._position_over_terminal()

        self.root.after(NATIVE_COMMAND_POLL_MS, self._poll_commands)

    @staticmethod
    def _drain_queue(items: queue.Queue) -> None:
        try:
            while True:
                items.get_nowait()
        except queue.Empty:
            pass

    def _request_path(self, path: Path) -> None:
        """Queue only the newest selection without decoding on the Tk thread."""
        self._load_generation += 1
        generation = self._load_generation
        self._close_source()
        self.path = path
        self.title_label.configure(text=path.name)
        self.status_label.configure(text=f"Loading {path.name}...")
        self.canvas.delete("all")
        self.canvas.create_text(
            max(20, self.canvas.winfo_width() // 2),
            max(20, self.canvas.winfo_height() // 2),
            text=f"Loading preview...\n\n{path.name}",
            fill=self.theme_palette["foreground"],
            font=("Cascadia Mono", 11, "bold"),
            justify="center",
        )
        self.visible = True
        self._apply_windows_styles()
        self._position_over_terminal()
        self._drain_queue(self._load_requests)
        self._load_requests.put((generation, path))

    def _loader_main(self) -> None:
        """Decode one document at a time and discard superseded selections."""
        while not self._loader_stop.is_set():
            request = self._load_requests.get()
            if request is None:
                return
            generation, path = request
            source = None
            error: Optional[Exception] = None
            try:
                source = prepare_document_source(path)
            except Exception as exc:
                error = exc
            if self._loader_stop.is_set():
                if source is not None:
                    source.close()
                return
            acknowledged = threading.Event()
            self._load_results.put(
                (generation, path, source, error, acknowledged)
            )
            while (
                not self._loader_stop.is_set()
                and not acknowledged.wait(timeout=0.05)
            ):
                pass

    def _poll_load_results(self) -> None:
        latest = None
        try:
            while True:
                result = self._load_results.get_nowait()
                generation, _, source, _, acknowledged = result
                if (
                    latest is not None
                    and latest[2] is not None
                    and latest[0] != self._load_generation
                ):
                    latest[2].close()
                    latest[4].set()
                if generation == self._load_generation:
                    if latest is not None and latest[2] is not None:
                        latest[2].close()
                        latest[4].set()
                    latest = result
                elif source is not None:
                    source.close()
                    acknowledged.set()
                else:
                    acknowledged.set()
        except queue.Empty:
            pass

        if latest is not None:
            generation, path, source, error, acknowledged = latest
            if (
                generation == self._load_generation
                and path == self.path
                and error is None
                and source is not None
            ):
                self.document_source = source
                self.source_image = source.image
                self.kind = source.kind
                self.detail = source.detail
                self.fit()
                acknowledged.set()
            elif generation == self._load_generation:
                if source is not None:
                    source.close()
                self._show_load_error(error or RuntimeError("Unknown error"))
                acknowledged.set()

        try:
            self.root.after(
                NATIVE_COMMAND_POLL_MS,
                self._poll_load_results,
            )
        except Exception:
            pass

    def _show_load_error(self, error: Exception) -> None:
        self.source_image = None
        self.document_source = None
        self.canvas.delete("all")
        self.canvas.create_text(
            max(20, self.canvas.winfo_width() // 2),
            max(20, self.canvas.winfo_height() // 2),
            text=f"Native preview unavailable\n\n{error}",
            fill=self.theme_palette["error"],
            font=("Cascadia Mono", 11, "bold"),
            justify="center",
        )
        self.status_label.configure(
            text="Use Open to view the file with its Windows application."
        )

    def _shutdown_background_threads(self) -> None:
        self._loader_stop.set()
        self._drain_queue(self._load_requests)
        self._load_requests.put(None)
        self._remove_mouse_wheel_hook()
        if self._loader_thread.is_alive():
            self._loader_thread.join(timeout=1.5)
        try:
            while True:
                _, _, source, _, acknowledged = (
                    self._load_results.get_nowait()
                )
                if source is not None:
                    source.close()
                acknowledged.set()
        except queue.Empty:
            pass

    def _close_source(self) -> None:
        if self._render_after is not None:
            try:
                self.root.after_cancel(self._render_after)
            except Exception:
                pass
            self._render_after = None
        if self._fit_after is not None:
            try:
                self.root.after_cancel(self._fit_after)
            except Exception:
                pass
            self._fit_after = None
        self.canvas.delete("all")
        self.canvas_image = None
        self.photo = None
        self.source_image = None
        if self.document_source is not None:
            self.canvas.delete("all")
            try:
                self.document_source.close()
            except Exception:
                pass
            self.document_source = None

    def _update_canvas_screen_rectangle(self) -> None:
        try:
            left = int(self.canvas.winfo_rootx())
            top = int(self.canvas.winfo_rooty())
            width = max(1, int(self.canvas.winfo_width()))
            height = max(1, int(self.canvas.winfo_height()))
            self._canvas_screen_rectangle = WindowRectangle(
                left,
                top,
                left + width,
                top + height,
            )
        except Exception:
            self._canvas_screen_rectangle = None

    def _canvas_size(self) -> tuple[int, int]:
        self.root.update_idletasks()
        return (
            max(40, self.canvas.winfo_width()),
            max(40, self.canvas.winfo_height()),
        )

    def fit(self) -> None:
        if self.source_image is None:
            return
        canvas_width, canvas_height = self._canvas_size()
        self.fit_scale = min(
            canvas_width / self.source_image.width,
            canvas_height / self.source_image.height,
        )
        self.scale = maximum_safe_scale(
            self.source_image.size,
            self.fit_scale,
        )
        self.offset_x = (
            canvas_width - self.source_image.width * self.scale
        ) / 2
        self.offset_y = (
            canvas_height - self.source_image.height * self.scale
        ) / 2
        self._render()

    def native_size(self) -> None:
        if self.source_image is None:
            return
        canvas_width, canvas_height = self._canvas_size()
        center_x = canvas_width / 2
        center_y = canvas_height / 2
        source_x = (
            center_x - self.offset_x
        ) / max(self.scale, 1e-9)
        source_y = (
            center_y - self.offset_y
        ) / max(self.scale, 1e-9)
        self.scale = maximum_safe_scale(self.source_image.size, 1.0)
        self.offset_x = center_x - source_x * self.scale
        self.offset_y = center_y - source_y * self.scale
        self._clamp_offsets()
        self._render()

    def _render(self) -> None:
        self._render_after = None
        if self.source_image is None:
            return
        from PIL import Image, ImageTk

        canvas_size = self._canvas_size()
        plan = calculate_viewport_render_plan(
            self.source_image.size,
            canvas_size,
            self.scale,
            (self.offset_x, self.offset_y),
        )
        self.canvas.delete("all")
        self.canvas_image = None
        self.photo = None
        if plan is None:
            return

        cropped = self.source_image.crop(plan.crop_box)
        resampling = getattr(Image, "Resampling", Image)
        if cropped.size == plan.display_size:
            display = cropped
        else:
            display = cropped.resize(
                plan.display_size,
                resample=resampling.LANCZOS,
            )
            cropped.close()
        new_photo = ImageTk.PhotoImage(display)
        if display is not cropped:
            display.close()
        else:
            cropped.close()
        self.photo = new_photo
        self.canvas_image = self.canvas.create_image(
            plan.display_position[0],
            plan.display_position[1],
            image=self.photo,
            anchor="nw",
        )
        native_note = (
            " | 1:1 original pixels"
            if abs(self.scale - 1.0) < 1e-6
            else ""
        )
        self.status_label.configure(
            text=(
                f"{self.kind} | {self.detail} | "
                f"Zoom {self.scale * 100:.1f}%{native_note} | "
                f"Visible buffer {plan.display_size[0]:,} x "
                f"{plan.display_size[1]:,} | Wheel: zoom | Drag: pan"
            )
        )

    def _schedule_render(self) -> None:
        if self._render_after is not None:
            try:
                self.root.after_cancel(self._render_after)
            except Exception:
                pass
        self._render_after = self.root.after(35, self._render)

    def _zoom_at(self, x: float, y: float, delta: int) -> None:
        if self.source_image is None:
            return
        steps = delta / 120 if delta else 0
        factor = WHEEL_ZOOM_FACTOR ** steps
        source_x = (
            x - self.offset_x
        ) / max(self.scale, 1e-9)
        source_y = (
            y - self.offset_y
        ) / max(self.scale, 1e-9)
        self.scale = maximum_safe_scale(
            self.source_image.size,
            self.scale * factor,
        )
        self.offset_x = x - source_x * self.scale
        self.offset_y = y - source_y * self.scale
        self._clamp_offsets()
        self._schedule_render()

    def _on_wheel(self, event) -> str:
        self._zoom_at(event.x, event.y, event.delta)
        return "break"

    def _install_mouse_wheel_hook(self) -> None:
        """Run the low-level hook on a thread that never decodes images."""
        if (
            os.name != "nt"
            or (
                self._mouse_hook_thread is not None
                and self._mouse_hook_thread.is_alive()
            )
        ):
            return
        self._mouse_hook_stop.clear()
        self._mouse_hook_ready.clear()
        self._mouse_hook_thread = threading.Thread(
            target=self._mouse_hook_worker,
            name="MDIR-Native-Wheel-Hook",
            daemon=True,
        )
        self._mouse_hook_thread.start()
        self._mouse_hook_ready.wait(timeout=0.5)

    def _mouse_hook_worker(self) -> None:
        class POINT(ctypes.Structure):
            _fields_ = [
                ("x", ctypes.c_long),
                ("y", ctypes.c_long),
            ]

        class MSLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("pt", POINT),
                ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p),
            ]

        WH_MOUSE_LL = 14
        WM_MOUSEWHEEL = 0x020A
        WM_QUIT = 0x0012
        hook_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        user32 = ctypes.windll.user32
        call_next = user32.CallNextHookEx
        call_next.argtypes = [
            wintypes.HHOOK,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        call_next.restype = ctypes.c_ssize_t

        @hook_type
        def mouse_hook(code, message, data):
            if (
                code >= 0
                and int(message) == WM_MOUSEWHEEL
                and self.visible
                and self.source_image is not None
                and self._canvas_screen_rectangle is not None
            ):
                information = ctypes.cast(
                    data,
                    ctypes.POINTER(MSLLHOOKSTRUCT),
                ).contents
                rectangle = self._canvas_screen_rectangle
                if (
                    rectangle.left <= information.pt.x < rectangle.right
                    and rectangle.top <= information.pt.y < rectangle.bottom
                ):
                    delta = ctypes.c_short(
                        (information.mouseData >> 16) & 0xFFFF
                    ).value
                    local_x = information.pt.x - rectangle.left
                    local_y = information.pt.y - rectangle.top
                    try:
                        self._native_input.put_nowait(
                            (local_x, local_y, delta)
                        )
                    except queue.Full:
                        pass
                    return 1
            return call_next(None, code, message, data)

        set_hook = user32.SetWindowsHookExW
        set_hook.argtypes = [
            ctypes.c_int,
            hook_type,
            wintypes.HINSTANCE,
            wintypes.DWORD,
        ]
        set_hook.restype = wintypes.HHOOK
        self._mouse_hook_callback = mouse_hook
        get_current_thread_id = ctypes.windll.kernel32.GetCurrentThreadId
        get_current_thread_id.restype = wintypes.DWORD
        self._mouse_hook_thread_id = int(get_current_thread_id())
        self._mouse_hook = int(
            set_hook(WH_MOUSE_LL, mouse_hook, None, 0) or 0
        )
        self._mouse_hook_ready.set()

        if not self._mouse_hook:
            self._mouse_hook_thread_id = 0
            return
        message = wintypes.MSG()
        try:
            while not self._mouse_hook_stop.is_set():
                result = int(
                    user32.GetMessageW(
                        ctypes.byref(message),
                        None,
                        0,
                        0,
                    )
                )
                if result <= 0 or int(message.message) == WM_QUIT:
                    break
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            try:
                user32.UnhookWindowsHookEx(wintypes.HHOOK(self._mouse_hook))
            except Exception:
                pass
            self._mouse_hook = 0
            self._mouse_hook_callback = None
            self._mouse_hook_thread_id = 0

    def _poll_native_input(self) -> None:
        latest_position: Optional[tuple[int, int]] = None
        total_delta = 0
        try:
            while True:
                x, y, delta = self._native_input.get_nowait()
                latest_position = (x, y)
                total_delta += delta
        except queue.Empty:
            pass
        if (
            latest_position is not None
            and total_delta
            and self.visible
            and self.source_image is not None
        ):
            self._zoom_at(
                latest_position[0],
                latest_position[1],
                total_delta,
            )
        try:
            self.root.after(NATIVE_INPUT_POLL_MS, self._poll_native_input)
        except Exception:
            pass

    def _remove_mouse_wheel_hook(self) -> None:
        if os.name != "nt":
            return
        self._mouse_hook_stop.set()
        thread_id = self._mouse_hook_thread_id
        if thread_id:
            try:
                ctypes.windll.user32.PostThreadMessageW(
                    wintypes.DWORD(thread_id),
                    wintypes.UINT(0x0012),
                    wintypes.WPARAM(0),
                    wintypes.LPARAM(0),
                )
            except Exception:
                pass
        thread = self._mouse_hook_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=0.75)
        self._mouse_hook_thread = None
        try:
            if self._mouse_hook:
                ctypes.windll.user32.UnhookWindowsHookEx(
                    wintypes.HHOOK(self._mouse_hook)
                )
        except Exception:
            pass
        self._mouse_hook = 0
        self._mouse_hook_callback = None
        self._mouse_hook_thread_id = 0

    def _clamp_offsets(self) -> None:
        if self.source_image is None:
            return
        canvas_width, canvas_height = self._canvas_size()
        image_width = self.source_image.width * self.scale
        image_height = self.source_image.height * self.scale
        if image_width <= canvas_width:
            self.offset_x = (canvas_width - image_width) / 2
        else:
            self.offset_x = min(0.0, max(canvas_width - image_width, self.offset_x))
        if image_height <= canvas_height:
            self.offset_y = (canvas_height - image_height) / 2
        else:
            self.offset_y = min(0.0, max(canvas_height - image_height, self.offset_y))

    def _drag_start(self, event) -> None:
        self._drag_origin = (
            event.x,
            event.y,
            self.offset_x,
            self.offset_y,
        )

    def _drag_move(self, event) -> None:
        if self._drag_origin is None:
            return
        start_x, start_y, offset_x, offset_y = self._drag_origin
        self.offset_x = offset_x + event.x - start_x
        self.offset_y = offset_y + event.y - start_y
        self._clamp_offsets()
        if self.canvas_image is not None:
            self.canvas.coords(
                self.canvas_image,
                self.offset_x,
                self.offset_y,
            )

    def _drag_end(self, event) -> None:
        self._drag_origin = None

    def _canvas_resized(self, event) -> None:
        self._update_canvas_screen_rectangle()
        if self.source_image is not None and self.visible:
            if self._fit_after is not None:
                try:
                    self.root.after_cancel(self._fit_after)
                except Exception:
                    pass
            self._fit_after = self.root.after(80, self._fit_after_resize)

    def _fit_after_resize(self) -> None:
        self._fit_after = None
        if self.source_image is not None and self.visible:
            self.fit()

    def open_original(self) -> None:
        if self.path is not None and os.name == "nt":
            try:
                os.startfile(self.path)
            except Exception:
                pass

    def _request_full_view(self) -> None:
        self.visible = False
        self.root.withdraw()
        self.full_view_callback()

    def _request_files(self) -> None:
        self.visible = False
        self.root.withdraw()
        self.files_callback()

    def run(self) -> None:
        self._install_mouse_wheel_hook()
        try:
            self.root.mainloop()
        finally:
            if not self._loader_stop.is_set():
                self._shutdown_background_threads()
            try:
                self._close_source()
            except Exception:
                pass
            self.visible = False
            self.path = None
            root = self.root
            try:
                root.destroy()
            except Exception:
                pass

            # Release every direct Tk reference while still on the GUI thread.
            # This prevents Tcl_AsyncDelete during Python interpreter teardown.
            self.photo = None
            self.canvas_image = None
            self.preview_badge = None
            self.title_label = None
            self.canvas = None
            self.status_label = None
            self.root = None
            self.tk = None
            del root
            gc.collect()
