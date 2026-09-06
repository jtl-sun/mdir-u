from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from mdir_u.advanced import (
    FileIndex,
    FileMacro,
    MacroAction,
    MacroStore,
    OperationJournal,
    Workspace,
    WorkspaceStore,
    compare_directories,
    find_exact_duplicates,
    parse_safe_file_request,
    safe_sync_directories,
)
from mdir_u.file_operations import run_file_operation


class AdvancedFeatureTests(unittest.TestCase):
    def test_named_workspace_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = WorkspaceStore(Path(directory) / "workspaces.json")
            expected = Workspace("office", "C:/left", "C:/right", "right", True)
            store.save(expected)
            self.assertEqual(store.get("office"), expected)

    def test_copy_move_macro_round_trip_excludes_destructive_actions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MacroStore(Path(directory) / "macros.json")
            macro = FileMacro(
                "daily",
                (MacroAction("copy", ("/in/report.xlsx",), "/out", "left"),),
            )
            store.save(macro)
            self.assertEqual(store.get("daily"), macro)

    def test_copy_move_and_rename_are_safely_undoable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, destination = root / "source", root / "destination"
            source.mkdir()
            destination.mkdir()
            original = source / "report.txt"
            original.write_text("report", encoding="utf-8")
            result = run_file_operation("copy", (original,), destination)
            journal = OperationJournal(root / "journal.json")
            record = journal.record("copy", result.completed_pairs)
            self.assertEqual(journal.undo(record), [])
            self.assertFalse((destination / original.name).exists())

            moved = run_file_operation("move", (original,), destination)
            record = journal.record("move", moved.completed_pairs)
            self.assertEqual(journal.undo(record), [])
            self.assertTrue(original.exists())

            renamed = source / "renamed.txt"
            original.rename(renamed)
            record = journal.record("rename", ((original, renamed),))
            self.assertEqual(journal.undo(record), [])
            self.assertTrue(original.exists())

    def test_copy_undo_refuses_to_remove_modified_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, destination = root / "a.txt", root / "out"
            source.write_text("before", encoding="utf-8")
            destination.mkdir()
            result = run_file_operation("copy", (source,), destination)
            journal = OperationJournal(root / "journal.json")
            record = journal.record("copy", result.completed_pairs)
            target = destination / source.name
            time.sleep(0.002)
            target.write_text("edited after copy", encoding="utf-8")
            self.assertTrue(journal.undo(record))
            self.assertTrue(target.exists())

    def test_pause_stops_between_top_level_items(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, destination = root / "source", root / "destination"
            source.mkdir()
            destination.mkdir()
            files = []
            for index in range(3):
                path = source / f"{index}.txt"
                path.write_text(str(index), encoding="utf-8")
                files.append(path)
            pause, cancel = threading.Event(), threading.Event()
            cancel.mdir_pause_event = pause  # type: ignore[attr-defined]
            pause.set()
            holder: list[object] = []
            thread = threading.Thread(
                target=lambda: holder.append(
                    run_file_operation("copy", files, destination, cancel_event=cancel)
                )
            )
            thread.start()
            time.sleep(0.08)
            self.assertFalse(any(destination.iterdir()))
            pause.clear()
            thread.join(timeout=2)
            self.assertEqual(len(list(destination.iterdir())), 3)

    def test_mindex_duplicates_compare_and_safe_sync(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left, right = root / "left", root / "right"
            left.mkdir()
            right.mkdir()
            (left / "Quarterly Report.txt").write_text("same", encoding="utf-8")
            (left / "copy.txt").write_text("same", encoding="utf-8")
            (left / "only.txt").write_text("new", encoding="utf-8")
            index = FileIndex(root / "index.sqlite3")
            self.assertEqual(index.rebuild(left), 3)
            self.assertEqual(len(index.search(left, "quarter report")), 1)
            self.assertEqual(len(find_exact_duplicates(left)), 1)
            compared = compare_directories(left, right)
            pairs, errors = safe_sync_directories(left, right, compared)
            self.assertFalse(errors)
            self.assertEqual(len(pairs), 3)
            self.assertTrue((right / "only.txt").exists())

    def test_explicit_natural_language_file_plan(self) -> None:
        selected = (Path("/left/report.xlsx"),)
        plan = parse_safe_file_request(
            "/파일 선택한 파일을 오른쪽으로 복사",
            selected=selected,
            active_directory=Path("/left"),
            passive_directory=Path("/right"),
        )
        self.assertEqual(plan.operation, "copy")
        self.assertEqual(plan.destination, Path("/right"))

    def test_safe_sync_undo_removes_new_tree_only_when_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left, right = root / "left", root / "right"
            (left / "sub").mkdir(parents=True)
            right.mkdir()
            (left / "sub" / "new.txt").write_text("new", encoding="utf-8")
            pairs, errors = safe_sync_directories(
                left, right, compare_directories(left, right)
            )
            self.assertFalse(errors)
            journal = OperationJournal(root / "journal.json")
            record = journal.record("copy", pairs)
            self.assertEqual(journal.undo(record), [])
            self.assertFalse((right / "sub").exists())


if __name__ == "__main__":
    unittest.main()
