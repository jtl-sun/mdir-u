from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mdir_u.recent_folders import RecentFolderStore


class RecentFolderStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "recent_folders.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_record_is_mru_and_deduplicates(self) -> None:
        store = RecentFolderStore(self.path, limit=5)
        store.record("C:/one")
        store.record("D:/two")
        values = store.record("C:/one")
        self.assertEqual(values, ["C:/one", "D:/two"])
        self.assertEqual(store.load(), values)

    def test_limit_is_bounded(self) -> None:
        store = RecentFolderStore(self.path, limit=3)
        for index in range(6):
            store.record(f"C:/folder-{index}")
        self.assertEqual(
            store.load(),
            ["C:/folder-5", "C:/folder-4", "C:/folder-3"],
        )

    def test_remove_and_clear(self) -> None:
        store = RecentFolderStore(self.path)
        store.record("C:/one")
        store.record("D:/two")
        self.assertEqual(store.remove("D:/two"), ["C:/one"])
        store.clear()
        self.assertEqual(store.load(), [])

    def test_invalid_file_is_treated_as_empty(self) -> None:
        self.path.write_text("not-json", encoding="utf-8")
        self.assertEqual(RecentFolderStore(self.path).load(), [])

    def test_load_removes_duplicate_and_invalid_entries(self) -> None:
        self.path.write_text(
            json.dumps(["C:/one", "", 123, "C:/one", "D:/two"]),
            encoding="utf-8",
        )
        self.assertEqual(RecentFolderStore(self.path).load(), ["C:/one", "D:/two"])


if __name__ == "__main__":
    unittest.main()
