"""Background duplicate scanning: nonblocking UI, true hash %, results on demand."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

from textual.app import App
from textual.widgets import Static

from mdir_u.base import BaseApp
from mdir_u.ui.duplicate_scan import (
    DuplicateScanProgressScreen,
    duplicate_scan_status,
)


class BackgroundStatusTests(unittest.TestCase):
    def test_percentage_uses_real_sha256_candidate_count(self):
        status = duplicate_scan_status(
            "SHA-256: 625/1,763 candidate files verified. Current folder: G:\\Music", 625
        )
        self.assertIn("35.5%", status)
        self.assertIn("625/1,763", status)
        self.assertIn("Ctrl+Alt+D", status)

    def test_unknown_directory_total_is_not_falsely_shown_as_percent(self):
        status = duplicate_scan_status("scanning G:\\Music", 12800)
        self.assertIn("12,800", status)
        self.assertIn("total unknown", status)
        self.assertNotIn("%", status)

    def test_background_button_dismisses_without_cancelling_worker(self):
        cancel = Event()
        screen = SimpleNamespace(is_mounted=True, dismiss=Mock())
        timer = SimpleNamespace(stop=Mock())
        host = SimpleNamespace(
            _duplicate_scan_cancel=cancel,
            _duplicate_scan_screen=screen,
            _duplicate_scan_background=False,
            _duplicate_scan_badge="DUP SCAN SHA-256 35.5% (625/1,763)",
            _duplicate_scan_timer=None,
            set_interval=Mock(return_value=timer),
            _duplicate_scan_tick=Mock(),
            set_status=Mock(),
        )
        BaseApp._background_duplicate_scan(host, screen)
        self.assertFalse(cancel.is_set())
        self.assertTrue(host._duplicate_scan_background)
        self.assertIsNone(host._duplicate_scan_screen)
        host.set_interval.assert_called_once()
        screen.dismiss.assert_called_once_with(None)

    def test_finished_background_scan_does_not_interrupt_current_work(self):
        host = SimpleNamespace(
            _duplicate_scan_background=True,
            _duplicate_scan_ready=None,
            _close_duplicate_scan_progress=Mock(),
            _show_duplicate_review=Mock(),
            set_status=Mock(),
            notify=Mock(),
        )
        results = [("Exact 1", Path("G:\\Music\\copy.m4a"), 20)]
        root = Path("G:\\")
        BaseApp._present_duplicate_scan_results(
            host, root, results, 1, 0, "right", [], {"files_scanned": 50},
        )
        host._show_duplicate_review.assert_not_called()
        self.assertIsNotNone(host._duplicate_scan_ready)
        self.assertIn("Ctrl+Alt+D", host.set_status.call_args.args[0])
        # Manually return to results when it is convenient.
        BaseApp.action_show_duplicate_progress(host)
        host._show_duplicate_review.assert_called_once_with(
            root, results, 1, 0, "right", [], {"files_scanned": 50},
        )
        self.assertIsNone(host._duplicate_scan_ready)


class BackgroundDuplicateScreenTests(unittest.IsolatedAsyncioTestCase):
    async def test_background_button_allows_other_app_work(self):
        class Host(App):
            def __init__(self):
                super().__init__()
                self.background_screen = None
            def _background_duplicate_scan(self, screen):
                self.background_screen = screen
                screen.dismiss(None)

        with tempfile.TemporaryDirectory() as folder:
            cancel = Event()
            host = Host()
            screen = DuplicateScanProgressScreen(Path(folder), cancel)
            screen.update_progress(
                625, "SHA-256: 625/1,763 candidate files verified."
            )
            async with host.run_test(size=(135, 38)) as pilot:
                host.push_screen(screen)
                await pilot.pause()
                phase = screen.query_one("#duplicate_scan_phase", Static)
                self.assertIn("35.5%", str(phase.render()))
                await pilot.click("#duplicate_scan_background")
                await pilot.pause()
                self.assertIs(host.background_screen, screen)
                self.assertIsNot(host.screen, screen)
                self.assertFalse(cancel.is_set())


if __name__ == "__main__":
    unittest.main()
