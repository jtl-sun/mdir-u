"""Check that every footer command is easy to click, not only the text row."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from textual.widgets import Footer
from textual.widgets._footer import FooterKey

from mdir_u.app import MDirApp


class FooterMouseTargetTests(unittest.IsolatedAsyncioTestCase):
    async def test_footer_has_three_clickable_rows_and_one_safe_row(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            app = MDirApp()
            app.left_start = directory
            app.right_start = directory
            app._save_paths = lambda: None
            async with app.run_test(size=(180, 42)) as pilot:
                footer = app.query_one(Footer)
                for _ in range(20):
                    if list(footer.query(FooterKey)):
                        break
                    await pilot.pause(0.05)

                self.assertEqual(footer.size.height, 4)
                self.assertEqual(footer.styles.padding.bottom, 1)
                keys = list(footer.query(FooterKey))
                self.assertTrue(keys, "Function-key commands must remain visible")
                for key in keys:
                    self.assertEqual(key.size.height, 3, key.key)

                options = next(key for key in keys if key.key == "f10")
                # Click the lowest of the THREE rows, not the rendered text row.
                await pilot.click(options, offset=(1, 2))
                await pilot.pause(0.1)
                self.assertIn("OptionsScreen", type(app.screen).__name__)
                app.exit()


if __name__ == "__main__":
    unittest.main()
