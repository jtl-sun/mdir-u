from __future__ import annotations

from time import monotonic
from typing import Optional

from textual import events
from textual.binding import Binding

from .. import core as legacy


class SlowRenameDataTable(legacy.MDirDataTable):
    """File table with Explorer/Commander-style slow-click rename."""

    BINDINGS = [
        binding
        for binding in legacy.MDirDataTable.BINDINGS
        if binding.key not in {"left", "right"}
    ] + [
        Binding(
            "left",
            "focus_left_file_pane",
            "Left pane",
            show=False,
            priority=True,
        ),
        Binding(
            "right",
            "focus_right_file_pane",
            "Right pane",
            show=False,
            priority=True,
        ),
        Binding(
            "tab",
            "switch_file_pane",
            "Switch pane",
            show=False,
            priority=True,
        ),
    ]

    SLOW_CLICK_MIN_SECONDS = 0.55
    SLOW_CLICK_MAX_SECONDS = 1.60

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._rename_click_row: Optional[int] = None
        self._rename_click_time = 0.0

    def _reset_slow_click(self) -> None:
        self._rename_click_row = None
        self._rename_click_time = 0.0

    def _focus_file_pane(self, side: str) -> None:
        app = self.app
        if hasattr(app, "set_active"):
            app.set_active(side)

    def action_focus_left_file_pane(self) -> None:
        self._focus_file_pane("left")

    def action_focus_right_file_pane(self) -> None:
        self._focus_file_pane("right")

    def action_switch_file_pane(self) -> None:
        pane = self._pane()
        if pane is not None:
            self._focus_file_pane(
                "right" if pane.id == "left" else "left"
            )

    async def on_click(self, event: events.Click) -> None:
        # A normal fast double-click must retain the existing Open action.
        if event.button != 1 or getattr(event, "chain", 1) >= 2:
            self._reset_slow_click()
            # Textual dispatches matching handlers throughout the class MRO.
            # MDirDataTable.on_click will run next, so calling it explicitly
            # here would open the selected item twice.
            return

        # DataTable attaches the exact row/column to the rendered cell. This is
        # more reliable than hover_coordinate, which may still describe the
        # previous cell when the click handler begins.
        meta = event.style.meta
        if "row" not in meta or int(meta["row"]) < 0:
            self._reset_slow_click()
            return

        row = int(meta["row"])
        pane = self._pane()
        if row is None or pane is None or not (0 <= row < len(pane.entries)):
            self._reset_slow_click()
            return

        path = pane.entries[row]
        now = monotonic()
        elapsed = now - self._rename_click_time

        self.move_cursor(row=row, column=0)
        self._activate_pane()

        should_rename = (
            path is not None
            and row == self._rename_click_row
            and self.SLOW_CLICK_MIN_SECONDS
            <= elapsed
            <= self.SLOW_CLICK_MAX_SECONDS
        )

        if should_rename:
            self._reset_slow_click()
            app = self.app
            if hasattr(app, "action_rename"):
                app.action_rename()
            event.stop()
            return

        self._rename_click_row = row
        self._rename_click_time = now
