"""Multi-select duplicate cleanup safety: user-chosen survivors are never recycled."""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from textual.app import App
from textual.widgets import DataTable

from mdir_u.duplicate_cleanup import (
    plan_marked_exact_duplicates,
    recycle_marked_exact_duplicates,
)
from mdir_u.duplicate_review import DuplicateReviewStore
from mdir_u.ui.duplicate_review import DuplicateReviewScreen


class BatchDuplicateSafetyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = DuplicateReviewStore(self.root / "review.json")
        self.paths = [self.root / f"file-{i}.m4a" for i in range(4)]
        for p in self.paths[:3]:
            p.write_bytes(b"same music audio")
        self.paths[3].write_bytes(b"another audio")
        self.rows = [
            ("Exact 1", p, len(b"same music audio")) for p in self.paths[:3]
        ]

    def test_all_copies_marked_requires_manually_unmarking_survivor(self):
        safe, skipped = plan_marked_exact_duplicates(
            self.rows, [(g, p) for g, p, _ in self.rows], self.store
        )
        self.assertFalse(safe)
        self.assertIn("Unmark at least one", skipped[0])

    def test_two_marked_out_of_three_keeps_explicit_unmarked_file(self):
        selected = self.rows[:2]
        safe, skipped = plan_marked_exact_duplicates(
            self.rows, [(g, p) for g, p, _ in selected], self.store
        )
        self.assertEqual(safe, selected)
        self.assertFalse(skipped)
        trash = self.root / "fake-trash"
        trash.mkdir()
        recycle = Mock(side_effect=lambda p: p.rename(trash / p.name))
        successful, failed = recycle_marked_exact_duplicates(
            self.root, self.rows, selected, self.store, recycle=recycle
        )
        self.assertEqual(successful, selected)
        self.assertEqual(failed, [])
        self.assertTrue(self.paths[2].is_file())
        self.assertFalse(self.paths[0].exists())
        self.assertFalse(self.paths[1].exists())
        self.assertEqual(len(list(trash.glob("*.m4a"))), 2)

    def test_keep_and_similar_are_not_batch_eligible(self):
        self.store.set(self.paths[0], "keep", "keep master audio")
        with_keep = [("Exact 1", self.paths[0]), ("Similar 1", self.paths[3])]
        rows = self.rows + [("Similar 1", self.paths[3], self.paths[3].stat().st_size)]
        safe, skipped = plan_marked_exact_duplicates(
            rows, with_keep, self.store
        )
        self.assertFalse(safe)
        self.assertEqual(len(skipped), 2)

    def test_missing_survivor_and_changed_payload_do_not_recycle(self):
        selected = self.rows[0]
        survivor = self.paths[2]
        survivor.unlink()
        # Keep a second listed peer but with changed bytes.
        self.paths[1].write_bytes(b"song is changed")
        recycle = Mock()
        successes, failures = recycle_marked_exact_duplicates(
            self.root, self.rows, [selected], self.store, recycle=recycle
        )
        self.assertEqual(successes, [])
        self.assertEqual(len(failures), 1)
        recycle.assert_not_called()
        self.assertTrue(selected[1].exists())

    def test_partial_failure_does_not_delete_other_items(self):
        def fail_first(p):
            if p == self.paths[0]:
                raise OSError("Recycle Bin unavailable")
        recycle = Mock(side_effect=fail_first)
        successes, failures = recycle_marked_exact_duplicates(
            self.root, self.rows, self.rows[:2], self.store, recycle=recycle
        )
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertTrue(self.paths[0].exists())
        self.assertTrue(self.paths[2].exists())

    def test_stop_before_second_file_does_not_delete_remaining(self):
        from threading import Event
        stopped = Event()
        def after_progress(done, total, path):
            if done == 1:
                stopped.set()
        trash = self.root / "fake-trash"
        trash.mkdir()
        successful, failures = recycle_marked_exact_duplicates(
            self.root, self.rows, self.rows[:2], self.store,
            recycle=lambda p: p.rename(trash / p.name),
            on_progress=after_progress, cancel_event=stopped
        )
        self.assertEqual(len(successful), 1)
        self.assertTrue(self.paths[1].exists())
        self.assertTrue(self.paths[2].exists())
        self.assertTrue(any("Stopped" in x for x in failures))


class BatchReviewUITests(unittest.IsolatedAsyncioTestCase):
    async def test_marks_persist_through_pages_and_clear(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            rows = []
            for i in range(152):
                p = root / f"song-{i:03d}.m4a"
                p.write_bytes(b"same audio")
                rows.append(("Exact 1", p, 10))
            screen = DuplicateReviewScreen(
                root, rows, 1, 0, root / "review.json"
            )
            app = App()
            async with app.run_test(size=(145, 43)) as pilot:
                app.push_screen(screen)
                await pilot.pause()
                screen.action_toggle_mark()
                await pilot.pause()
                self.assertEqual(len(screen._marked), 1)
                await pilot.click("#duplicate_next")
                await pilot.pause()
                screen.query_one("#duplicate_table", DataTable).focus()
                await pilot.pause()  # Allow Textual focus event to settle.
                screen.action_toggle_mark()
                await pilot.pause()
                self.assertEqual(len(screen._marked), 2)
                self.assertIn("Marked: 2", str(
                    screen.query_one("#duplicate_page").render()
                ))
                await pilot.click("#duplicate_clear_marks")
                await pilot.pause()
                self.assertEqual(len(screen._marked), 0)
                screen.dismiss(None)
                await pilot.pause()

    async def test_all_marked_shows_blocker_without_confirmation_or_files_lost(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = [root / "A.mp3", root / "B.mp3"]
            for p in files:
                p.write_bytes(b"same")
            screen = DuplicateReviewScreen(
                root, [("Exact 1", p, 4) for p in files],
                1, 0, root / "review.json",
            )
            app = App()
            async with app.run_test(size=(145, 43)) as pilot:
                app.push_screen(screen)
                await pilot.pause()
                screen._marked = {("Exact 1", p) for p in files}
                screen._show_page()
                await pilot.click("#duplicate_delete_marked")
                await pilot.pause()
                self.assertIs(app.screen, screen)
                self.assertTrue(all(p.exists() for p in files))
                self.assertIn("Unmark at least one", str(
                    screen.query_one("#duplicate_feedback").render()
                ))
                screen.dismiss(None)
                await pilot.pause()


if __name__ == "__main__":
    unittest.main()
