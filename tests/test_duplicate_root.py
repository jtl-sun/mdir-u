"""Drive-root duplicate finder scope and inaccessible-subtree regressions."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mdir_u.advanced import find_exact_duplicates
from mdir_u.base import BaseApp


class RecursiveDuplicateEngineTests(unittest.TestCase):
    def test_searches_root_siblings_and_deep_descendants(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            one = root / "Music" / "Classical"
            two = root / "AudioBooks" / "Narration"
            one.mkdir(parents=True)
            two.mkdir(parents=True)
            files = (root / "track.m4a", one / "another-name.mp3", two / "same-content.bin")
            for file in files:
                file.write_bytes(b"same bytes across folder depths")
            (two / "unique.txt").write_bytes(b"unique")
            stats = {}
            errors = []
            groups = find_exact_duplicates(root, scan_stats=stats, scan_errors=errors)
            self.assertEqual(len(groups), 1)
            self.assertEqual(set(groups[0]), set(files))
            self.assertEqual(stats["files_scanned"], 4)
            self.assertEqual(stats["files_hashed"], 3)
            self.assertEqual(errors, [])

    def test_reports_unreadable_subfolders_instead_of_silent_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            item = root / "available.txt"
            item.write_bytes(b"available")
            blocked = root / "System Volume Information"

            def fake_walk(start, *, onerror, followlinks):
                self.assertEqual(start, root)
                self.assertFalse(followlinks)
                onerror(PermissionError(13, "Access is denied", str(blocked)))
                yield str(root), [], [item.name]

            errors = []
            stats = {}
            with patch("mdir_u.advanced.os.walk", side_effect=fake_walk):
                groups = find_exact_duplicates(root, scan_errors=errors, scan_stats=stats)
            self.assertFalse(groups)
            self.assertEqual(stats["files_scanned"], 1)
            self.assertEqual(len(errors), 1)
            self.assertIn("System Volume Information", errors[0])

    def test_missing_root_is_reported_not_silently_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(NotADirectoryError):
                find_exact_duplicates(Path(folder) / "missing-drive")


if __name__ == "__main__":
    unittest.main()

class LinuxTrashIntegrationTests(unittest.TestCase):
    def test_default_recycle_uses_gio_trash_and_preserves_survivor(self):
        from types import SimpleNamespace
        from mdir_u.duplicate_cleanup import recycle_selected_exact_duplicate
        from mdir_u.duplicate_review import DuplicateReviewStore
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original, duplicate = root / 'original', root / 'duplicate'
            original.write_bytes(b'identical')
            duplicate.write_bytes(b'identical')
            rows = [('Exact 1', original, 9), ('Exact 1', duplicate, 9)]
            with patch('mdir_u.file_operations.shutil.which', return_value='/usr/bin/gio'), \
                 patch('mdir_u.file_operations.subprocess.run', return_value=SimpleNamespace(returncode=0)) as run:
                survivor = recycle_selected_exact_duplicate(root, rows, rows[1], DuplicateReviewStore(root / 'reviews.json'))
            self.assertEqual(survivor, original)
            self.assertEqual(run.call_args.args[0], ['/usr/bin/gio', 'trash', '--', str(duplicate)])
            self.assertEqual(original.read_bytes(), b'identical')
