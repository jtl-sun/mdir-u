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

    FAST_DOUBLE_CLICK_MAX_SECONDS = 0.75
    SLOW_CLICK_MIN_SECONDS = 1.00
    SLOW_CLICK_MAX_SECONDS = 3.00
    SELECTION_CLICK_MAX_SECONDS = 0.20

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._rename_click_row: Optional[int] = None
        self._rename_click_time = 0.0
        self._selection_only_row: Optional[int] = None
        self._selection_click_row: Optional[int] = None
        self._selection_click_time = 0.0

    def _reset_slow_click(self) -> None:
        self._rename_click_row = None
        self._rename_click_time = 0.0
        self._selection_only_row = None
        self._selection_click_row = None
        self._selection_click_time = 0.0

    def _prepare_left_click_row(
        self,
        clicked_row: int,
        previous_cursor_row: int,
    ) -> None:
        """Make the first click on another file selection-only."""
        if clicked_row != previous_cursor_row:
            self._reset_slow_click()
            self._selection_only_row = clicked_row

    def _consume_selection_only_click(self, row: int) -> bool:
        selection_only = self._selection_only_row == row
        self._selection_only_row = None
        return selection_only

    def _record_selection_click(self, row: int, now: float) -> None:
        self._rename_click_row = None
        self._rename_click_time = 0.0
        self._selection_click_row = row
        self._selection_click_time = now

    def _selection_followup_action(
        self,
        row: int,
        now: float,
    ) -> Optional[str]:
        """Classify a click following the click which selected a new file."""
        if row != self._selection_click_row:
            return None
        elapsed = now - self._selection_click_time
        self._selection_click_row = None
        self._selection_click_time = 0.0
        if 0.0 <= elapsed <= self.SELECTION_CLICK_MAX_SECONDS:
            return "open"
        return "restart"

    def _arm_action_click(self, row: int, now: float) -> None:
        self._rename_click_row = row
        self._rename_click_time = now

    def _repeated_click_action(self, row: int, now: float) -> Optional[str]:
        """Classify a second single-click on the same row."""
        if row != self._rename_click_row:
            return None
        elapsed = now - self._rename_click_time
        if 0.0 <= elapsed <= self.FAST_DOUBLE_CLICK_MAX_SECONDS:
            return "open"
        if self.SLOW_CLICK_MIN_SECONDS <= elapsed <= self.SLOW_CLICK_MAX_SECONDS:
            return "rename"
        return None

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
        if event.button == 1 and self._shift_click_active(event):
            self._reset_slow_click()
            event.stop()
            return

        if event.button != 1:
            self._reset_slow_click()
            return

        if getattr(event, "chain", 1) >= 2:
            meta = event.style.meta
            row = int(meta.get("row", -1))
            now = monotonic()
            selection_action = self._selection_followup_action(row, now)
            if selection_action == "restart":
                self._arm_action_click(row, now)
                event.stop()
                return

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

        self.move_cursor(row=row, column=0, animate=False, scroll=False)
        self._activate_pane()

        selection_only = self._consume_selection_only_click(row)
        if selection_only:
            self._record_selection_click(row, now)
            return

        selection_action = self._selection_followup_action(row, now)
        if selection_action == "restart":
            self._arm_action_click(row, now)
            return

        repeated_action = (
            "open"
            if selection_action == "open"
            else self._repeated_click_action(row, now)
        )
        if path is not None and repeated_action == "open":
            self._reset_slow_click()
            app = self.app
            if hasattr(app, "_open_from_pane"):
                app._open_from_pane(pane)
            event.stop()
            return

        if path is not None and repeated_action == "rename":
            self._reset_slow_click()
            app = self.app
            if hasattr(app, "action_rename"):
                app.action_rename()
            event.stop()
            return

        self._arm_action_click(row, now)
