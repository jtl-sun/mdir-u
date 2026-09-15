import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from textual import events
from textual.widgets import Button
from mdir_u import core
from mdir_u.app import MDirApp


class ThumbnailTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'LOCALAPPDATA': str(self.root), 'XDG_CACHE_HOME': str(self.root),
                                          'XDG_STATE_HOME': str(self.root), 'MDIR_U_SHORTCUTS': str(self.root/'links.json')})
        self.env.start()
        self.config = patch.object(core, 'CONFIG_PATH', self.root/'config.json')
        self.config.start()
        for side in ('left', 'right'):
            folder = self.root/side
            folder.mkdir()
            for i in range(40):
                (folder/f'{i:02}.txt').write_text(f'file {i}')
            (folder/'folder').mkdir()
            with Image.new('RGB', (80, 50), '#ff0000') as image:
                image.save(folder/'00.png')
        self.app = MDirApp()
        self.app.left_start, self.app.right_start = self.root/'left', self.root/'right'
        self.app._save_paths = lambda: None
        self.context = self.app.run_test(size=(140, 42))
        self.pilot = await self.context.__aenter__()
        await self.wait_for(lambda: self.app.left.initial_listing_complete and self.app.right.initial_listing_complete)

    async def asyncTearDown(self):
        await self.context.__aexit__(None, None, None)
        self.config.stop()
        self.env.stop()
        self.temp.cleanup()

    async def wait_for(self, predicate):
        for _ in range(120):
            if predicate(): return
            await self.pilot.pause(0.03)
        self.assertTrue(predicate())

    async def enable(self, side):
        await self.pilot.click(f'#{side}_thumbnail')
        grid = self.app.thumbnail_grids[side]
        await self.pilot.pause()
        self.assertTrue(grid.display)
        self.assertIs(self.app.focused, grid)
        return grid

    async def test_both_panes_drag_reverse_release_and_list(self):
        for side in ('left', 'right'):
            grid = await self.enable(side)
            pane = grid.pane
            other = self.app.right if side == 'left' else self.app.left
            before_other = set(other.marked)
            pane.toggle_mark_path(pane.entries[2])
            await self.pilot.mouse_down(grid, offset=(21, 2), button=3)
            await self.pilot.hover(grid, offset=(41, 11))
            last = grid.columns + 2
            await self.pilot.hover(grid, offset=(21, 2))
            await self.pilot._post_mouse_events([events.MouseUp], widget=grid, offset=(21, 2), button=3)
            self.assertEqual(pane.marked, set(pane.entries[1:last+1]) - {pane.entries[2]})
            self.assertEqual(other.marked, before_other)
            self.assertIsNone(grid._drag_revision)
            self.assertNotIn(None, pane.marked)
            marked = set(pane.marked)
            await self.pilot.hover(grid, offset=(1, 20))
            self.assertEqual(pane.marked, marked)
            await self.pilot.press('alt+t')
            self.assertTrue(pane.table.display)
            self.assertEqual(pane.marked, marked)

    async def test_images_render_and_workers_are_bounded(self):
        grid = await self.enable('left')
        row = grid.pane.row_by_path[self.root/'left'/'00.png']
        await self.wait_for(lambda: grid.images.get(grid.image_key(row)) is not None)
        line = grid.render_line(row // grid.columns * grid.tile_height + 1 - int(grid.scroll_y))
        self.assertTrue(any('▀' in segment.text for segment in line))
        self.assertLessEqual(len(grid.loader.pending), 96)
        self.assertLessEqual(len(grid.images), 192)

    async def test_keyboard_navigation_bulk_buttons_and_hidden_are_independent(self):
        left = await self.enable('left')
        await self.pilot.press('right')
        self.assertEqual(left.pane.table.cursor_row, 1)
        await self.pilot.press('down')
        self.assertEqual(left.pane.table.cursor_row, 1 + left.columns)
        await self.pilot.press('tab')
        self.assertEqual(self.app.active_side, 'right')
        right = await self.enable('right')
        for side in ('left', 'right'):
            await self.pilot.click(f'#{side}_select_all')
            pane = self.app.left if side == 'left' else self.app.right
            self.assertEqual(pane.marked, set(pane.entries) - {None})
            button = self.app.query_one(f'#{side}_select_all', Button)
            thumb = self.app.query_one(f'#{side}_thumbnail', Button)
            self.assertGreaterEqual(button.region.x - thumb.region.right, 2)
            await self.pilot.click(f'#{side}_select_invert')
            self.assertFalse(pane.marked)
            await self.pilot.click(f'#{side}_select_none')
        await self.pilot.click('#right_hidden_toggle')
        self.assertTrue(self.app.right.show_hidden_system)
        self.assertFalse(self.app.left.show_hidden_system)

    async def test_edge_scroll_and_modal_cancel(self):
        grid = await self.enable('left')
        await self.pilot.mouse_down(grid, offset=(21, 2), button=3)
        await self.pilot.hover(grid, offset=(21, grid.size.height - 1))
        await self.wait_for(lambda: grid.scroll_y > 0)
        self.assertGreater(len(grid.pane.marked), grid.columns)
        self.app.action_options()
        await self.pilot.pause()
        grid.sync()
        self.assertIsNone(grid._drag_revision)
        marked = set(grid.pane.marked)
        grid._edge_tick()
        self.assertEqual(grid.pane.marked, marked)
        await self.pilot.press('escape')

    async def test_folder_navigation_and_copy_use_existing_actions(self):
        grid = await self.enable('left')
        source = self.root/'left'/'01.txt'
        destination = self.root/'right'/'01.txt'
        destination.unlink()
        row = grid.pane.row_by_path[source]
        grid.choose(row)
        grid.toggle_rows((row,))
        await self.pilot.press('f5', 'enter')
        await self.wait_for(lambda: destination.exists() and not self.app._file_operation_busy
                            and len(self.app.screen_stack) == 1)
        self.assertEqual(destination.read_text(), source.read_text())
        await self.pilot.pause()
        await self.wait_for(lambda: grid.pane.initial_listing_complete)
        grid.choose(grid.pane.row_by_path[self.root/'left'/'folder'])
        await self.pilot.pause()
        self.assertEqual(grid.pane.selected_path(), self.root/'left'/'folder')
        self.assertIs(self.app.focused, grid)
        await self.pilot.press('enter')
        await self.wait_for(lambda: grid.pane.cached_path == self.root/'left'/'folder')
        self.assertTrue(grid.display)
        self.assertFalse(grid.pane.marked)
