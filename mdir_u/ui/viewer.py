from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static, TextArea

from .. import core as legacy


class CompactViewerScreen(legacy.ViewerScreen):
    """File viewer shown as a distinct, cancellable window over MDIR."""

    BINDINGS = [
        Binding(
            "f3",
            "close_viewer",
            "Close viewer",
            show=False,
            priority=True,
        ),
    ]

    CSS = """
    CompactViewerScreen {
        align: center middle;
        background: #00000073;
    }

    #compact_viewer {
        width: 96%;
        height: 84%;
        min-width: 72;
        min-height: 16;
        max-width: 100%;
        max-height: 54;
        border: solid $primary;
        background: $surface;
        padding: 0 1;
    }

    #viewer_header {
        height: 1;
        min-height: 1;
        max-height: 1;
    }

    #viewer_title {
        width: 1fr;
        height: 1;
        color: $foreground;
        text-style: bold;
        text-wrap: nowrap;
    }

    #viewer_close_x {
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

    #viewer_close_x:hover {
        background: $error;
    }

    .viewer_content {
        height: 1fr;
        margin-top: 1;
        padding: 0 1;
        overflow-x: auto;
        overflow-y: auto;
        background: $background;
        color: $foreground;
        scrollbar-size: 1 1;
    }

    #viewer_text {
        border: none;
    }

    #viewer_actions {
        height: 3;
        align-horizontal: right;
    }

    #viewer_actions Button {
        min-width: 12;
        width: auto;
        height: 3;
    }

    #viewer_help {
        height: 1;
        color: $text-muted;
    }
    """

    def _read_entire_text(self) -> str:
        """Read the complete file using common Windows text encodings."""
        try:
            data = self.path.read_bytes()
        except Exception as exc:
            return f"[Unable to read file: {exc}]"

        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            try:
                return data.decode("utf-16")
            except UnicodeDecodeError:
                pass

        for encoding in ("utf-8-sig", "cp949"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                pass
        return data.decode("utf-8", errors="replace")

    def compose(self) -> ComposeResult:
        with Vertical(id="compact_viewer"):
            with Horizontal(id="viewer_header"):
                yield Static(str(self.path), id="viewer_title")
                yield Button("X", id="viewer_close_x")
            if self.path.suffix.lower() in legacy.IMAGE_EXTENSIONS:
                yield Static(
                    self._image_preview(),
                    id="viewer_image",
                    classes="viewer_content",
                )
            else:
                yield TextArea(
                    self._read_entire_text(),
                    id="viewer_text",
                    classes="viewer_content",
                    read_only=True,
                    soft_wrap=False,
                    show_line_numbers=True,
                    highlight_cursor_line=False,
                )
            with Horizontal(id="viewer_actions"):
                yield Button("Close", id="viewer_close")
            yield Static(
                "Arrows/PageUp/PageDown: scroll   "
                "F3/Esc/X/Close: return to MDIR",
                id="viewer_help",
            )

    def on_mount(self) -> None:
        try:
            self.query_one("#viewer_text", TextArea).focus()
        except Exception:
            self.query_one("#viewer_close", Button).focus()

    def _close(self) -> None:
        self.dismiss(None)

    def action_close_viewer(self) -> None:
        self._close()

    @on(Button.Pressed, "#viewer_close_x")
    @on(Button.Pressed, "#viewer_close")
    def close_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self._close()

    def key_escape(self) -> None:
        self._close()

    def key_f3(self) -> None:
        self._close()
