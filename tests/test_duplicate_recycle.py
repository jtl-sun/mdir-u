"""Single-file recycle safety for Duplicate Review, with no real deletions."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from textual.app import App
from textual.widgets import DataTable

from mdir_u.duplicate_review import DuplicateReviewStore
from mdir_u.duplicate_cleanup import recycle_selected_exact_duplicate
from mdir_u.ui.duplicate_review import DuplicateReviewScreen


class DuplicateRecycleSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "music").mkdir()
        (self.root / "archive").mkdir()
        self.first = self.root / "music" / "song.m4a"
        self.second = self.root / "archive" / "copy.m4a"
        self.first.write_bytes(b"same song data")
        self.second.write_bytes(b"same song data")
        self.rows = [
            ("Exact 1", self.first, 14),
            ("Exact 1", self.second, 14),
        ]
        self.store = DuplicateReviewStore(self.root / "review.json")

    def test_single_selected_copy_recycles_and_keeps_survivor(self):
        destination = self.root / "simulated-recycle"
        recycle = Mock(side_effect=lambda path: path.rename(destination))
        survivor = recycle_selected_exact_duplicate(
            self.root, self.rows, self.rows[0], self.store, recycle=recycle
        )
        self.assertEqual(survivor, self.second)
        self.assertTrue(destination.exists())
        self.assertTrue(self.second.exists())
        recycle.assert_called_once_with(self.first)

    def test_keep_label_blocks_even_with_another_copy(self):
        self.store.set(self.first, "keep", "Master")
        recycle = Mock()
        with self.assertRaisesRegex(ValueError, "protected"):
            recycle_selected_exact_duplicate(
                self.root, self.rows, self.rows[0], self.store, recycle=recycle
            )
        recycle.assert_not_called()

    def test_last_copy_is_never_recycled(self):
        recycle = Mock()
        with self.assertRaisesRegex(ValueError, "No other listed copy"):
            recycle_selected_exact_duplicate(
                self.root, [self.rows[0]], self.rows[0], self.store,
                recycle=recycle,
            )
        recycle.assert_not_called()

    def test_similar_image_matches_are_not_exact_matches(self):
        recycle = Mock()
        selected = ("Similar 1", self.first, 14)
        with self.assertRaisesRegex(ValueError, "Only byte-identical"):
            recycle_selected_exact_duplicate(
                self.root, [selected, ("Similar 1", self.second, 14)],
                selected, self.store, recycle=recycle,
            )
        recycle.assert_not_called()

    def test_peer_changed_contents_prevents_recycle(self):
        self.second.write_bytes(b"different song")
        recycle = Mock()
        with self.assertRaisesRegex(ValueError, "No remaining byte-identical"):
            recycle_selected_exact_duplicate(
                self.root, self.rows, self.rows[0], self.store, recycle=recycle,
            )
        recycle.assert_not_called()

    def test_unavailable_copy_prevents_recycle(self):
        self.second.unlink()
        recycle = Mock()
        with self.assertRaisesRegex(ValueError, "No remaining byte-identical"):
            recycle_selected_exact_duplicate(
                self.root, self.rows, self.rows[0], self.store, recycle=recycle
            )
        recycle.assert_not_called()

    def test_external_file_outside_scan_root_cannot_be_recycled(self):
        with tempfile.TemporaryDirectory() as folder:
            other = Path(folder) / "outside.m4a"
            other.write_bytes(b"same song data")
            selected = ("Exact 1", other, 14)
            recycle = Mock()
            with self.assertRaisesRegex(ValueError, "outside"):
                recycle_selected_exact_duplicate(
                    self.root, [selected, self.rows[0]],
                    selected, self.store, recycle=recycle,
                )
            recycle.assert_not_called()

    def test_failure_to_recycle_is_not_replaced_by_permanent_delete(self):
        recycle = Mock(side_effect=OSError("Recycle Bin is full"))
        with self.assertRaisesRegex(OSError, "Recycle Bin is full"):
            recycle_selected_exact_duplicate(
                self.root, self.rows, self.rows[0], self.store, recycle=recycle,
            )
        self.assertTrue(self.first.exists())
        self.assertTrue(self.second.exists())


class DuplicateRecycleScreenTests(unittest.IsolatedAsyncioTestCase):
    async def test_select_row_stays_in_review_and_cancel_does_not_delete(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            a = root / "A.mp3"
            b = root / "B.mp3"
            a.write_bytes(b"same")
            b.write_bytes(b"same")
            screen = DuplicateReviewScreen(
                root, [("Exact 1", a, 4), ("Exact 1", b, 4)], 1, 0,
                root / "review.json",
            )
            app = App()
            async with app.run_test(size=(130, 45)) as pilot:
                app.push_screen(screen)
                await pilot.pause()
                table = screen.query_one("#duplicate_table", DataTable)
                table.move_cursor(row=1)
                await pilot.pause()
                self.assertIn("B.mp3", str(
                    screen.query_one("#duplicate_feedback").render()
                ))
                screen.row_selected(type("RowSelected", (), {"stop":lambda _:None})())
                self.assertIs(app.screen, screen)
                await pilot.click("#duplicate_delete")
                await pilot.pause()
                self.assertEqual(len(app.screen_stack), 3)
                await pilot.press("escape")
                await pilot.pause()
                self.assertIs(app.screen, screen)
                self.assertTrue(a.exists())
                self.assertTrue(b.exists())
                await pilot.click("#duplicate_keep")
                await pilot.pause()
                self.assertEqual(screen.store.get(b).status, "keep")
                self.assertTrue(screen.query_one("#duplicate_delete").disabled)
                screen.dismiss(None)
                await pilot.pause()


    async def test_confirmed_recycle_updates_rows_and_saves_precleanup_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            a, b = root / "A.mp3", root / "B.mp3"
            a.write_bytes(b"same")
            b.write_bytes(b"same")
            screen = DuplicateReviewScreen(
                root, [("Exact 1", a, 4), ("Exact 1", b, 4)], 1, 0,
                root / "review.json",
            )
            app = App()
            simulated_bin = root / "recycled-A.mp3"

            def safe_fake_recycle(_root, _rows, _selected, _store):
                self.assertEqual(_selected[1], a)
                a.rename(simulated_bin)
                return b

            with patch(
                "mdir_u.ui.duplicate_review.recycle_selected_exact_duplicate",
                side_effect=safe_fake_recycle,
            ):
                async with app.run_test(size=(135, 45)) as pilot:
                    app.push_screen(screen)
                    await pilot.pause()
                    await pilot.click("#duplicate_delete")
                    await pilot.pause()
                    self.assertFalse(simulated_bin.exists())
                    self.assertEqual(len(app.screen_stack), 3)
                    await pilot.click("#confirm_yes")
                    for _ in range(80):
                        await pilot.pause(0.05)
                        if not screen.results and screen._recycle_count == 1:
                            break
                    self.assertEqual(len(screen.results), 0)
                    self.assertEqual(screen.exact_groups, 0)
                    self.assertEqual(screen._resolved_groups, 1)
                    self.assertIn(
                        "RESULTS REFRESHED", screen._operation_message,
                    )
                    self.assertIn(
                        "RECYCLED: 1 file(s)",
                        str(screen.query_one("#duplicate_result_notice").render()),
                    )
                    self.assertEqual(len(app.screen_stack), 2)
                    self.assertTrue(b.exists())
                    self.assertTrue(simulated_bin.exists())
                    self.assertEqual(len(list((root / "reports").glob(
                        "duplicate-precleanup-*.csv"
                    ))), 1)
                    self.assertTrue(screen.query_one("#duplicate_delete").disabled)
                    screen.dismiss(None)
                    await pilot.pause()


if __name__ == "__main__":
    unittest.main()
