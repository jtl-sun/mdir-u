"""F9 archive routing and keyboard drive-switch coverage."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from mdir_u.base import BaseApp
from mdir_u.core import MDir
from mdir_u.keymap import load_keymap


class F9ArchiveTests(unittest.TestCase):
    @staticmethod
    def simulate(items):
        obj = SimpleNamespace(
            _archive_busy=False,
            active=SimpleNamespace(selected_items=lambda: list(items)),
            set_status=Mock(),
            action_compress_zip=Mock(),
            action_extract_zip=Mock(),
        )
        BaseApp.action_smart_archive(obj)
        return obj

    def test_f9_uses_zip_extraction_for_single_archive(self):
        with tempfile.TemporaryDirectory() as root:
            zip_path = Path(root) / "archive.ZIP"
            zip_path.write_bytes(b"test")
            result = self.simulate([zip_path])
            result.action_extract_zip.assert_called_once_with()
            result.action_compress_zip.assert_not_called()

    def test_f9_compresses_files_and_folders_including_multiple_items(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root)
            file_path, folder_path = p / "a.txt", p / "folder"
            file_path.touch()
            folder_path.mkdir()
            for items in ([file_path], [folder_path], [file_path, folder_path]):
                with self.subTest(items=items):
                    result = self.simulate(items)
                    result.action_compress_zip.assert_called_once_with()
                    result.action_extract_zip.assert_not_called()

    def test_f9_handles_no_selection_and_unsupported_archive(self):
        missing = self.simulate([])
        missing.action_compress_zip.assert_not_called()
        missing.set_status.assert_called_once()
        with tempfile.TemporaryDirectory() as root:
            rar = Path(root) / "archive.rar"
            rar.touch()
            result = self.simulate([rar])
            result.action_compress_zip.assert_not_called()
            self.assertIn("ZIP only", result.set_status.call_args.args[0])

    def test_footer_and_preserved_zip_aliases(self):
        bindings = {b.key: b for b in MDir.BINDINGS}
        self.assertEqual(bindings["f9"].action, "smart_archive")
        self.assertEqual(bindings["alt+f9"].action, "drive")
        self.assertEqual(bindings["alt+f5"].action, "compress_zip")
        self.assertEqual(bindings["alt+f6"].action, "extract_zip")
        if os.name == "nt":
            for letter in ("c", "d", "s"):
                self.assertEqual(
                    bindings[f"alt+{letter}"].action, f"quick_drive('{letter.upper()}')"
                )

    def test_legacy_f9_drive_keymap_migrates(self):
        with tempfile.TemporaryDirectory() as root:
            import json
            prefs = Path(root) / "keys.json"
            prefs.write_text(json.dumps({
                "mdir.drive": "f9", "mdir.view": "ctrl+v"
            }), encoding="utf-8")
            result = load_keymap(prefs)
            self.assertNotIn("mdir.drive", result)
            self.assertEqual(result.get("mdir.view"), "ctrl+v")


if __name__ == "__main__":
    unittest.main()
