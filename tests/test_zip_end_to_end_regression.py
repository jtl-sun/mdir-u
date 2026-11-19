"""End-to-end checks for F9 ZIP creation, safe defaults, and failures."""
from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from mdir_u.app import MDirApp
from mdir_u.base import BaseApp
from mdir_u.ui.archive import CreateZipRequest, create_zip_archive, ArchiveError
from mdir_u.ui.archive import CreateZipScreen


class ZipDestinationTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows drive-root behaviour")
    def test_opposite_drive_root_uses_source_directory(self):
        import ctypes
        root = Path(Path.home().anchor)
        source = Path.home() / "Documents"
        self.assertEqual(BaseApp._preferred_zip_directory(source, root), source)

    @unittest.skipUnless(os.name == "nt", "Windows drive-root behaviour")
    def test_ordinary_opposite_directory_is_preserved(self):
        source = Path.home() / "source"
        opposite = Path.home() / "output"
        self.assertEqual(BaseApp._preferred_zip_directory(source, opposite), opposite)

    def test_missing_destination_permission_is_user_visible(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "a.txt"
            source.write_text("safe")
            occupied = root / "not_a_directory"
            occupied.write_text("occupied")
            with self.assertRaises((OSError, ArchiveError)):
                create_zip_archive([source], CreateZipRequest(
                    occupied / "archive.zip"
                ))
            self.assertEqual(source.read_text(), "safe")


class ZipProgressIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_22_selected_files_go_from_f9_to_valid_zip(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "work_sheet"
            output = root / "output"
            source.mkdir()
            output.mkdir()
            items = []
            for i in range(22):
                f = source / f"SpecSheet_{i:03d}.pdf"
                f.write_bytes(b"PDF placeholder " + bytes([i]) * 256)
                items.append(f)

            app = MDirApp()
            app.left_start = source
            app.right_start = output
            app._save_paths = lambda: None
            async with app.run_test(size=(140, 42)) as pilot:
                for _ in range(120):
                    if app.left.initial_listing_complete:
                        break
                    await pilot.pause(0.05)
                self.assertTrue(app.left.initial_listing_complete)
                app.left.marked = set(items)
                app.set_active("left")
                app.action_smart_archive()
                await pilot.pause()
                self.assertIsInstance(app.screen, CreateZipScreen)
                zip_path = Path(app.screen.query_one("#archive_path").value)
                self.assertEqual(zip_path.parent, output)
                self.assertTrue(await pilot.click("#archive_accept"))

                for _ in range(180):
                    if zip_path.is_file() and not app._archive_busy:
                        break
                    await pilot.pause(0.05)
                self.assertTrue(zip_path.is_file(), "F9 progress never created a ZIP")
                self.assertFalse(app._archive_busy)
                with zipfile.ZipFile(zip_path) as archive:
                    self.assertIsNone(archive.testzip())
                    self.assertEqual(
                        set(archive.namelist()), {f.name for f in items}
                    )
                self.assertTrue(all(f.is_file() for f in items))
                app.exit()


if __name__ == "__main__":
    unittest.main()
