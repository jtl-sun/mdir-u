from __future__ import annotations

from rich.text import Text
from textual.geometry import Offset
from textual.strip import Strip
from textual.widgets import Input


class ThinCursorInput(Input):
    """Input using the terminal's zero-width steady insertion bar."""

    _STEADY_BAR = "\x1b[6 q"
    _SHOW_CURSOR = "\x1b[?25h"
    _HIDE_CURSOR = "\x1b[?25l"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.cursor_blink = False

    @property
    def insertion_cursor_screen_offset(self) -> Offset:
        """Return the insertion boundary rather than the next text cell."""
        x, y, _width, _height = self.content_region
        scroll_x, _ = self.scroll_offset
        return Offset(
            x + self._position_to_cell(self.cursor_position) - scroll_x,
            y,
        )

    def _write_terminal_cursor(self, sequence: str) -> None:
        if self.app.is_headless:
            return
        driver = getattr(self.app, "_driver", None)
        if driver is None:
            return
        driver.write(sequence)
        driver.flush()

    def _on_focus(self, event) -> None:
        super()._on_focus(event)
        self.app.cursor_position = self.insertion_cursor_screen_offset
        self._write_terminal_cursor(self._STEADY_BAR + self._SHOW_CURSOR)

    def _on_blur(self, event) -> None:
        super()._on_blur(event)
        self._write_terminal_cursor(self._HIDE_CURSOR)

    def _watch_selection(self, selection) -> None:
        super()._watch_selection(selection)
        self.app.cursor_position = self.insertion_cursor_screen_offset

    def render_line(self, y: int) -> Strip:
        if y != 0:
            return Strip.blank(self.size.width, self.rich_style)

        console = self.app.console
        options = self.app.console_options
        maximum_width = self.scrollable_content_region.width

        if not self.value:
            content = Text(self.placeholder, justify="left", end="")
            content.stylize(
                self.get_component_rich_style("input--placeholder")
            )
        else:
            content = self._value
            value_length = len(self.value)
            suggestion = self._suggestion
            show_suggestion = (
                len(suggestion) > value_length and self.has_focus
            )
            if show_suggestion:
                content += Text(
                    suggestion[value_length:],
                    self.get_component_rich_style("input--suggestion"),
                    end="",
                )

            if self.has_focus and not self.selection.is_empty:
                start, end = sorted(self.selection)
                content.stylize_before(
                    self.get_component_rich_style("input--selection"),
                    start,
                    end,
                )

        segments = list(
            console.render(
                content,
                options.update_width(self.content_width),
            )
        )
        strip = Strip(segments)
        scroll_x, _ = self.scroll_offset
        strip = strip.crop(scroll_x, scroll_x + maximum_width)
        strip = strip.extend_cell_length(maximum_width)
        return strip.apply_style(self.rich_style)
