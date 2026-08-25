from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.strip import Strip
from textual.widgets import Input


class ThinCursorInput(Input):
    """Textual Input with an insertion bar instead of a full-cell cursor."""

    CURSOR_BAR_STYLE = Style(color="#f2f2f2", bold=True)

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
            if self.has_focus and self._cursor_visible:
                content = Text("│", self.CURSOR_BAR_STYLE, end="") + content
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

            if self.has_focus and self._cursor_visible:
                cursor = self.cursor_position
                content = (
                    content[:cursor]
                    + Text("│", self.CURSOR_BAR_STYLE, end="")
                    + content[cursor:]
                )

        segments = list(
            console.render(
                content,
                options.update_width(self.content_width + 1),
            )
        )
        strip = Strip(segments)
        scroll_x, _ = self.scroll_offset
        strip = strip.crop(scroll_x, scroll_x + maximum_width + 1)
        strip = strip.extend_cell_length(maximum_width + 1)
        return strip.apply_style(self.rich_style)
