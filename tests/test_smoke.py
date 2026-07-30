from __future__ import annotations

import os
import base64
import sys
import tempfile
import unittest
from pathlib import Path

from mdir_u.app import MDirApp
from mdir_u.preview.native import (
    PaneLayout,
    WindowRectangle,
    calculate_pane_rectangle,
)
from mdir_u.text_actions import DEFAULT_VIEW_LIMIT, inspect_safe_text_file


class PackageSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_ai_panel_is_loaded_only_when_requested(self) -> None:
        app = MDirApp()
        self.assertNotIn("mdir_u.ai.panel", sys.modules)

        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause(0.05)
            self.assertFalse(list(app.query("#ai_panel")))

            await app.action_toggle_ai_terminal()
            await pilot.pause(0.05)
            self.assertTrue(app.ai_mode)
            self.assertEqual(len(list(app.query("#ai_panel"))), 1)

            await app.action_toggle_ai_terminal()
            await pilot.pause(0.05)
            self.assertFalse(app.ai_mode)
            self.assertTrue(app.right.table.has_focus)
            app.exit()

    async def test_listing_and_theme_switch(self) -> None:
        previous = os.environ.get("MDIR_NATIVE_PREVIEW")
        os.environ["MDIR_NATIVE_PREVIEW"] = "0"
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "folder").mkdir()
                (root / "note.txt").write_text(
                    "hello",
                    encoding="utf-8",
                )

                app = MDirApp()
                app.left_start = root
                app.right_start = root
                app._save_paths = lambda: None

                async with app.run_test(size=(120, 35)) as pilot:
                    for _ in range(100):
                        if (
                            app.left.initial_listing_complete
                            and len(app.left.entries) >= 3
                        ):
                            break
                        await pilot.pause(0.02)

                    self.assertIn(root / "folder", app.left.entries)
                    self.assertIn(root / "note.txt", app.left.entries)
                    self.assertEqual(
                        app.left.styles.background.hex,
                        "#202020",
                    )

                    app.theme = "textual-light"
                    await pilot.pause()
                    await pilot.pause()
                    self.assertEqual(
                        app.left.styles.background.hex,
                        "#E0E0E0",
                    )
                    app.exit()
        finally:
            if previous is None:
                os.environ.pop("MDIR_NATIVE_PREVIEW", None)
            else:
                os.environ["MDIR_NATIVE_PREVIEW"] = previous

    async def test_preview_toggle_preserves_file_navigation(self) -> None:
        previous = os.environ.get("MDIR_NATIVE_PREVIEW")
        os.environ["MDIR_NATIVE_PREVIEW"] = "0"
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                image = root / "preview.png"
                image.write_bytes(
                    base64.b64decode(
                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
                        "AAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                    )
                )

                app = MDirApp()
                app.left_start = root
                app.right_start = root
                app._save_paths = lambda: None

                async with app.run_test(size=(120, 35)) as pilot:
                    for _ in range(100):
                        if app.left.initial_listing_complete:
                            break
                        await pilot.pause(0.02)

                    app.left.table.move_cursor(
                        row=app.left.row_by_path[image],
                        column=0,
                    )
                    app.set_active("left")
                    app.action_toggle_preview()
                    await pilot.pause(0.05)

                    self.assertTrue(app.preview_enabled)
                    self.assertTrue(app.preview_mode)
                    self.assertTrue(app.left.table.has_focus)
                    self.assertTrue(app.right.disabled)

                    await pilot.pause(0.25)
                    app.action_toggle_preview()
                    await pilot.pause(0.05)
                    self.assertFalse(app.preview_enabled)
                    self.assertFalse(app.preview_mode)
                    self.assertFalse(app.right.disabled)
                    await pilot.pause(0.2)
                    app.exit()
        finally:
            if previous is None:
                os.environ.pop("MDIR_NATIVE_PREVIEW", None)
            else:
                os.environ["MDIR_NATIVE_PREVIEW"] = previous

    def test_safe_text_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            text = root / "note.md"
            image = root / "photo.jpg"
            text.write_text("# MDIR", encoding="utf-8")
            image.write_bytes(b"\xff\xd8\xff\xe0binary")

            self.assertTrue(
                inspect_safe_text_file(
                    text,
                    max_bytes=DEFAULT_VIEW_LIMIT,
                ).allowed
            )
            self.assertEqual(
                inspect_safe_text_file(
                    image,
                    max_bytes=DEFAULT_VIEW_LIMIT,
                ).reason,
                "unsupported_type",
            )

    def test_native_preview_geometry(self) -> None:
        terminal = WindowRectangle(100, 50, 2_100, 1_250)
        pane = PaneLayout(
            x=80,
            y=3,
            width=70,
            height=38,
            columns=150,
            rows=45,
        )
        rectangle = calculate_pane_rectangle(terminal, pane)
        self.assertGreater(rectangle.width, 800)
        self.assertGreater(rectangle.height, 700)


if __name__ == "__main__":
    unittest.main()
