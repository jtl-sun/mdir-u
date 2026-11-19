"""End-to-end confirmation -> bulk recycle for the exact marked set."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.app import App

from mdir_u.duplicate_cleanup import recycle_marked_exact_duplicates
from mdir_u.ui.dialogs import CompactConfirmScreen
from mdir_u.ui.duplicate_review import DuplicateReviewScreen


class MarkedBatchIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_seventeen_marked_recycle_in_one_confirm_and_keep_all_originals(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fake_bin = root / "_fake_bin"
            fake_bin.mkdir()
            rows = []
            originals = []
            copies = []
            for i in range(17):
                first = root / f"song-{i:03d}-original.m4a"
                duplicate = root / f"song-{i:03d}-copy.m4a"
                data = b"audio-" + bytes([i])
                first.write_bytes(data)
                duplicate.write_bytes(data)
                originals.append(first)
                copies.append(duplicate)
                rows.extend([
                    (f"Exact {i+1}", first, len(data)),
                    (f"Exact {i+1}", duplicate, len(data)),
                ])
            screen = DuplicateReviewScreen(
                root, rows, 17, 0, root / "review.json",
            )
            app = App()
            observed = []

            def simulated_batch(scan_root, rowset, selected, store, **kwargs):
                chosen = list(selected)
                observed.extend(chosen)
                return recycle_marked_exact_duplicates(
                    scan_root, rowset, chosen, store,
                    recycle=lambda path: path.rename(fake_bin / path.name),
                    **kwargs,
                )

            with patch(
                "mdir_u.ui.duplicate_review.recycle_marked_exact_duplicates",
                side_effect=simulated_batch,
            ):
                async with app.run_test(size=(134, 42)) as pilot:
                    app.push_screen(screen)
                    await pilot.pause()
                    screen._marked = {(f"Exact {i+1}", copies[i]) for i in range(17)}
                    screen._show_page()
                    await pilot.click("#duplicate_delete_marked")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, CompactConfirmScreen)
                    self.assertIn("ALL 17 MARKED", app.screen.message)
                    self.assertEqual(app.screen.yes_label, "Recycle All 17")
                    # A single explicit approval must recycle all 17, not one.
                    await pilot.click("#confirm_yes")
                    for _ in range(200):
                        await pilot.pause(0.05)
                        if not screen.results and not screen._recycling:
                            break
                    self.assertEqual(len(observed), 17)
                    self.assertEqual(len(screen.results), 0)
                    self.assertEqual(screen.exact_groups, 0)
                    self.assertEqual(screen._resolved_groups, 17)
                    self.assertIn(
                        "RECYCLED: 17 file(s)",
                        str(screen.query_one("#duplicate_result_notice").render()),
                    )
                    self.assertEqual(len(screen._marked), 0)
                    self.assertTrue(all(p.is_file() for p in originals))
                    self.assertTrue(all(not p.exists() for p in copies))
                    self.assertEqual(len(list(fake_bin.glob("*.m4a"))), 17)
                    self.assertTrue(list((root / "reports").glob(
                        "duplicate-precleanup-batch-*.csv"
                    )))
                    self.assertIn(
                        "17 moved to Trash",
                        screen._operation_message,
                    )
                    screen.dismiss(None)
                    await pilot.pause()

    async def test_more_than_old_hundred_limit_is_one_explicit_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            rows = []
            copies = []
            for i in range(101):
                first = root / f"a-{i:03d}.txt"
                copy = root / f"b-{i:03d}.txt"
                first.write_bytes(bytes([i]))
                copy.write_bytes(bytes([i]))
                rows.extend([
                    (f"Exact {i+1}", first, 1),
                    (f"Exact {i+1}", copy, 1),
                ])
                copies.append((f"Exact {i+1}", copy))
            screen = DuplicateReviewScreen(
                root, rows, 101, 0, root / "review.json"
            )
            app = App()
            async with app.run_test(size=(130, 40)) as pilot:
                app.push_screen(screen)
                await pilot.pause()
                screen._marked = set(copies)
                screen._show_page()
                await pilot.click("#duplicate_delete_marked")
                await pilot.pause()
                self.assertIsInstance(app.screen, CompactConfirmScreen)
                self.assertIn("ALL 101 MARKED", app.screen.message)
                await pilot.click("#confirm_cancel")
                await pilot.pause()
                self.assertIs(app.screen, screen)
                self.assertTrue(all(path.exists() for _, path, _ in rows))
                screen.dismiss(None)
                await pilot.pause()


if __name__ == "__main__":
    unittest.main()
