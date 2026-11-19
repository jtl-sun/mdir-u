"""Verify post-recycle results refresh without rescanning the user's drive."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from textual.app import App
from textual.widgets import Button, Static

from mdir_u.duplicate_cleanup import refreshed_duplicate_review
from mdir_u.ui.duplicate_review import DuplicateReviewScreen


class DuplicateResultFilteringTests(unittest.TestCase):
    def test_two_copy_group_disappears_after_one_copy_recycled(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first, last = root / "first.mp3", root / "last.mp3"
            first.write_bytes(b"same")
            last.write_bytes(b"same")
            rows = [("Exact 1", first, 4), ("Exact 1", last, 4)]
            first.unlink()  # Simulate confirmed Windows recycle.
            updated, resolved, hidden = refreshed_duplicate_review(rows, [rows[0]])
            self.assertEqual(updated, [])
            self.assertEqual((resolved, hidden), (1, 2))
            self.assertTrue(last.is_file())  # Last copy remains in its folder.

    def test_three_copy_group_remains_when_two_still_exist(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = [root / f"copy-{i}.mp3" for i in range(3)]
            for p in paths:
                p.write_bytes(b"same")
            rows = [("Exact 8", p, 4) for p in paths]
            paths[0].unlink()
            remaining, resolved, hidden = refreshed_duplicate_review(rows, [rows[0]])
            self.assertEqual([x[1] for x in remaining], paths[1:])
            self.assertEqual((resolved, hidden), (0, 1))

    def test_clears_only_resolved_groups_and_keeps_other_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            group1 = [root / "a.mp3", root / "b.mp3"]
            group2 = [root / "c.mp3", root / "d.mp3"]
            for p in group1 + group2:
                p.write_bytes(b"song")
            rows = [("Exact 1", p, 4) for p in group1] + [
                ("Exact 2", p, 4) for p in group2
            ]
            group1[0].unlink()
            remaining, resolved, hidden = refreshed_duplicate_review(rows, [rows[0]])
            self.assertEqual([row[0] for row in remaining], ["Exact 2", "Exact 2"])
            self.assertEqual((resolved, hidden), (1, 2))


class DuplicateUIRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_recycle_keeps_existing_marks_only_for_valid_remaining_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = [root / f"{name}.m4a" for name in "abcde"]
            for p in paths:
                p.write_bytes(b"music")
            rows = [
                ("Exact 1", paths[0], 5), ("Exact 1", paths[1], 5),
                ("Exact 2", paths[2], 5), ("Exact 2", paths[3], 5),
                ("Exact 2", paths[4], 5),
            ]
            app = App()
            screen = DuplicateReviewScreen(
                root, rows, 2, 0, root / "review.json",
                scan_stats={"files_scanned": 5, "files_hashed": 5},
            )
            async with app.run_test(size=(130, 44)) as pilot:
                app.push_screen(screen)
                await pilot.pause()
                screen._marked = {
                    ("Exact 1", paths[0]), ("Exact 2", paths[3])
                }
                screen._show_page()
                paths[0].unlink()
                resolved, hidden = screen._refresh_after_recycle([rows[0]])
                await pilot.pause()
                self.assertEqual((resolved, hidden), (1, 2))
                self.assertEqual(screen.exact_groups, 1)
                self.assertEqual(len(screen.results), 3)
                self.assertEqual(screen._marked, {("Exact 2", paths[3])})
                self.assertEqual(screen.query_one("#duplicate_table").row_count, 3)
                summary = str(screen.query_one("#duplicate_summary", Static).render())
                self.assertIn("Current matches: 1 exact groups", summary)
                self.assertIn("3 duplicate rows", summary)
                self.assertIn("Original scan: 5 files", summary)
                notice = str(screen.query_one("#duplicate_result_notice", Static).render())
                self.assertIn("RECYCLED: 1 file(s)", notice)
                self.assertIn("RESULTS REFRESHED", notice)
                self.assertIn("Marked: 1", str(
                    screen.query_one("#duplicate_page", Static).render()
                ))
                self.assertFalse(
                    screen.query_one("#duplicate_delete_marked", Button).disabled
                )
                self.assertTrue(paths[1].is_file())
                screen.dismiss(None)
                await pilot.pause()

if __name__ == "__main__":
    unittest.main()
