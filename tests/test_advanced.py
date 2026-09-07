from __future__ import annotations

import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from mdir_u.advanced import (
    FileIndex,
    FileMacro,
    MacroAction,
    MacroStore,
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
            # Every operation must release its SQLite handle. Windows refuses
            # to rename/delete an open database, unlike many Unix systems.
            database = root / "index.sqlite3"
            moved_database = root / "index-closed.sqlite3"
            database.replace(moved_database)
            moved_database.replace(database)
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

    def test_copy_and_move_block_directory_into_its_own_subtree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            child = root / "child"
            child.mkdir(parents=True)
            (root / "file.txt").write_text("data", encoding="utf-8")

            copied = run_file_operation("copy", (root,), child)
            self.assertTrue(copied.errors)
            self.assertFalse((child / root.name).exists())

            moved = run_file_operation("move", (root,), child)
            self.assertTrue(moved.errors)
            self.assertTrue(root.exists())

    def test_safe_sync_keeps_destination_on_file_folder_type_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left, right = root / "left", root / "right"
            left.mkdir()
            right.mkdir()
            (left / "item").write_text("source-file", encoding="utf-8")
            (right / "item").mkdir()
            (right / "item" / "keep.txt").write_text("keep", encoding="utf-8")

            pairs, errors = safe_sync_directories(
                left, right, compare_directories(left, right)
            )
            self.assertFalse(pairs)
            self.assertTrue(any("type conflict" in error for error in errors))
            self.assertTrue((right / "item" / "keep.txt").exists())
            self.assertFalse((right / "item" / "item").exists())

    def test_safe_sync_blocks_destination_inside_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            destination = source / "backup"
            destination.mkdir(parents=True)
            (source / "data.txt").write_text("data", encoding="utf-8")
            pairs, errors = safe_sync_directories(
                source, destination, compare_directories(source, destination)
            )
            self.assertFalse(pairs)
            self.assertTrue(any("inside the source tree" in error for error in errors))

    def test_cancelled_mindex_rebuild_preserves_previous_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            indexed = root / "files"
            indexed.mkdir()
            (indexed / "old.txt").write_text("old", encoding="utf-8")
            index = FileIndex(root / "index.sqlite3")
            self.assertEqual(index.rebuild(indexed), 1)

            (indexed / "new.txt").write_text("new", encoding="utf-8")
            cancel = threading.Event()
            cancel.set()
            self.assertEqual(index.rebuild(indexed, cancel_event=cancel), 0)
            self.assertEqual(len(index.search(indexed, "old")), 1)
            self.assertEqual(len(index.search(indexed, "new")), 0)

    def test_failed_copy_overwrite_preserves_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            destination = root / "out"
            destination.mkdir()
            source.write_text("new", encoding="utf-8")
            target = destination / source.name
            target.write_text("old", encoding="utf-8")

            def fail_after_partial_copy(src, dst, *args, **kwargs):
                Path(dst).write_text("partial", encoding="utf-8")
                raise OSError("simulated copy failure")

            with patch(
                "mdir_u.file_operations.shutil.copy2",
                side_effect=fail_after_partial_copy,
            ):
                result = run_file_operation(
                    "copy", (source,), destination, overwrite=True
                )

            self.assertTrue(result.errors)
            self.assertEqual(target.read_text(encoding="utf-8"), "old")
            self.assertFalse(
                any(".mdir-copy-" in path.name for path in destination.iterdir())
            )

    def test_failed_move_overwrite_restores_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            destination = root / "out"
            destination.mkdir()
            source.write_text("new", encoding="utf-8")
            target = destination / source.name
            target.write_text("old", encoding="utf-8")

            with patch(
                "mdir_u.file_operations.shutil.move",
                side_effect=OSError("simulated move failure"),
            ):
                result = run_file_operation(
                    "move", (source,), destination, overwrite=True
                )

            self.assertTrue(result.errors)
            self.assertTrue(source.exists())
            self.assertEqual(target.read_text(encoding="utf-8"), "old")
            self.assertFalse(
                any(".mdir-backup-" in path.name for path in destination.iterdir())
            )

    def test_directory_copy_overwrite_replaces_instead_of_merging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_parent = root / "source-parent"
            source = source_parent / "folder"
            destination = root / "out"
            target = destination / "folder"
            source.mkdir(parents=True)
            target.mkdir(parents=True)
            (source / "new.txt").write_text("new", encoding="utf-8")
            (target / "stale.txt").write_text("stale", encoding="utf-8")

            result = run_file_operation(
                "copy", (source,), destination, overwrite=True
            )
            self.assertFalse(result.errors)
            self.assertTrue((target / "new.txt").exists())
            self.assertFalse((target / "stale.txt").exists())


if __name__ == "__main__":
    unittest.main()
