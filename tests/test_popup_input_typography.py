"""Popup inputs must use the same regular fixed-cell text as file panes."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from textual.widgets import Input
from mdir_u.app import MDirApp
from mdir_u.ui.inputs import ThinCursorInput
from mdir_u.ui.prompt import CompactPromptScreen
from mdir_u.ui.dialogs import CompactCopyScreen


class PopupInputTypographyTests(unittest.IsolatedAsyncioTestCase):
    async def test_f6_rename_input_is_not_bold_and_preserves_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "010620-6 TJ.pdf"
            path.write_bytes(b"sample")
            app = MDirApp()
            app.left_start = root
            app.right_start = root
            app._save_paths = lambda: None
            async with app.run_test(size=(130, 38)) as pilot:
                for _ in range(100):
                    if app.left.initial_listing_complete:
                        break
                    await pilot.pause(.03)
                app.push_screen(CompactPromptScreen(
                    "F6 Rename/Move — filename or destination path:",
                    str(path),
                ))
                await pilot.pause()
                field = app.screen.query_one("#compact_input", ThinCursorInput)
                self.assertFalse(bool(field.rich_style.bold))
                self.assertEqual(field.value, str(path))
                field.value = str(root / "010620-6 TJ revised.pdf")
                await pilot.pause()
                self.assertEqual(field.value, str(root / "010620-6 TJ revised.pdf"))
                app.exit()

    async def test_copy_save_as_input_is_regular_weight(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "010620-6 TJ.pdf"
            path.write_bytes(b"sample")
            app = MDirApp()
            app.left_start = root
            app.right_start = root
            app._save_paths = lambda: None
            async with app.run_test(size=(130, 38)) as pilot:
                app.push_screen(CompactCopyScreen([path], root))
                await pilot.pause()
                field = app.screen.query_one("#copy_name", ThinCursorInput)
                self.assertFalse(bool(field.rich_style.bold))
                self.assertEqual(field.value, path.name)
                app.exit()


if __name__ == "__main__":
    unittest.main()
