from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Static

from . import core as legacy


class AIShellApp(legacy.MDir):
    TITLE = "MDIR-U"
    SUB_TITLE = "Ubuntu and Universal File Manager / Codex AI Terminal"
    CSS = legacy.MDir.CSS + """
    #ai_panel { display: none; }
    #right_wrap.ai-mode #right_drive_bar,
    #right_wrap.ai-mode #right_drive_info,
    #right_wrap.ai-mode #right { display: none; }
    #right_wrap.ai-mode #ai_panel { display: block; }
    """
    BINDINGS = legacy.MDir.BINDINGS + [
        Binding(
            "f12",
            "toggle_ai_terminal",
            "AI/File",
            show=True,
            priority=True,
            id="mdir.ai",
        ),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.ai_mode = False

    def on_mount(self) -> None:
        super().on_mount()

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
                yield legacy.FilePane(
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
                yield legacy.FilePane(
                    "right",
                    self.right_start,
                    self.column_widths,
                    self.show_hidden_system,
                )

        yield Static("", id="status")
        yield Footer()

    async def _ensure_ai_panel(self):
        """Import and mount the AI editor only when F12 is first used."""
        existing = list(self.query("#ai_panel"))
        if existing:
            return existing[0]

        from .ai.panel import AIPanel

        panel = AIPanel(lambda: self.left.current_path)
        panel.disabled = True
        await self.query_one("#right_wrap", Vertical).mount(panel)
        return panel

    async def action_toggle_ai_terminal(self) -> None:
        panel = await self._ensure_ai_panel()
        self.ai_mode = not self.ai_mode
        wrap = self.query_one("#right_wrap", Vertical)
        if self.ai_mode:
            self._reset_mouse_routing()
            panel.disabled = False
            wrap.set_class(True, "ai-mode")
            self.set_active("left")
            panel.focus_prompt()
            self.call_after_refresh(self._focus_ai_prompt)
            self.set_status(
                "AI Terminal: Codex · F12 returns to the right file pane"
            )
        else:
            self._reset_mouse_routing()
            panel.disabled = True
            wrap.set_class(False, "ai-mode")

            # Restore all interaction state, not just the visual panel.
            self.set_active("right")
            table = self.right.table
            if hasattr(table, "_reset_slow_click"):
                table._reset_slow_click()
            table._right_dragging = False
            table._drag_rows_seen.clear()
            table._resize_key = None
            table._resize_next_key = None
            self.call_after_refresh(self._restore_right_file_focus)
            self.set_status("Right file pane restored")

    def _focus_ai_prompt(self) -> None:
        """Focus the AI input after the newly displayed panel is laid out."""
        if not self.ai_mode:
            return
        panel = self.query_one("#ai_panel")
        if panel.disabled:
            return
        panel.focus_prompt()

    def _reset_mouse_routing(self) -> None:
        """Discard mouse state owned by the pane that is being hidden."""
        # Releasing the file table alone is insufficient when an Input,
        # RichLog, scrollbar, or another child in the AI panel owns capture.
        self.capture_mouse(None)

        # F12 changes which widget occupies the same screen coordinates.
        # A click chain started in the old widget must not become a double or
        # triple click in the newly displayed widget.
        self._mouse_down_widget = None
        self._click_chain_last_offset = None
        self._click_chain_last_time = None
        self._chained_clicks = 1

    def _restore_right_file_focus(self) -> None:
        """Restore mouse/keyboard routing after the AI subtree is hidden."""
        if self.ai_mode:
            return
        self._reset_mouse_routing()
        self.set_active("right")
        table = self.right.table
        table.refresh(layout=True)
        table.focus()
