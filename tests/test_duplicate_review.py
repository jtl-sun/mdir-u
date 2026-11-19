"""Safety tests: duplicate review must never delete, move or alter scanned files."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from textual.app import App
from textual.widgets import DataTable, Static

from mdir_u.advanced import find_exact_duplicates
from mdir_u.duplicate_review import DuplicateReviewStore, export_duplicate_report
from mdir_u.ui.duplicate_review import DuplicateReviewScreen


class DuplicateReviewStorageTests(unittest.TestCase):
    def test_identical_content_diff_names_and_path_notes_survive_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            one, two = root / "Project A", root / "Archive"
            one.mkdir()
            two.mkdir()
            original, intentional = one / "song.m4a", two / "backup-copy.m4a"
            original.write_bytes(b"audio-content")
            intentional.write_bytes(b"audio-content")
            (root / "different.m4a").write_bytes(b"not-the-same")

            groups = find_exact_duplicates(root)
            self.assertEqual(len(groups), 1)
            self.assertEqual(set(groups[0]), {original, intentional})
            save_path = root / "review.json"
            store = DuplicateReviewStore(save_path)
            store.set(original, "keep", "Master album / original playlist")
            store.set(intentional, "keep", "Backup for mastering project")
            loaded = DuplicateReviewStore(save_path)
            self.assertEqual(loaded.get(original).status, "keep")
            self.assertEqual(loaded.get(intentional).note, "Backup for mastering project")
            self.assertEqual(original.read_bytes(), b"audio-content")
            self.assertEqual(intentional.read_bytes(), b"audio-content")
            self.assertEqual((root / "different.m4a").read_bytes(), b"not-the-same")

    def test_candidate_is_only_metadata_not_deletion(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "music.mp3"
            path.write_bytes(b"important audio")
            store = DuplicateReviewStore(Path(folder) / "labels.json")
            store.set(path, "candidate", "Maybe unnecessary, check album links")
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_bytes(), b"important audio")
            self.assertEqual(store.get(path).status, "candidate")

    def test_modified_file_resets_label_without_losing_context(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "file.txt"
            path.write_bytes(b"first")
            store = DuplicateReviewStore(Path(folder) / "labels.json")
            store.set(path, "keep", "Stored for email attachment reference")
            path.write_bytes(b"replaced with different content")
            decision = store.get(path)
            self.assertEqual(decision.status, "review")
            self.assertTrue(decision.changed)
            self.assertIn("email attachment", decision.note)

    def test_corrupt_manifest_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "labels.json"
            path.write_text("bad json", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                DuplicateReviewStore(path)
            self.assertEqual(path.read_text(encoding="utf-8"), "bad json")

    def test_export_includes_full_path_intentional_copy_and_safe_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            copy = root / "=SUM(1+1).m4a"
            copy.write_bytes(b"music")
            store = DuplicateReviewStore(root / "labels.json")
            store.set(copy, "keep", "=HYPERLINK(\"bad\") (intentional)")
            report = root / "reports" / "duplicates.csv"
            count = export_duplicate_report(report, [("Exact 1", copy, 5)], store)
            self.assertEqual(count, 1)
            with report.open(encoding="utf-8-sig", newline="") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["Status"], "KEEP")
            self.assertEqual(rows[0]["Full path"], str(copy.absolute()))
            self.assertTrue(rows[0]["File name"].startswith("'="))
            self.assertTrue(rows[0]["Review note"].startswith("'="))
            self.assertTrue(copy.exists())


class DuplicateReviewScreenTests(unittest.IsolatedAsyncioTestCase):
    async def test_review_page_is_non_destructive_and_paginates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = []
            for index in range(155):
                item = root / f"song-{index:03d}.m4a"
                item.write_bytes(b"small")
                files.append(("Exact 1", item, 5))
            app = App()
            screen = DuplicateReviewScreen(
                root, files, 1, 0, root / "manifest.json"
            )
            async with app.run_test(size=(130, 42)) as pilot:
                app.push_screen(screen)
                await pilot.pause()
                table = screen.query_one("#duplicate_table", DataTable)
                self.assertEqual(table.row_count, 150)
                await pilot.click("#duplicate_keep")
                await pilot.pause()
                self.assertEqual(screen.store.get(files[0][1]).status, "keep")
                self.assertTrue(files[0][1].exists())
                await pilot.click("#duplicate_next")
                await pilot.pause()
                self.assertEqual(table.row_count, 5)
                self.assertEqual(screen.page, 1)
                await pilot.click("#duplicate_prev")
                await pilot.pause()
                self.assertEqual(table.row_count, 150)
                await pilot.click("#duplicate_export")
                await pilot.pause()
                self.assertIn("Exported 155 rows", str(
                    screen.query_one("#duplicate_feedback", Static).render()
                ))
                self.assertEqual(len(list((root / "reports").glob("*.csv"))), 1)
                self.assertEqual(len(list(root.glob("*.m4a"))), 155)
                await pilot.click("#duplicate_close")
                await pilot.pause()
                self.assertIsNot(app.screen, screen)


if __name__ == "__main__":
    unittest.main()
