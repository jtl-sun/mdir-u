"""Integration tests for progress-bearing operations and archive cancellation."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from threading import Event

from mdir_u.file_operations import run_file_operation
from mdir_u.progress import OperationCancelled, ProgressTracker
from mdir_u.ui.archive import (
    CreateZipRequest,
    ExtractZipRequest,
    create_zip_archive,
    extract_zip_archive,
)


class ProgressIntegrationTests(unittest.TestCase):
    def test_copy_reports_bytes_and_two_levels(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "large.bin"
            source.write_bytes(b"x" * (2 * 1024 * 1024 + 31))
            target = Path(tmp) / "output"
            target.mkdir()
            reports = []
            tracker = ProgressTracker("copy", callback=reports.append, interval=0)
            result = run_file_operation("copy", [source], target, tracker=tracker)
            self.assertEqual(result.completed, 1)
            self.assertEqual((target / source.name).read_bytes(), source.read_bytes())
            self.assertTrue(any(x.current_percent is not None and 0 < x.current_percent < 100 for x in reports))
            self.assertEqual(tracker.snapshot().overall_percent, 100)

    def test_cancel_mid_file_preserves_source_and_no_partial_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "large.bin"
            source.write_bytes(b"a" * (3 * 1024 * 1024))
            output = Path(tmp) / "output"
            output.mkdir()
            cancel = Event()
            def report(state):
                if state.bytes_done >= 1024 * 1024:
                    cancel.set()
            tracker = ProgressTracker("copy", cancel_event=cancel, callback=report, interval=0)
            outcome = run_file_operation("copy", [source], output, tracker=tracker, cancel_event=cancel)
            self.assertTrue(outcome.cancelled)
            self.assertTrue(source.exists())
            self.assertFalse((output / source.name).exists())

    def test_zip_roundtrip_and_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.txt"
            source.write_bytes(b"abc" * (512 * 1024))
            archive = Path(tmp) / "data.zip"
            packed = ProgressTracker("compress", interval=0)
            result = create_zip_archive([source], CreateZipRequest(archive), tracker=packed)
            self.assertEqual(result.files, 1)
            self.assertEqual(packed.snapshot().overall_percent, 100)
            extracted = Path(tmp) / "extracted"
            unpacked = ProgressTracker("extract", interval=0)
            result = extract_zip_archive(archive, ExtractZipRequest(extracted), tracker=unpacked)
            self.assertEqual(result.files, 1)
            self.assertEqual(unpacked.snapshot().overall_percent, 100)
            self.assertEqual((extracted / source.name).read_bytes(), source.read_bytes())

    def test_cancel_zip_does_not_replace_existing_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "item.txt"
            source.write_text("some data")
            archive = Path(tmp) / "prior.zip"
            archive.write_bytes(b"existing archive")
            event = Event()
            event.set()
            tracker = ProgressTracker("compress", cancel_event=event)
            with self.assertRaises(OperationCancelled):
                create_zip_archive(
                    [source], CreateZipRequest(archive, overwrite=True),
                    tracker=tracker,
                )
            self.assertEqual(archive.read_bytes(), b"existing archive")


if __name__ == "__main__":
    unittest.main()
