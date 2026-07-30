from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes


DEFAULT_WINDOW_WIDTH = 1480
DEFAULT_WINDOW_HEIGHT = 850
WINDOW_WORK_AREA_MARGIN = 32
WINDOW_RESIZE_SETTLE_SECONDS = 0.015


def centered_window_bounds(
    work_left: int,
    work_top: int,
    work_right: int,
    work_bottom: int,
    requested_width: int = DEFAULT_WINDOW_WIDTH,
    requested_height: int = DEFAULT_WINDOW_HEIGHT,
    margin: int = WINDOW_WORK_AREA_MARGIN,
) -> tuple[int, int, int, int]:
    """Return a centered window rectangle fitted inside a monitor work area."""
    work_width = max(1, work_right - work_left)
    work_height = max(1, work_bottom - work_top)
    available_width = max(1, work_width - min(margin, work_width - 1))
    available_height = max(1, work_height - min(margin, work_height - 1))
    width = min(max(1, requested_width), available_width)
    height = min(max(1, requested_height), available_height)
    left = work_left + (work_width - width) // 2
    top = work_top + (work_height - height) // 2
    return left, top, width, height


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def _configure_user32():
    """Configure the Win32 signatures used by the terminal window helpers."""
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetClassNameW.argtypes = [
        wintypes.HWND,
        wintypes.LPWSTR,
        ctypes.c_int,
    ]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = [
        wintypes.HMONITOR,
        ctypes.POINTER(_MonitorInfo),
    ]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.IsZoomed.argtypes = [wintypes.HWND]
    user32.IsZoomed.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    return user32


def _position_terminal_window(
    width: int = DEFAULT_WINDOW_WIDTH,
    height: int = DEFAULT_WINDOW_HEIGHT,
) -> bool:
    """Resize and center the foreground terminal without hiding it."""
    if os.name != "nt":
        return False

    user32 = _configure_user32()
    window = user32.GetForegroundWindow()
    if not window:
        return False

    class_name_buffer = ctypes.create_unicode_buffer(256)
    if not user32.GetClassNameW(
        window,
        class_name_buffer,
        len(class_name_buffer),
    ):
        return False

    class_name = class_name_buffer.value
    is_terminal = (
        "CASCADIA" in class_name.upper()
        or class_name == "ConsoleWindowClass"
    )
    if not is_terminal:
        return False

    monitor = user32.MonitorFromWindow(window, 2)
    if not monitor:
        return False

    monitor_info = _MonitorInfo()
    monitor_info.cbSize = ctypes.sizeof(_MonitorInfo)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info)):
        return False

    work = monitor_info.rcWork
    left, top, fitted_width, fitted_height = centered_window_bounds(
        work.left,
        work.top,
        work.right,
        work.bottom,
        width,
        height,
    )

    # Avoid an unnecessary restore animation for an already normal window.
    if user32.IsZoomed(window):
        user32.ShowWindow(window, 9)

    no_z_order = 0x0004
    no_activate = 0x0010
    return bool(
        user32.SetWindowPos(
            window,
            None,
            left,
            top,
            fitted_width,
            fitted_height,
            no_z_order | no_activate,
        )
    )


def center_terminal_window(
    width: int = DEFAULT_WINDOW_WIDTH,
    height: int = DEFAULT_WINDOW_HEIGHT,
) -> bool:
    """Resize and center the terminal, then let its character grid settle."""
    positioned = _position_terminal_window(width, height)
    if positioned:
        # Let Windows Terminal propagate its pixel resize to the ConPTY grid
        # before Textual reads the initial row and column count.
        time.sleep(WINDOW_RESIZE_SETTLE_SECONDS)
    return positioned
