"""Duplicate-search progress dialog and safe cancellation regressions."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

from textual.app import App
from textual.widgets import Button, Static

from mdir_u.advanced import find_exact_duplicates
from mdir_u.base import BaseApp
from mdir_u.ui.duplicate_scan import DuplicateScanProgressScreen


class DuplicateProgressScreenTests(unittest.IsolatedAsyncioTestCase):
    async def test_explains_results_then_allows_safe_cancel(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            marker = root / "do-not-delete.txt"
            marker.write_bytes(b"protected")
            cancel = Event()
            screen = DuplicateScanProgressScreen(root, cancel)
            app = App()
            async with app.run_test(size=(120, 38)) as pilot:
                app.push_screen(screen)
                await pilot.pause()
                self.assertIs(app.screen, screen)
                self.assertIn(
                    "opens automatically",
                    str(screen.query_one("#duplicate_scan_help", Static).render()),
                )
                screen.update_progress(
                    12800,
                    "SHA-256: 12,800/17,500 candidate files verified.",
                )
                await pilot.pause()
                self.assertIn(
                    "12,800/17,500",
                    str(screen.query_one("#duplicate_scan_phase", Static).render()),
                )
                await pilot.click("#duplicate_scan_cancel")
                await pilot.pause()
                self.assertTrue(cancel.is_set())
                self.assertTrue(
                    screen.query_one("#duplicate_scan_cancel", Button).disabled
                )
                self.assertTrue(marker.exists())
                screen.dismiss(None)
                await pilot.pause()

    async def test_escape_does_not_leave_scan_running_uncontrolled(self):
        with tempfile.TemporaryDirectory() as folder:
            cancel = Event()
            screen = DuplicateScanProgressScreen(Path(folder), cancel)
            app = App()
            async with app.run_test(size=(120, 38)) as pilot:
                app.push_screen(screen)
                await pilot.pause()
                screen.key_escape()
                self.assertTrue(cancel.is_set())
                screen.dismiss(None)
                await pilot.pause()


class DuplicateScanLifecycleTests(unittest.TestCase):
    def test_scan_cancelled_during_hash_never_marks_or_deletes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            a, b = root / "first.bin", root / "second.bin"
            data = b"1" * (3 * 1024 * 1024)
            a.write_bytes(data)
            b.write_bytes(data)
            cancel = Event()
            messages = []

            def progress(count, phase):
                messages.append((count, phase))
                if count == 0 and "verification starting" in phase:
                    cancel.set()

            groups = find_exact_duplicates(root, cancel_event=cancel, progress=progress)
            self.assertEqual(groups, [])
            self.assertTrue(messages)
            self.assertTrue(a.is_file())
            self.assertTrue(b.is_file())
            self.assertEqual(a.read_bytes(), data)

    def test_progress_reports_total_hash_candidates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            a, b, c = root / "one.mp3", root / "two.m4a", root / "unique.txt"
            a.write_bytes(b"song!")
            b.write_bytes(b"song!")
            c.write_bytes(b"not the same")
            progress = []
            stats = {}
            groups = find_exact_duplicates(root, progress=lambda n, msg: progress.append((n,msg)), scan_stats=stats)
            self.assertEqual(len(groups), 1)
            self.assertEqual(stats["hash_candidates"], 2)
            self.assertEqual(stats["files_hashed"], 2)
            self.assertTrue(any("2/2 candidate files" in phase for _, phase in progress))

    def test_results_lifecycle_opens_review_even_when_no_duplicates(self):
        mock = SimpleNamespace(
            _close_duplicate_scan_progress=Mock(),
            _show_duplicate_review=Mock(),
            set_status=Mock(),
        )
        root = Path("G:\\")
        BaseApp._present_duplicate_scan_results(
            mock, root, [], 0, 0, "right", [], {"files_scanned": 12},
        )
        mock._close_duplicate_scan_progress.assert_called_once_with()
        mock._show_duplicate_review.assert_called_once_with(
            root, [], 0, 0, "right", [], {"files_scanned": 12},
        )
        self.assertIn("result", mock.set_status.call_args.args[0].lower())


if __name__ == "__main__":
    unittest.main()
