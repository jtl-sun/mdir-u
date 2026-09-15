"""Virtual terminal thumbnails: no desktop overlay or display-server dependency."""
from __future__ import annotations

from collections import OrderedDict
from math import ceil

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip

from .selection_style import MARK_BACKGROUND, MARK_FOREGROUND, MARK_PREFIX, CURSOR_BACKGROUND
from .thumbnail import IMAGE_EXTENSIONS, ThumbnailLoader, navigate


class ThumbnailGrid(ScrollView, can_focus=True):
    DEFAULT_CSS = """
    ThumbnailGrid { height: 1fr; width: 1fr; display: none; overflow-x: hidden; }
    """
    BINDINGS = [Binding(key, f"navigate('{key}')", '', show=False)
                for key in ('left', 'right', 'up', 'down', 'home', 'end', 'pageup', 'pagedown')] + [
                    Binding('tab', 'pane', '', show=False, priority=True),
                    Binding('enter', 'open_item', '', show=False),
                    Binding('space', 'mark', '', show=False),
                ]

    def __init__(self, pane, **kwargs):
        super().__init__(**kwargs)
        self.pane = pane
        self.tile_width = 20
        self.tile_height = 9
        self.columns = 1
        self.loader = None
        self.images = OrderedDict()
        self.revision = None
        self._last_cursor = None
        self._drag_revision = None
        self._seen = set()
        self._last = None
        self._pointer = None
        self._paint_signature = None

    def on_mount(self):
        self.set_interval(0.10, self.sync)
        self.set_interval(0.07, self._edge_tick)

    def current_revision(self):
        p = self.pane
        return (p.current_path, p._listing_generation, getattr(p, '_thumbnail_revision', 0),
                len(p.entries), p.initial_listing_complete)

    def ready(self):
        if not self.is_mounted or not self.app.is_running or self.app._exit:
            return False
        return (self.display and self.pane.display and len(self.app.screen_stack) == 1
                and not self.pane.disabled and self.pane.initial_listing_complete
                and self.pane.cached_path == self.pane.current_path)

    def set_enabled(self, enabled):
        self.end_drag()
        self.display = enabled
        self.pane.table.display = not enabled
        if enabled:
            if self.loader is None:
                self.loader = ThumbnailLoader()
            self.sync()
        elif self.loader is not None:
            self.loader.request(self.pane.id, ())

    def on_focus(self):
        self.app.set_active(self.pane.id, focus_table=False)

    def on_blur(self):
        self.end_drag()

    def on_resize(self):
        self.end_drag()
        self.sync()

    def sync(self):
        if not self.ready():
            self.end_drag()
            if self.loader:
                self.loader.request(self.pane.id, ())
            return
        revision = self.current_revision()
        if revision != self.revision:
            self.end_drag()
            self.revision = revision
            self._last_cursor = None
        self.columns = max(1, self.scrollable_content_region.width // self.tile_width)
        self.virtual_size = Size(self.scrollable_content_region.width,
                                 ceil(len(self.pane.entries) / self.columns) * self.tile_height)
        cursor = self.pane.table.cursor_row
        if cursor != self._last_cursor and self._drag_revision is None:
            self.ensure_current()
        self._last_cursor = cursor
        results = self.loader.take_results() if self.loader is not None else {}
        if self.loader is not None:
            for key, image in results.items():
                # Store bounded terminal pixels, releasing the Pillow image immediately.
                pixels = None
                if image is not None:
                    try:
                        from PIL import ImageOps
                        fitted = ImageOps.pad(image, (self.tile_width - 4, 10), color='#202020')
                        try:
                            pixels = tuple(fitted.getpixel((x, y)) for y in range(10)
                                           for x in range(self.tile_width - 4))
                        finally:
                            fitted.close()
                    finally:
                        image.close()
                self.images[key] = pixels
            while len(self.images) > 192:
                self.images.popitem(last=False)
            pending = []
            first = max(0, int(self.scroll_y) // self.tile_height - 1) * self.columns
            last = min(len(self.pane.entries),
                       (ceil((self.scroll_y + self.size.height) / self.tile_height) + 1) * self.columns)
            for index in range(first, last):
                key = self.image_key(index)
                if key and key not in self.images:
                    pending.append(key)
            self.loader.request(self.pane.id, pending)
        signature = (revision, cursor, frozenset(self.pane.marked), self.columns, self.size)
        if results or signature != self._paint_signature:
            self._paint_signature = signature
            self.refresh()

    def image_key(self, index):
        p = self.pane.entries[index]
        metadata = self.pane.metadata_by_path.get(p)
        if p is None or not metadata or metadata.is_directory or p.suffix.lower() not in IMAGE_EXTENSIONS:
            return None
        return (p, metadata.modified, metadata.size, 96)

    def render_line(self, y):
        width = self.scrollable_content_region.width
        line = int(self.scroll_y) + y
        row, inside = divmod(line, self.tile_height)
        output = []
        for column in range(self.columns):
            index = row * self.columns + column
            if index >= len(self.pane.entries):
                break
            path = self.pane.entries[index]
            selected = path is not None and path in self.pane.marked
            current = index == self.pane.table.cursor_row
            background = CURSOR_BACKGROUND if current else MARK_BACKGROUND if selected else '#202020'
            style = Style(color=MARK_FOREGROUND if selected else '#d8d8d8', bgcolor=background)
            border = Style(color='#36c9c6' if selected else '#7894a8' if current else '#555555', bgcolor=background)
            if inside in (0, self.tile_height - 1):
                label = ('✓' if selected else '─') + '─' * (self.tile_width - 3)
                output.append(Segment(' ' + label + ' ', border))
                continue
            output.append(Segment('│ ', border))
            pixels = self.images.get(self.image_key(index))
            if pixels and 1 <= inside <= 5:
                pixel_width = self.tile_width - 4
                start = (inside - 1) * 2 * pixel_width
                for x in range(pixel_width):
                    top, bottom = pixels[start + x], pixels[start + pixel_width + x]
                    output.append(Segment('▀', Style(color='#%02x%02x%02x' % top,
                                                     bgcolor='#%02x%02x%02x' % bottom)))
            else:
                label = ''
                if inside == 3:
                    metadata = self.pane.metadata_by_path.get(path)
                    label = 'DIR' if path is None or (metadata and metadata.is_directory) else (path.suffix[1:].upper() or 'FILE')
                if inside == 6:
                    label = (MARK_PREFIX if selected else '') + (path.name if path else '..')
                text = Text(label, style=style)
                text.truncate(self.tile_width - 4, overflow='ellipsis', pad=True)
                output.extend(Segment(segment.text, segment.style or style)
                              for segment in text.render(self.app.console, end=''))
            output.append(Segment(' │', border))
        return Strip(output).adjust_cell_length(width, Style(bgcolor='#202020'))

    def ensure_current(self):
        y = self.pane.table.cursor_row // self.columns * self.tile_height
        if y < self.scroll_y:
            self.scroll_to(y=y, animate=False)
        elif y + self.tile_height > self.scroll_y + self.size.height:
            self.scroll_to(y=y + self.tile_height - self.size.height, animate=False)

    def choose(self, index):
        self.app.set_active(self.pane.id)
        self.pane.table.move_cursor(row=index, column=0, scroll=False)
        self.pane.update_info()
        self.refresh()

    def action_navigate(self, key):
        index = navigate(self.pane.table.cursor_row, len(self.pane.entries), self.columns,
                         key, max(1, self.size.height // self.tile_height))
        self.pane.reset_shift_selection_anchor()
        self.choose(index)
        self.ensure_current()

    def action_pane(self):
        self.app.action_switch_pane()

    def action_open_item(self):
        self.app._open_from_pane(self.pane)

    def action_mark(self):
        self.toggle_rows((self.pane.table.cursor_row,))

    def index_at(self, x, y, clamp=False):
        if not self.ready() or not 0 <= x < self.columns * self.tile_width:
            return None
        if clamp:
            y = max(0, min(self.size.height - 1, y))
        elif not 0 <= y < self.size.height:
            return None
        index = (int(self.scroll_y) + y) // self.tile_height * self.columns + x // self.tile_width
        if clamp and self.pane.entries:
            index = min(index, len(self.pane.entries) - 1)
        return index if 0 <= index < len(self.pane.entries) else None

    def on_mouse_down(self, event: events.MouseDown):
        if event.button not in (1, 3):
            return
        index = self.index_at(event.x, event.y)
        if index is None:
            return
        self.choose(index)
        if event.button == 3:
            self.end_drag()
            self._drag_revision = self.current_revision()
            self.capture_mouse()
            self._pointer = (event.x, event.y)
            self._visit(index)
        elif event.ctrl:
            self.toggle_rows((index,))
        event.stop()
        event.prevent_default()

    def on_click(self, event: events.Click):
        if event.button == 1 and event.chain == 2 and not event.ctrl and self.ready():
            self.app._open_from_pane(self.pane)
        event.stop()

    def toggle_rows(self, rows):
        with self.app.batch_update():
            for index in rows:
                path = self.pane.entries[index]
                if path is None:
                    continue
                if path in self.pane.marked:
                    self.pane.marked.remove(path)
                else:
                    self.pane.marked.add(path)
                self.pane._update_mark_cell(path)
            self.pane.update_info()
            self.pane.update_summary()
        self.refresh()

    def _visit(self, index):
        if self._drag_revision != self.current_revision() or not self.ready():
            self.end_drag()
            return
        previous = self._last
        step = 1 if previous is None or index >= previous else -1
        candidates = (index,) if previous is None else range(previous + step, index + step, step)
        fresh = [i for i in candidates if i not in self._seen]
        self._seen.update(fresh)
        self._last = index
        self.toggle_rows(fresh)
        self.choose(index)

    def on_mouse_move(self, event: events.MouseMove):
        if self._drag_revision is None:
            return
        self._pointer = (event.x, event.y)
        index = self.index_at(event.x, event.y, clamp=True)
        if index is not None:
            self._visit(index)
        event.stop()

    def _edge_tick(self):
        if self._pointer is None:
            return
        if not self.ready() or self.current_revision() != self._drag_revision:
            self.end_drag()
            return
        x, y = self._pointer
        direction = -1 if y <= 0 else 1 if y >= self.size.height - 1 else 0
        if direction:
            self.scroll_to(y=self.scroll_y + direction * 2, animate=False)
            index = self.index_at(x, y, clamp=True)
            if index is not None:
                self._visit(index)

    def on_mouse_up(self, event: events.MouseUp):
        if event.button == 3:
            self.end_drag()
            event.stop()

    def end_drag(self):
        if self._drag_revision is not None:
            self.release_mouse()
        self._drag_revision = None
        self._seen.clear()
        self._last = self._pointer = None

    def on_unmount(self):
        self.end_drag()
        if self.loader:
            self.loader.shutdown()
