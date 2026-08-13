from __future__ import annotations

import os
import sys
import tempfile
import unittest
import json
import threading
import time
import zipfile
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mdir_u.app import MDirApp
from mdir_u.preview.native import (
    PaneLayout,
    WindowRectangle,
    calculate_pane_rectangle,
)
from mdir_u.text_actions import DEFAULT_VIEW_LIMIT, inspect_safe_text_file
from mdir_u.shortcuts import (
    DEFAULT_SHORTCUTS,
    ShortcutDefinition,
    ensure_shortcut_config,
    expand_shortcut_text,
    load_shortcuts,
    parse_shortcuts,
    save_shortcuts,
)
from mdir_u.ui.shortcuts import ShortcutManagerScreen
from mdir_u import core as legacy
from mdir_u.ui.batch_rename import (
    BatchRenameOptions,
    BatchRenameScreen,
    RenamePair,
    apply_rename_pairs,
    build_rename_pairs,
)
from mdir_u.ui.search import (
    AdvancedSearchScreen,
    SearchRequest,
    search_files,
)
from mdir_u.ui.archive import (
    ArchiveError,
    CreateZipRequest,
    CreateZipScreen,
    ExtractZipRequest,
    ExtractZipScreen,
    create_zip_archive,
    extract_zip_archive,
    next_available_zip_path,
)
from mdir_u.file_operations import FileOperationResult, run_file_operation
from mdir_u.ui.dialogs import FileOperationProgressScreen


class PackageSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_f4_uses_nano_and_restores_the_file_pane(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "notes.txt"
            document.write_text("before", encoding="utf-8")
            app = MDirApp()
            app.left_start = root
            app.right_start = root
            app._save_paths = lambda: None

            async with app.run_test(size=(100, 24)) as pilot:
                for _ in range(100):
                    if app.left.initial_listing_complete:
                        break
                    await pilot.pause(0.02)
                app.left.table.move_cursor(
                    row=app.left.row_by_path[document], column=0
                )
                app.set_active("left")
                with (
                    patch("mdir_u.core.shutil.which", return_value="/usr/bin/nano"),
                    patch("mdir_u.core.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run,
                    patch.object(app, "suspend", return_value=nullcontext()),
                    patch.object(app, "set_status") as status,
                ):
                    app.action_edit()

                run.assert_called_once_with(
                    ["/usr/bin/nano", str(document)], check=False
                )
                status.assert_called_with(f"Finished editing: {document.name}")
                app.exit()

    async def test_f4_explains_how_to_install_nano(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "notes.txt"
            document.write_text("text", encoding="utf-8")
            app = MDirApp()
            app.left_start = root
            app.right_start = root
            app._save_paths = lambda: None

            async with app.run_test(size=(100, 24)) as pilot:
                for _ in range(100):
                    if app.left.initial_listing_complete:
                        break
                    await pilot.pause(0.02)
                app.left.table.move_cursor(
                    row=app.left.row_by_path[document], column=0
                )
                app.set_active("left")
                with (
                    patch("mdir_u.core.shutil.which", return_value=None),
                    patch.object(app, "set_status") as status,
                    patch.object(app, "notify") as notify,
                ):
                    app.action_edit()

                message = status.call_args.args[0]
                self.assertIn("sudo apt install nano", message)
                self.assertIn("sudo apt install nano", notify.call_args.args[0])
                app.exit()

    def test_more_than_one_thousand_files_copy_move_and_delete(self) -> None:
        """Large batches complete without per-item UI work or lost files."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            copied = root / "copied"
            moved = root / "moved"
            source.mkdir()
            copied.mkdir()
            moved.mkdir()
            paths = []
            for index in range(1_005):
                path = source / f"item-{index:04d}.txt"
                path.write_text(str(index), encoding="utf-8")
                paths.append(path)

            copy_result = run_file_operation("copy", paths, copied)
            self.assertEqual(copy_result.completed, 1_005)
            self.assertFalse(copy_result.errors)
            copied_paths = sorted(copied.iterdir())

            move_result = run_file_operation("move", copied_paths, moved)
            self.assertEqual(move_result.completed, 1_005)
            self.assertFalse(move_result.errors)
            self.assertFalse(any(copied.iterdir()))
            moved_paths = sorted(moved.iterdir())

            delete_result = run_file_operation("delete", moved_paths)
            self.assertEqual(delete_result.completed, 1_005)
            self.assertFalse(delete_result.errors)
            self.assertFalse(any(moved.iterdir()))

    def test_large_file_operation_can_cancel_between_items(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            paths = []
            for index in range(100):
                path = source / f"cancel-{index:03d}.txt"
                path.touch()
                paths.append(path)
            cancelled = threading.Event()

            def progress(completed: int, total: int, name: str) -> None:
                if completed == 25:
                    cancelled.set()

            result = run_file_operation(
                "copy",
                paths,
                destination,
                cancel_event=cancelled,
                progress=progress,
            )
            self.assertTrue(result.cancelled)
            self.assertEqual(result.completed, 25)
            self.assertEqual(len(list(destination.iterdir())), 25)

    def test_zip_default_name_avoids_existing_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "images.zip"
            second = root / "images (2).zip"
            first.write_bytes(b"old")
            self.assertEqual(next_available_zip_path(first), second)
            second.write_bytes(b"old too")
            self.assertEqual(
                next_available_zip_path(first), root / "images (3).zip"
            )

    def test_zip_overwrite_is_atomic_and_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.txt"
            source.write_text("new", encoding="utf-8")
            archive = root / "sample.zip"
            archive.write_bytes(b"existing")

            with self.assertRaises(ArchiveError):
                create_zip_archive([source], CreateZipRequest(archive))
            self.assertEqual(archive.read_bytes(), b"existing")

            create_zip_archive(
                [source], CreateZipRequest(archive, overwrite=True)
            )
            with zipfile.ZipFile(archive) as opened:
                self.assertEqual(opened.read("sample.txt"), b"new")

    def test_application_shortcuts_do_not_shadow_command_palette(self) -> None:
        actions = {binding.key: binding.action for binding in MDirApp.BINDINGS}
        self.assertNotIn("ctrl+p", actions)
        self.assertEqual(actions["alt+enter"], "properties")

    def test_zip_rejects_destination_inside_selected_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "designs"
            source.mkdir()
            (source / "sample.txt").write_text("sample", encoding="utf-8")

            with self.assertRaises(ArchiveError):
                create_zip_archive(
                    [source],
                    CreateZipRequest(source / "archive.zip"),
                )
            self.assertFalse((source / "archive.zip").exists())

    def test_zip_rejects_member_tree_conflicts_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "conflict.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("folder", "not a directory")
                archive.writestr("folder/item.txt", "must be rejected")

            destination = root / "out"
            with self.assertRaises(ArchiveError):
                extract_zip_archive(
                    archive_path,
                    ExtractZipRequest(destination),
                )
            self.assertFalse((destination / "folder").exists())

    def test_zip_create_and_extract_preserve_tree_and_empty_folders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "designs"
            source.mkdir()
            (source / "sea-glass.txt").write_text("blue", encoding="utf-8")
            nested = source / "collection"
            nested.mkdir()
            (nested / "cuff.txt").write_text("gold", encoding="utf-8")
            (source / "empty").mkdir()
            archive = root / "designs.zip"

            created = create_zip_archive(
                [source], CreateZipRequest(archive, compression_level=6)
            )
            self.assertEqual(created.files, 2)
            self.assertTrue(archive.is_file())
            with zipfile.ZipFile(archive) as opened:
                self.assertIn("designs/sea-glass.txt", opened.namelist())
                self.assertIn("designs/collection/cuff.txt", opened.namelist())
                self.assertIn("designs/empty/", opened.namelist())

            destination = root / "restored"
            extracted = extract_zip_archive(
                archive, ExtractZipRequest(destination)
            )
            self.assertEqual(extracted.files, 2)
            self.assertEqual(
                (destination / "designs" / "collection" / "cuff.txt").read_text(
                    encoding="utf-8"
                ),
                "gold",
            )
            self.assertTrue((destination / "designs" / "empty").is_dir())

    def test_zip_extract_blocks_traversal_symlinks_and_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            traversal = root / "traversal.zip"
            with zipfile.ZipFile(traversal, "w") as archive:
                archive.writestr("../escape.txt", "blocked")
            with self.assertRaises(ArchiveError):
                extract_zip_archive(traversal, ExtractZipRequest(root / "out"))
            self.assertFalse((root / "escape.txt").exists())

            symlink = root / "symlink.zip"
            with zipfile.ZipFile(symlink, "w") as archive:
                info = zipfile.ZipInfo("link")
                info.create_system = 3
                info.external_attr = 0o120777 << 16
                archive.writestr(info, "target")
            with self.assertRaises(ArchiveError):
                extract_zip_archive(symlink, ExtractZipRequest(root / "links"))

            invalid_name = root / "invalid-name.zip"
            with zipfile.ZipFile(invalid_name, "w") as archive:
                archive.writestr("CON.txt", "blocked")
            with self.assertRaises(ArchiveError):
                extract_zip_archive(
                    invalid_name, ExtractZipRequest(root / "invalid-names")
                )

            normal = root / "normal.zip"
            with zipfile.ZipFile(normal, "w") as archive:
                archive.writestr("same.txt", "new")
            destination = root / "collision"
            destination.mkdir()
            existing = destination / "same.txt"
            existing.write_text("old", encoding="utf-8")
            with self.assertRaises(ArchiveError):
                extract_zip_archive(normal, ExtractZipRequest(destination))
            self.assertEqual(existing.read_text(encoding="utf-8"), "old")
            extract_zip_archive(
                normal, ExtractZipRequest(destination, overwrite=True)
            )
            self.assertEqual(existing.read_text(encoding="utf-8"), "new")

    async def test_zip_dialogs_open_from_keyboard_shortcuts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.txt"
            source.write_text("sample", encoding="utf-8")
            archive = root / "sample.zip"
            with zipfile.ZipFile(archive, "w") as opened:
                opened.write(source, source.name)

            app = MDirApp()
            app.left_start = root
            app.right_start = root
            app._save_paths = lambda: None
            async with app.run_test(size=(120, 35)) as pilot:
                for _ in range(100):
                    if app.left.initial_listing_complete:
                        break
                    await pilot.pause(0.02)
                app.set_active("left")
                app.left.marked = {source}
                app.left.table.focus()
                await pilot.press("alt+f5")
                await pilot.pause()
                self.assertIsInstance(app.screen, CreateZipScreen)
                await pilot.press("escape")
                await pilot.pause()

                app.left.marked = {archive}
                await pilot.press("alt+f6")
                await pilot.pause()
                self.assertIsInstance(app.screen, ExtractZipScreen)
                await pilot.press("escape")
                app.exit()

    async def test_zip_operations_default_to_opposite_pane_in_both_directions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left_dir = root / "left"
            right_dir = root / "right"
            left_dir.mkdir()
            right_dir.mkdir()
            left_file = left_dir / "left-design.txt"
            right_file = right_dir / "right-design.txt"
            left_file.write_text("left", encoding="utf-8")
            right_file.write_text("right", encoding="utf-8")
            left_archive = left_dir / "left-design.zip"
            right_archive = right_dir / "right-design.zip"
            with zipfile.ZipFile(left_archive, "w") as opened:
                opened.writestr("from-left.txt", "left archive")
            with zipfile.ZipFile(right_archive, "w") as opened:
                opened.writestr("from-right.txt", "right archive")

            app = MDirApp()
            app.left_start = left_dir
            app.right_start = right_dir
            app._save_paths = lambda: None
            async with app.run_test(size=(120, 35)) as pilot:
                for _ in range(100):
                    if (
                        app.left.initial_listing_complete
                        and app.right.initial_listing_complete
                    ):
                        break
                    await pilot.pause(0.02)

                app.set_active("left")
                app.left.marked = {left_file}
                app.left.table.focus()
                await pilot.press("alt+f5")
                await pilot.pause()
                self.assertIsInstance(app.screen, CreateZipScreen)
                self.assertEqual(app.screen.destination.parent, right_dir)
                await pilot.press("escape")
                await pilot.pause()

                app.set_active("right")
                app.right.marked = {right_file}
                app.right.table.focus()
                await pilot.press("alt+f5")
                await pilot.pause()
                self.assertIsInstance(app.screen, CreateZipScreen)
                self.assertEqual(app.screen.destination.parent, left_dir)
                await pilot.press("escape")
                await pilot.pause()

                app.set_active("left")
                app.left.marked = {left_archive}
                app.left.table.focus()
                await pilot.press("alt+f6")
                await pilot.pause()
                self.assertIsInstance(app.screen, ExtractZipScreen)
                self.assertEqual(app.screen.destination, right_dir)
                await pilot.press("escape")
                await pilot.pause()

                app.set_active("right")
                app.right.marked = {right_archive}
                app.right.table.focus()
                await pilot.press("alt+f6")
                await pilot.pause()
                self.assertIsInstance(app.screen, ExtractZipScreen)
                self.assertEqual(app.screen.destination, left_dir)
                await pilot.press("escape")
                app.exit()

    async def test_zip_dialog_stays_open_for_unapproved_existing_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.txt"
            source.write_text("sample", encoding="utf-8")
            archive = root / "sample.zip"
            archive.write_bytes(b"keep me")

            app = MDirApp()
            app.left_start = root
            app.right_start = root
            app._save_paths = lambda: None
            async with app.run_test(size=(100, 30)) as pilot:
                screen = CreateZipScreen((source,), archive)
                app.push_screen(screen)
                await pilot.pause()
                screen.query_one("#archive_accept").press()
                await pilot.pause()

                self.assertIs(app.screen, screen)
                self.assertEqual(archive.read_bytes(), b"keep me")
                await pilot.press("escape")
                app.exit()

    async def test_zip_creation_runs_in_background_and_refreshes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.txt"
            source.write_text("sample", encoding="utf-8")
            destination = root / "sample.zip"

            app = MDirApp()
            app.left_start = root
            app.right_start = root
            app._save_paths = lambda: None
            async with app.run_test(size=(100, 30)) as pilot:
                for _ in range(100):
                    if (
                        app.left.initial_listing_complete
                        and app.right.initial_listing_complete
                    ):
                        break
                    await pilot.pause(0.02)

                app._archive_busy = True
                app._create_zip_in_background(
                    (source,),
                    CreateZipRequest(destination),
                    "left",
                )
                for _ in range(100):
                    if not app._archive_busy:
                        break
                    await pilot.pause(0.02)

                self.assertFalse(app._archive_busy)
                self.assertTrue(destination.is_file())
                self.assertIn(destination, app.left.entries)
                app.exit()

    async def test_zip_extraction_runs_in_background_and_refreshes_opposite_pane(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left_dir = root / "left"
            right_dir = root / "right"
            left_dir.mkdir()
            right_dir.mkdir()
            archive = left_dir / "designs.zip"
            with zipfile.ZipFile(archive, "w") as opened:
                opened.writestr("extracted-design.txt", "ready")

            app = MDirApp()
            app.left_start = left_dir
            app.right_start = right_dir
            app._save_paths = lambda: None
            async with app.run_test(size=(100, 30)) as pilot:
                for _ in range(100):
                    if (
                        app.left.initial_listing_complete
                        and app.right.initial_listing_complete
                    ):
                        break
                    await pilot.pause(0.02)

                app._archive_busy = True
                app._extract_zip_in_background(
                    archive,
                    ExtractZipRequest(right_dir),
                    "left",
                )
                for _ in range(100):
                    if not app._archive_busy:
                        break
                    await pilot.pause(0.02)

                extracted = right_dir / "extracted-design.txt"
                self.assertFalse(app._archive_busy)
                self.assertEqual(extracted.read_text(encoding="utf-8"), "ready")
                self.assertIn(extracted, app.right.entries)
                app.exit()

    def test_file_search_patterns_depth_content_and_hidden_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Report-One.TXT").write_text(
                "Quarterly jewelry sales",
                encoding="utf-8",
            )
            (root / "photo.jpg").write_bytes(b"not text")
            (root / ".private.txt").write_text("hidden", encoding="utf-8")
            nested = root / "nested"
            nested.mkdir()
            (nested / "report-two.txt").write_text(
                "Quarterly sea glass sales",
                encoding="utf-16",
            )
            deeper = nested / "deeper"
            deeper.mkdir()
            (deeper / "report-three.txt").write_text(
                "Quarterly sales",
                encoding="utf-8",
            )

            outcome = search_files(
                SearchRequest(
                    root=root,
                    name_pattern="*.txt; *.md",
                    include_directories=False,
                    max_depth=1,
                    content_text="jewelry",
                )
            )
            self.assertFalse(outcome.error)
            self.assertEqual(
                [result.path.name for result in outcome.results],
                ["Report-One.TXT"],
            )

            outcome = search_files(
                SearchRequest(
                    root=root,
                    name_pattern=r"^report-.*\.txt$",
                    regular_expression=True,
                    include_directories=False,
                    max_depth=1,
                )
            )
            self.assertEqual(
                {result.path.name for result in outcome.results},
                {"Report-One.TXT", "report-two.txt"},
            )

            outcome = search_files(
                SearchRequest(
                    root=root,
                    name_pattern="private",
                    include_directories=False,
                    include_hidden_system=True,
                )
            )
            self.assertEqual(
                [result.path.name for result in outcome.results],
                [".private.txt"],
            )

    def test_file_search_limit_and_pre_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(10):
                (root / f"item-{index:02d}.dat").write_bytes(b"x")

            limited = search_files(
                SearchRequest(root=root, result_limit=3)
            )
            self.assertEqual(len(limited.results), 3)
            self.assertTrue(limited.truncated)

            cancel_event = threading.Event()
            cancel_event.set()
            cancelled = search_files(
                SearchRequest(root=root),
                cancel_event=cancel_event,
            )
            self.assertTrue(cancelled.cancelled)
            self.assertEqual(cancelled.scanned, 0)

    async def test_file_search_screen_opens_from_active_pane(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "find-me.txt").write_text("needle", encoding="utf-8")

            app = MDirApp()
            app.left_start = root
            app.right_start = root
            app._save_paths = lambda: None
            async with app.run_test(size=(120, 38)) as pilot:
                for _ in range(100):
                    if app.left.initial_listing_complete:
                        break
                    await pilot.pause(0.02)

                app.set_active("left")
                await pilot.press("ctrl+f")
                await pilot.pause()
                self.assertIsInstance(app.screen, AdvancedSearchScreen)
                self.assertTrue(os.path.samefile(app.screen.initial_root, root))
                self.assertTrue(
                    os.path.samefile(
                        app.screen.query_one("#search_root").value,
                        root,
                    )
                )
                await pilot.press("escape")
                app.exit()

    async def test_batch_rename_screen_opens_for_marked_items(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            items = [root / "alpha.jpg", root / "beta.jpg"]
            for item in items:
                item.write_bytes(b"test")

            app = MDirApp()
            app.left_start = root
            app.right_start = root
            app._save_paths = lambda: None
            async with app.run_test(size=(120, 35)) as pilot:
                for _ in range(100):
                    if app.left.initial_listing_complete:
                        break
                    await pilot.pause(0.02)
                app.left.marked = set(items)
                app.set_active("left")
                app.left.table.focus()
                await pilot.press("ctrl+f2")
                await pilot.pause()
                self.assertIsInstance(app.screen, BatchRenameScreen)
                preview = app.screen.query_one("#rename_preview")
                self.assertEqual(preview.row_count, 2)
                await pilot.press("escape")
                app.exit()

    def test_batch_rename_preview_counter_and_extension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            items = [root / "alpha.jpg", root / "beta.png"]
            for item in items:
                item.write_bytes(b"test")
            pairs, errors = build_rename_pairs(
                items,
                BatchRenameOptions(
                    name_pattern="photo_[C]_[N]",
                    extension_pattern="[E]",
                    start=5,
                    step=2,
                    digits=3,
                ),
            )
            self.assertEqual(errors, [])
            self.assertEqual(
                [pair.target.name for pair in pairs],
                ["photo_005_alpha.jpg", "photo_007_beta.png"],
            )

            pairs, errors = build_rename_pairs(
                items,
                BatchRenameOptions(name_pattern="[N1-2]", extension_pattern="[E]"),
            )
            self.assertEqual(errors, [])
            self.assertEqual(
                [pair.target.name for pair in pairs], ["al.jpg", "be.png"]
            )

    def test_batch_rename_rejects_duplicates_and_rolls_back_safely(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            items = [root / "a.txt", root / "b.txt"]
            items[0].write_text("A", encoding="utf-8")
            items[1].write_text("B", encoding="utf-8")
            _pairs, errors = build_rename_pairs(
                items,
                BatchRenameOptions(name_pattern="same", extension_pattern="txt"),
            )
            self.assertTrue(errors)

            swap_pairs = [
                RenamePair(items[0], items[1]),
                RenamePair(items[1], items[0]),
            ]
            apply_rename_pairs(swap_pairs)
            self.assertEqual(items[0].read_text(encoding="utf-8"), "B")
            self.assertEqual(items[1].read_text(encoding="utf-8"), "A")
    def test_current_widgets_are_connected_without_monkey_patching(self) -> None:
        from mdir_u import core
        from mdir_u.base import BaseApp
        from mdir_u.ui.dialogs import CompactConfirmScreen
        from mdir_u.ui.prompt import CompactPromptScreen
        from mdir_u.ui.rename import SlowRenameDataTable
        from mdir_u.ui.viewer import CompactViewerScreen

        self.assertIsNot(core.MDirDataTable, SlowRenameDataTable)
        self.assertIs(BaseApp.PROMPT_SCREEN, CompactPromptScreen)
        self.assertIs(BaseApp.CONFIRM_SCREEN, CompactConfirmScreen)
        self.assertIs(BaseApp.VIEWER_SCREEN, CompactViewerScreen)

    async def test_enter_confirms_move_and_delete_dialogs(self) -> None:
        """Move/Delete must run when Enter is pressed on their dialog."""
        from textual.widgets import Button

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left_root = root / "left"
            right_root = root / "right"
            left_root.mkdir()
            right_root.mkdir()
            source = left_root / "move-with-enter.txt"
            source.write_text("confirm me", encoding="utf-8")

            app = MDirApp()
            app.left_start = left_root
            app.right_start = right_root
            app._save_paths = lambda: None

            async with app.run_test(size=(100, 24)) as pilot:
                for _ in range(100):
                    if (
                        app.left.initial_listing_complete
                        and app.right.initial_listing_complete
                    ):
                        break
                    await pilot.pause(0.02)

                app.set_active("left")
                app.left.marked = {source}
                app.action_move()
                await pilot.pause()
                self.assertEqual(
                    app.screen.focused.id,
                    "confirm_yes",
                    "Move confirmation must default to Yes",
                )
                await pilot.press("enter")
                for _ in range(200):
                    if not app._file_operation_busy:
                        break
                    await pilot.pause(0.01)

                moved = right_root / source.name
                self.assertFalse(source.exists())
                self.assertTrue(moved.exists())

                app.set_active("right")
                app.right.marked = {moved}
                app.action_delete()
                await pilot.pause()
                self.assertIsInstance(app.screen.focused, Button)
                self.assertEqual(
                    app.screen.focused.id,
                    "confirm_yes",
                    "Delete confirmation must default to Yes",
                )
                await pilot.press("enter")
                for _ in range(200):
                    if not app._file_operation_busy:
                        break
                    await pilot.pause(0.01)

                self.assertFalse(moved.exists())
                app.exit()

    async def test_background_file_operation_ui_can_cancel_without_freezing(
        self,
    ) -> None:
        """The progress modal must continue receiving keys during disk work."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left_root = root / "left"
            right_root = root / "right"
            left_root.mkdir()
            right_root.mkdir()
            source = left_root / "slow.txt"
            source.touch()
            worker_started = threading.Event()

            def slow_operation(
                operation,
                items,
                destination=None,
                *,
                new_name=None,
                cancel_event=None,
                progress=None,
            ):
                worker_started.set()
                while cancel_event is not None and not cancel_event.is_set():
                    time.sleep(0.005)
                return FileOperationResult(
                    operation=operation,
                    total=len(tuple(items)),
                    cancelled=True,
                )

            app = MDirApp()
            app.left_start = left_root
            app.right_start = right_root
            app._save_paths = lambda: None

            with patch("mdir_u.base.run_file_operation", slow_operation):
                async with app.run_test(size=(100, 24)) as pilot:
                    for _ in range(100):
                        if (
                            app.left.initial_listing_complete
                            and app.right.initial_listing_complete
                        ):
                            break
                        await pilot.pause(0.02)

                    app.set_active("left")
                    app.left.marked = {source}
                    app.action_copy()
                    await pilot.pause()
                    await pilot.press("enter")
                    for _ in range(100):
                        if worker_started.is_set():
                            break
                        await pilot.pause(0.01)

                    self.assertTrue(app._file_operation_busy)
                    self.assertIsInstance(
                        app.screen, FileOperationProgressScreen
                    )
                    await pilot.press("escape")
                    for _ in range(200):
                        if not app._file_operation_busy:
                            break
                        await pilot.pause(0.01)

                    self.assertFalse(app._file_operation_busy)
                    self.assertFalse(right_root.joinpath(source.name).exists())
                    app.exit()

    async def test_shift_range_and_fast_right_drag_do_not_skip_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = [root / f"item-{index:02d}.txt" for index in range(10)]
            for path in files:
                path.write_text(path.name, encoding="utf-8")

            app = MDirApp()
            app.left_start = root
            app.right_start = root
            app._save_paths = lambda: None

            async with app.run_test(size=(120, 35)) as pilot:
                for _ in range(100):
                    if app.left.initial_listing_complete:
                        break
                    await pilot.pause(0.02)

                pane = app.left
                start_row = pane.row_by_path[files[1]]
                end_row = pane.row_by_path[files[8]]
                pane.table.move_cursor(row=start_row, column=0)
                pane.reset_shift_selection_anchor()

                app.set_active("left")
                pane.table.focus()
                await pilot.press("shift+down")
                self.assertEqual(
                    pane.marked,
                    {pane.entries[start_row], pane.entries[start_row + 1]},
                )

                pane.marked.clear()
                pane.table.move_cursor(row=start_row, column=0)
                pane.reset_shift_selection_anchor()
                pane.select_range_to(end_row)

                expected = {
                    path
                    for path in pane.entries[start_row : end_row + 1]
                    if path is not None
                }
                self.assertEqual(pane.marked, expected)
                self.assertEqual(pane.table.cursor_row, end_row)

                pane.marked.clear()
                pane.reset_shift_selection_anchor()
                pane.table._drag_rows_seen.clear()
                pane.table._right_drag_last_row = None
                pane.table._toggle_drag_range_to(start_row)
                pane.table._toggle_drag_range_to(end_row)
                self.assertEqual(pane.marked, expected)
                app.exit()

    async def test_right_drag_auto_scroll_continues_selection_beyond_page(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = [root / f"item-{index:03d}.txt" for index in range(80)]
            for path in files:
                path.write_text(path.name, encoding="utf-8")

            app = MDirApp()
            app.left_start = root
            app.right_start = root
            app._save_paths = lambda: None

            async with app.run_test(size=(100, 18)) as pilot:
                for _ in range(100):
                    if app.left.initial_listing_complete:
                        break
                    await pilot.pause(0.02)

                pane = app.left
                table = pane.table
                start_row = pane.row_by_path[files[2]]
                table._right_dragging = True
                table._drag_rows_seen.clear()
                table._right_drag_last_row = None
                table._toggle_drag_range_to(start_row)
                table._right_drag_scroll_direction = 1

                steps = table.size.height + 5
                for _ in range(steps):
                    table._right_drag_auto_scroll_tick()
                    await pilot.pause(0)

                end_row = start_row + steps
                expected = {
                    path
                    for path in pane.entries[start_row : end_row + 1]
                    if path is not None
                }
                self.assertEqual(pane.marked, expected)
                self.assertEqual(table.cursor_row, end_row)
                self.assertGreater(int(table.scroll_offset.y), 0)
                table.end_right_drag()
                app.exit()

    def test_filename_and_extension_are_visually_separated(self) -> None:
        path = Path("sample.design.png")
        self.assertEqual(
            legacy.display_file_title(path, is_directory=False),
            "sample.design",
        )
        self.assertEqual(legacy.display_extension(".png"), "   png")
        self.assertEqual(
            legacy.display_file_title(Path("folder.name"), is_directory=True),
            "folder.name",
        )

    async def test_both_panels_auto_refresh_after_external_delete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            victim = root / "delete-me.txt"
            victim.write_text("temporary", encoding="utf-8")

            app = MDirApp()
            app.left_start = root
            app.right_start = root
            app._save_paths = lambda: None

            async with app.run_test(size=(100, 24)) as pilot:
                for _ in range(100):
                    if (
                        app.left.initial_listing_complete
                        and app.right.initial_listing_complete
                        and victim in app.left.entries
                        and victim in app.right.entries
                    ):
                        break
                    await pilot.pause(0.02)

                self.assertIn(victim, app.left.entries)
                self.assertIn(victim, app.right.entries)
                victim.unlink()

                for _ in range(100):
                    if (
                        victim not in app.left.entries
                        and victim not in app.right.entries
                    ):
                        break
                    await pilot.pause(0.03)

                self.assertNotIn(victim, app.left.entries)
                self.assertNotIn(victim, app.right.entries)
                app.exit()

    async def test_pane_details_remain_visible_below_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "folder"
            folder.mkdir()

            app = MDirApp()
            app.left_start = root
            app.right_start = root
            app._save_paths = lambda: None

            async with app.run_test(size=(100, 22)) as pilot:
                for _ in range(100):
                    if app.left.initial_listing_complete:
                        break
                    await pilot.pause(0.02)

                app.left.table.move_cursor(
                    row=app.left.row_by_path[folder],
                    column=0,
                )
                app.left.update_info()
                await pilot.pause()

                summary = app.left.query_one(".pane_summary")
                details = app.left.query_one(".pane_info")
                summary_text = str(summary.render())
                self.assertTrue(details.visible)
                self.assertEqual(summary.content_region.height, 1)
                self.assertIn("Capacity:", summary_text)
                self.assertIn("Files:", summary_text)
                self.assertIn("Folders:", summary_text)
                self.assertEqual(details.region.height, 3)
                self.assertEqual(details.content_region.height, 3)
                self.assertEqual(details.region.y, summary.region.bottom)
                self.assertLessEqual(details.region.bottom, app.left.region.bottom)
                self.assertIn("Name: folder", str(details.render()))
                self.assertIn(f"Path: {folder}", str(details.render()))
                app.exit()

    async def test_shortcut_bar_and_folder_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "destination"
            destination.mkdir()

            app = MDirApp()
            app.left_start = root
            app.right_start = root
            app.shortcuts = [
                ShortcutDefinition(
                    "Destination",
                    "folder",
                    str(destination),
                    pane="right",
                )
            ]
            app._save_paths = lambda: None

            async with app.run_test(size=(100, 32)) as pilot:
                for _ in range(100):
                    if app.left.initial_listing_complete:
                        break
                    await pilot.pause(0.02)

                button = app.query_one("#shortcut_0")
                self.assertTrue(button.display)
                self.assertEqual(str(button.label), "Destination")

                await app._activate_shortcut(app.shortcuts[0])
                self.assertEqual(app.right.current_path, destination.resolve())
                self.assertEqual(app.active_side, "right")

                await pilot.click("#shortcut_edit")
                await pilot.pause(0.05)
                self.assertIsInstance(app.screen, ShortcutManagerScreen)
                await pilot.click("#shortcut_cancel")
                await pilot.pause(0.05)
                self.assertNotIsInstance(app.screen, ShortcutManagerScreen)
                app.exit()

    async def test_ai_panel_is_loaded_only_when_requested(self) -> None:
        app = MDirApp()
        self.assertNotIn("mdir_u.ai.panel", sys.modules)

        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause(0.05)
            self.assertFalse(list(app.query("#ai_panel")))

            await app.action_toggle_ai_terminal()
            await pilot.pause(0.05)
            self.assertTrue(app.ai_mode)
            self.assertEqual(len(list(app.query("#ai_panel"))), 1)

            await app.action_toggle_ai_terminal()
            await pilot.pause(0.05)
            self.assertFalse(app.ai_mode)
            self.assertTrue(app.right.table.has_focus)
            app.exit()

    async def test_listing_and_theme_switch(self) -> None:
        previous = os.environ.get("MDIR_NATIVE_PREVIEW")
        os.environ["MDIR_NATIVE_PREVIEW"] = "0"
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "folder").mkdir()
                (root / "note.txt").write_text(
                    "hello",
                    encoding="utf-8",
                )

                app = MDirApp()
                app.left_start = root
                app.right_start = root
                app._save_paths = lambda: None

                async with app.run_test(size=(120, 35)) as pilot:
                    for _ in range(100):
                        if (
                            app.left.initial_listing_complete
                            and len(app.left.entries) >= 3
                        ):
                            break
                        await pilot.pause(0.02)

                    self.assertIn(root / "folder", app.left.entries)
                    self.assertIn(root / "note.txt", app.left.entries)
                    self.assertEqual(
                        app.left.styles.background.hex,
                        "#202020",
                    )

                    app.theme = "textual-light"
                    await pilot.pause()
                    await pilot.pause()
                    self.assertEqual(
                        app.left.styles.background.hex,
                        "#E0E0E0",
                    )
                    app.exit()
        finally:
            if previous is None:
                os.environ.pop("MDIR_NATIVE_PREVIEW", None)
            else:
                os.environ["MDIR_NATIVE_PREVIEW"] = previous

    async def test_preview_toggle_preserves_file_navigation(self) -> None:
        previous = os.environ.get("MDIR_NATIVE_PREVIEW")
        os.environ["MDIR_NATIVE_PREVIEW"] = "0"
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                image = root / "preview.png"
                image.write_bytes(b"\x89PNG\r\n\x1a\n")

                app = MDirApp()
                app.left_start = root
                app.right_start = root
                app._save_paths = lambda: None

                async with app.run_test(size=(120, 35)) as pilot:
                    for _ in range(100):
                        if app.left.initial_listing_complete:
                            break
                        await pilot.pause(0.02)

                    app.left.table.move_cursor(
                        row=app.left.row_by_path[image],
                        column=0,
                    )
                    app.set_active("left")
                    app.action_toggle_preview()
                    await pilot.pause(0.05)

                    self.assertTrue(app.preview_enabled)
                    self.assertTrue(app.preview_mode)
                    self.assertTrue(app.left.table.has_focus)
                    self.assertTrue(app.right.disabled)

                    await pilot.pause(0.25)
                    app.action_toggle_preview()
                    await pilot.pause(0.05)
                    self.assertFalse(app.preview_enabled)
                    self.assertFalse(app.preview_mode)
                    self.assertFalse(app.right.disabled)
                    app.exit()
        finally:
            if previous is None:
                os.environ.pop("MDIR_NATIVE_PREVIEW", None)
            else:
                os.environ["MDIR_NATIVE_PREVIEW"] = previous

    def test_safe_text_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            text = root / "note.md"
            image = root / "photo.jpg"
            text.write_text("# MDIR", encoding="utf-8")
            image.write_bytes(b"\xff\xd8\xff\xe0binary")

            self.assertTrue(
                inspect_safe_text_file(
                    text,
                    max_bytes=DEFAULT_VIEW_LIMIT,
                ).allowed
            )
            self.assertEqual(
                inspect_safe_text_file(
                    image,
                    max_bytes=DEFAULT_VIEW_LIMIT,
                ).reason,
                "unsupported_type",
            )

    def test_native_preview_geometry(self) -> None:
        terminal = WindowRectangle(100, 50, 2_100, 1_250)
        pane = PaneLayout(
            x=80,
            y=3,
            width=70,
            height=38,
            columns=150,
            rows=45,
        )
        rectangle = calculate_pane_rectangle(terminal, pane)
        self.assertGreater(rectangle.width, 800)
        self.assertGreater(rectangle.height, 700)

    def test_shortcut_configuration(self) -> None:
        values = [
            {"label": "Docs", "type": "folder", "target": "{home}\\Documents"},
            {"label": "Site", "type": "web", "target": "https://example.com"},
            {"label": "Invalid", "type": "unknown", "target": "ignored"},
        ]
        parsed = parse_shortcuts(values)
        self.assertEqual([item.label for item in parsed], ["Docs", "Site"])

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "shortcuts.json"
            ensure_shortcut_config(config_path)
            self.assertEqual(load_shortcuts(config_path), list(DEFAULT_SHORTCUTS))

            config_path.write_text(json.dumps(values), encoding="utf-8")
            self.assertEqual(
                [item.label for item in load_shortcuts(config_path)],
                ["Docs", "Site"],
            )
            save_shortcuts(parsed, config_path)
            self.assertEqual(load_shortcuts(config_path), parsed)

        expanded = expand_shortcut_text(
            "{project}|{current}|{left}|{right}",
            current=Path("C:/Current"),
            left=Path("C:/Left"),
            right=Path("D:/Right"),
            project=Path("S:/MDIR"),
        )
        self.assertIn(str(Path("S:/MDIR")), expanded)
        self.assertIn(str(Path("C:/Current")), expanded)


if __name__ == "__main__":
    unittest.main()
