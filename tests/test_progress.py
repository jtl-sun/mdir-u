"""Regression coverage for the shared cross-platform progress contract."""
import unittest
from threading import Event

from mdir_u.progress import OperationCancelled, ProgressTracker


class ProgressTrackerTests(unittest.TestCase):
    def test_bytes_and_item_percentages(self):
        updates = []
        tracker = ProgressTracker("copy", total_items=2, total_bytes=100,
                                  callback=updates.append, interval=0)
        tracker.begin_item("first", 60)
        tracker.advance(30)
        self.assertEqual(tracker.snapshot().current_percent, 50)
        self.assertEqual(tracker.snapshot().overall_percent, 30)
        tracker.advance(30)
        tracker.complete_item()
        self.assertEqual(tracker.snapshot().items_done, 1)
        tracker.begin_item("second", 40)
        tracker.advance(40)
        tracker.complete_item()
        self.assertEqual(tracker.snapshot().overall_percent, 100)
        self.assertGreater(len(updates), 3)

    def test_unknown_search_total(self):
        tracker = ProgressTracker("search")
        tracker.scan(500, 19, "/tmp")
        state = tracker.snapshot()
        self.assertIsNone(state.overall_percent)
        self.assertEqual(state.items_done, 500)
        self.assertEqual(state.found, 19)

    def test_cancel_is_cooperative(self):
        cancel = Event()
        tracker = ProgressTracker("extract", cancel_event=cancel)
        cancel.set()
        with self.assertRaises(OperationCancelled):
            tracker.checkpoint()

    def test_zero_size_and_item_fallback(self):
        tracker = ProgressTracker("delete", total_items=2, total_bytes=0)
        tracker.complete_item()
        self.assertEqual(tracker.snapshot().overall_percent, 50)


if __name__ == "__main__":
    unittest.main()
