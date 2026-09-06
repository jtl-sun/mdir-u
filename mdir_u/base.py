from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Mapping, Optional

from textual import work

from . import core as legacy
from .ime import enable_windows_korean_width_compatibility
from .shell import AIShellApp
from .ui.dialogs import (
    CompactConfirmScreen,
    CompactCopyScreen,
    CompactDriveScreen,
    CopyRequest,
    FileOperationProgressScreen,
)
from .file_operations import (
    PERMANENT_DELETE_THRESHOLD_BYTES,
    FileOperation,
    FileOperationResult,
    destination_conflicts,
    run_file_operation,
)
from .advanced import (
    FileIndex,
    FileMacro,
    MacroAction,
    MacroStore,
    OperationJournal,
    Workspace,
    WorkspaceStore,
    advanced_data_dir,
    compare_directories,
    find_exact_duplicates,
    find_similar_images,
    parse_safe_file_request,
    safe_sync_directories,
)
from .ui.advanced import AdvancedResult, AdvancedResultsScreen
from .ui.batch_rename import (
    BatchRenameScreen,
    RenamePair,
    apply_rename_pairs,
)
from .ui.prompt import CompactPromptScreen
from .ui.viewer import CompactViewerScreen
from .ui.archive import (
    ArchiveResult,
    CreateZipRequest,
    CreateZipScreen,
    ExtractZipRequest,
    ExtractZipScreen,
    create_zip_archive,
    extract_zip_archive,
    next_available_zip_path,
)


KOREAN_WIDTH_COMPATIBILITY = enable_windows_korean_width_compatibility()


@dataclass(frozen=True)
class QueuedFileOperation:
    operation: FileOperation
    items: tuple[Path, ...]
    destination: Path | None
    source_side: str
    new_name: str | None = None
    overwrite: bool = False


def move_confirmation_message(
    items: list[Path],
    destination: Path,
    metadata_by_path: Mapping[Path, object] | None = None,
) -> str:
    """Build a compact Move summary without listing selected filenames.

    Cached pane metadata is preferred so selecting thousands of files does not
    trigger thousands of additional filesystem calls just to open the dialog.
    Folder contents are intentionally not scanned here; the displayed capacity
    is the total of the selected files, matching the pane's capacity summary.
    """
    file_count = 0
    folder_count = 0
    total_size = 0
    metadata = metadata_by_path or {}

    for path in items:
        entry = metadata.get(path)
        if entry is not None:
            is_directory = bool(getattr(entry, "is_directory", False))
            size = int(getattr(entry, "size", 0))
        else:
            try:
                is_directory = path.is_dir()
                size = 0 if is_directory else int(path.stat().st_size)
            except OSError:
                is_directory = False
                size = 0

        if is_directory:
            folder_count += 1
        else:
            file_count += 1
            total_size += size

    return (
        f"Selected: {file_count:,} file(s), {folder_count:,} folder(s)\n"
        f"Total file size: {legacy.human_size(total_size)}\n"
        f"Move to:\n{destination}"
    )


def overwrite_confirmation_message(
    operation: FileOperation,
    conflicts: list[Path],
) -> str:
    """Build a small warning without expanding a large selection list."""
    count = len(conflicts)
    noun = "item" if count == 1 else "items"
    verb = "exists" if count == 1 else "exist"
    pronoun = "it" if count == 1 else "them"
    preview = "\n".join(path.name for path in conflicts[:3])
    remainder = count - min(count, 3)
    if remainder:
        preview += f"\n... and {remainder:,} more"
    return (
        f"{count:,} same-name {noun} already {verb}.\n"
        f"{operation.title()} will overwrite {pronoun}. Continue?\n"
        f"{preview}"
    )


def delete_confirmation_message(
    items: list[Path],
    metadata_by_path: Mapping[Path, object] | None = None,
) -> str:
    """Summarize which selected items are trashed or permanently deleted."""
    file_count = 0
    folder_count = 0
    total_size = 0
    permanent_count = 0
    metadata = metadata_by_path or {}

    for path in items:
        entry = metadata.get(path)
        if entry is not None:
            is_directory = bool(getattr(entry, "is_directory", False))
            size = int(getattr(entry, "size", 0))
        else:
            try:
                is_directory = path.is_dir() and not path.is_symlink()
                size = 0 if is_directory else int(path.stat().st_size)
            except OSError:
                is_directory = False
                size = 0

        if is_directory:
            folder_count += 1
            continue
        file_count += 1
        total_size += size
        if size >= PERMANENT_DELETE_THRESHOLD_BYTES:
            permanent_count += 1

    recycled_count = len(items) - permanent_count
    return (
        f"Selected: {file_count:,} file(s), {folder_count:,} folder(s)\n"
        f"Total file size: {legacy.human_size(total_size)}\n"
        f"Trash: {recycled_count:,} item(s)\n"
        f"Permanent delete (10 GB or larger): {permanent_count:,} file(s)"
    )

def windows_volume_label(drive: str) -> str:
    """Return a Windows volume label without querying drive capacity."""
    if os.name != "nt":
        return ""

    try:
        import ctypes

        label_buffer = ctypes.create_unicode_buffer(261)
        success = ctypes.windll.kernel32.GetVolumeInformationW(
            f"{drive.rstrip(chr(92))}\\",
            label_buffer,
            len(label_buffer),
            None,
            None,
            None,
            None,
            0,
        )
        if success:
            return label_buffer.value.strip()
    except Exception:
        pass
    return ""


class BaseApp(AIShellApp):
    """Application layer that selects the current dialogs explicitly."""

    PROMPT_SCREEN = CompactPromptScreen
    CONFIRM_SCREEN = CompactConfirmScreen
    VIEWER_SCREEN = CompactViewerScreen
    TITLE = "MDIR-U"
    SUB_TITLE = "Ubuntu and Universal File Manager / Codex AI"

    def __init__(self) -> None:
        self._archive_busy = False
        self._file_operation_busy = False
        self._file_operation_cancel: Event | None = None
        self._file_operation_pause: Event | None = None
        self._file_operation_screen: FileOperationProgressScreen | None = None
        self._file_operation_queue: deque[QueuedFileOperation] = deque()
        data_dir = advanced_data_dir("mDIR-U")
        self._operation_journal = OperationJournal(data_dir / "operations.json")
        self._workspace_store = WorkspaceStore(data_dir / "workspaces.json")
        self._macro_store = MacroStore(data_dir / "macros.json")
        self._macro_recording_name: str | None = None
        self._macro_recording_actions: list[MacroAction] = []
        self._file_index_path = data_dir / "mindex.sqlite3"
        super().__init__()

    def action_rename(self) -> None:
        """Use the batch tool automatically when more than one item is selected."""
        if len(self.active.selected_items()) > 1:
            self.action_batch_rename()
            return
        super().action_rename()

    def action_batch_rename(self) -> None:
        items = self.active.selected_items()
        if not items:
            self.set_status("Select one or more items first.")
            return

        def rename_requested(pairs: Optional[list[RenamePair]]) -> None:
            if pairs is None:
                self.set_status("Batch rename cancelled.")
                return
            changed = [pair for pair in pairs if pair.source != pair.target]
            if not changed:
                self.set_status("No names need to be changed.")
                return
            try:
                apply_rename_pairs(changed)
            except Exception as exc:
                self.set_status(f"Batch rename failed and was rolled back: {exc}")
                return

            self.active.marked.clear()
            self.active.refresh_listing(
                keep_name=changed[0].target.name if len(changed) == 1 else None
            )
            self.passive.refresh_listing()
            self.set_status(f"Renamed {len(changed)} item(s).")
            self.record_operation(
                "rename", ((pair.source, pair.target) for pair in changed)
            )

        self.push_screen(BatchRenameScreen(items), rename_requested)

    def action_compress_zip(self) -> None:
        """Create a ZIP from the active pane in the opposite pane by default."""
        source_side = self.active_side
        source_pane = self.active
        destination_pane = self.passive
        items = source_pane.selected_items()
        if not items:
            self.set_status("Select one or more items first.")
            return

        if len(items) == 1:
            default_name = f"{items[0].stem}.zip"
        else:
            default_name = f"{source_pane.current_path.name or 'archive'}.zip"

        # Dual-pane file managers conventionally put generated output in the
        # opposite pane. Fall back to the source directory only if that pane's
        # current path has disappeared or is no longer a directory (for
        # example, after a removable drive was disconnected).
        destination_directory = destination_pane.current_path
        try:
            if not destination_directory.is_dir():
                destination_directory = source_pane.current_path
        except OSError:
            destination_directory = source_pane.current_path
        destination = next_available_zip_path(
            destination_directory / default_name
        )

        def create_requested(request: Optional[CreateZipRequest]) -> None:
            if request is None:
                self.set_status("ZIP creation cancelled.")
                return
            if self._archive_busy:
                self.set_status("Another ZIP operation is already running.")
                return
            self._archive_busy = True
            self.set_status(f"Creating ZIP: {request.destination.name} ...")
            self._create_zip_in_background(
                tuple(items),
                request,
                source_side,
            )

        self.push_screen(CreateZipScreen(items, destination), create_requested)

    @work(thread=True, group="archive-operation", exit_on_error=False)
    def _create_zip_in_background(
        self,
        items: tuple[Path, ...],
        request: CreateZipRequest,
        source_side: str,
    ) -> None:
        """Compress without blocking navigation or screen redraws."""
        try:
            result = create_zip_archive(items, request)
            error = None
        except Exception as exc:
            result = None
            error = str(exc)
        self.call_from_thread(
            self._finish_create_zip,
            request,
            source_side,
            result,
            error,
        )

    def _finish_create_zip(
        self,
        request: CreateZipRequest,
        source_side: str,
        result: ArchiveResult | None,
        error: str | None,
    ) -> None:
        self._archive_busy = False
        if error or result is None:
            message = error or "Unknown ZIP creation error"
            self.set_status(f"ZIP creation failed: {message}")
            self.notify(message, title="Create ZIP failed")
            return

        final_path = request.destination
        if final_path.suffix.lower() != ".zip":
            final_path = final_path.with_suffix(".zip")
        source = self.left if source_side == "left" else self.right
        destination_pane = self.right if source_side == "left" else self.left
        final_parent = final_path.parent.resolve(strict=False)
        source.marked.clear()
        source.refresh_listing(
            keep_name=final_path.name
            if final_parent == source.current_path.resolve(strict=False)
            else None
        )
        destination_pane.refresh_listing(
            keep_name=final_path.name
            if final_parent == destination_pane.current_path.resolve(strict=False)
            else None
        )
        self.set_status(
            f"Created {final_path.name}: {result.files} file(s), "
            f"{result.directories} folder(s)."
        )

    def action_extract_zip(self) -> None:
        """Extract the active pane's ZIP into the opposite pane by default."""
        source_side = self.active_side
        source_pane = self.active
        destination_pane = self.passive
        items = source_pane.selected_items()
        if len(items) != 1:
            self.set_status("Select exactly one ZIP file to extract.")
            return
        archive_path = items[0]
        if not archive_path.is_file() or archive_path.suffix.lower() != ".zip":
            self.set_status("Select a .zip file to extract.")
            return

        # Match the dual-pane copy and compression workflow: left extracts to
        # right, and right extracts to left.  Keep the source side fixed while
        # the dialog is open so a later focus change cannot reverse the panes.
        # A disconnected or otherwise unavailable passive path falls back to
        # the directory containing the archive.
        destination = destination_pane.current_path
        try:
            if not destination.is_dir():
                destination = archive_path.parent
        except OSError:
            destination = archive_path.parent

        def extract_requested(request: Optional[ExtractZipRequest]) -> None:
            if request is None:
                self.set_status("ZIP extraction cancelled.")
                return
            if self._archive_busy:
                self.set_status("Another ZIP operation is already running.")
                return
            self._archive_busy = True
            self.set_status(f"Extracting ZIP: {archive_path.name} ...")
            self._extract_zip_in_background(
                archive_path,
                request,
                source_side,
            )

        self.push_screen(
            ExtractZipScreen(archive_path, destination),
            extract_requested,
        )

    @work(thread=True, group="archive-operation", exit_on_error=False)
    def _extract_zip_in_background(
        self,
        archive_path: Path,
        request: ExtractZipRequest,
        source_side: str,
    ) -> None:
        """Extract without blocking keyboard and mouse input."""
        try:
            result = extract_zip_archive(archive_path, request)
            error = None
        except Exception as exc:
            result = None
            error = str(exc)
        self.call_from_thread(
            self._finish_extract_zip,
            archive_path,
            request,
            source_side,
            result,
            error,
        )

    def _finish_extract_zip(
        self,
        archive_path: Path,
        request: ExtractZipRequest,
        source_side: str,
        result: ArchiveResult | None,
        error: str | None,
    ) -> None:
        self._archive_busy = False
        if error or result is None:
            message = error or "Unknown ZIP extraction error"
            self.set_status(f"ZIP extraction failed: {message}")
            self.notify(message, title="Extract ZIP failed")
            return

        source = self.left if source_side == "left" else self.right
        destination_pane = self.right if source_side == "left" else self.left
        source.marked.clear()
        source.refresh_listing(keep_name=archive_path.name)
        destination_path = request.destination.resolve(strict=False)
        destination_current = destination_pane.current_path.resolve(strict=False)
        destination_pane.refresh_listing(
            keep_name=request.destination.name
            if request.destination.parent.resolve(strict=False)
            == destination_current
            and destination_path != destination_current
            else None
        )
        self.set_status(
            f"Extracted {result.files} file(s) and "
            f"{result.directories} folder(s) to {request.destination}"
        )

    def action_copy(self) -> None:
        """Copy selected items, with Save As support for a single item."""
        items = self.active.selected_items()
        if not items:
            self.set_status("Nothing selected.")
            return

        destination = self.passive.current_path
        source_side = self.active_side

        def copy_requested(request: Optional[CopyRequest]) -> None:
            if request is None:
                self.set_status("Copy cancelled.")
                return

            selected = tuple(items)
            conflicts = destination_conflicts(
                selected,
                destination,
                new_name=request.new_name,
            )

            def start_copy(overwrite: bool = False) -> None:
                self._start_file_operation(
                    "copy",
                    selected,
                    destination,
                    source_side,
                    new_name=request.new_name,
                    overwrite=overwrite,
                )

            if not conflicts:
                start_copy()
                return

            def overwrite_confirmed(ok: bool) -> None:
                if not ok:
                    self.set_status("Copy cancelled; existing items kept.")
                    return
                start_copy(overwrite=True)

            self.push_screen(
                self.CONFIRM_SCREEN(
                    overwrite_confirmation_message("copy", conflicts),
                    title="Overwrite warning",
                    compact=True,
                ),
                overwrite_confirmed,
            )

        self.push_screen(
            CompactCopyScreen(items, destination),
            copy_requested,
        )

    def action_move(self) -> None:
        items = self.active.selected_items()
        if not items:
            self.set_status("Nothing selected.")
            return
        destination = self.passive.current_path
        source_side = self.active_side
        message = move_confirmation_message(
            items,
            destination,
            getattr(self.active, "metadata_by_path", None),
        )

        def confirmed(ok: bool) -> None:
            if not ok:
                self.set_status("Move cancelled.")
                return
            selected = tuple(items)
            conflicts = destination_conflicts(selected, destination)
            if not conflicts:
                self._start_file_operation(
                    "move", selected, destination, source_side
                )
                return

            def overwrite_confirmed(overwrite_ok: bool) -> None:
                if not overwrite_ok:
                    self.set_status("Move cancelled; existing items kept.")
                    return
                self._start_file_operation(
                    "move",
                    selected,
                    destination,
                    source_side,
                    overwrite=True,
                )

            self.push_screen(
                self.CONFIRM_SCREEN(
                    overwrite_confirmation_message("move", conflicts),
                    title="Overwrite warning",
                    compact=True,
                ),
                overwrite_confirmed,
            )

        self.push_screen(
            self.CONFIRM_SCREEN(message, title="Move"),
            confirmed,
        )

    def action_delete(self) -> None:
        items = self.active.selected_items()
        if not items:
            self.set_status("Nothing selected.")
            return
        source_side = self.active_side
        message = delete_confirmation_message(
            items,
            getattr(self.active, "metadata_by_path", None),
        )

        def confirmed(ok: bool) -> None:
            if not ok:
                self.set_status("Delete cancelled.")
                return
            self._start_file_operation(
                "delete", tuple(items), None, source_side
            )

        self.push_screen(
            self.CONFIRM_SCREEN(message, title="Delete"),
            confirmed,
        )

    def _start_file_operation(
        self,
        operation: FileOperation,
        items: tuple[Path, ...],
        destination: Path | None,
        source_side: str,
        *,
        new_name: str | None = None,
        overwrite: bool = False,
    ) -> None:
        """Open progress UI and start the filesystem work off the UI thread."""
        if self._macro_recording_name and operation in {"copy", "move"}:
            self._macro_recording_actions.append(
                MacroAction(
                    operation,  # type: ignore[arg-type]
                    tuple(str(path) for path in items),
                    str(destination or ""),
                    source_side,  # type: ignore[arg-type]
                    new_name,
                )
            )
        if self._file_operation_busy:
            self._file_operation_queue.append(
                QueuedFileOperation(
                    operation,
                    items,
                    destination,
                    source_side,
                    new_name,
                    overwrite,
                )
            )
            self.set_status(
                f"Queued {operation}: {len(items):,} item(s) "
                f"(queue {len(self._file_operation_queue)})."
            )
            return
        self._file_operation_busy = True
        cancel_event = Event()
        pause_event = Event()
        cancel_event.mdir_pause_event = pause_event  # type: ignore[attr-defined]
        screen = FileOperationProgressScreen(
            operation, len(items), cancel_event, pause_event
        )
        self._file_operation_cancel = cancel_event
        self._file_operation_pause = pause_event
        self._file_operation_screen = screen
        self.push_screen(screen)
        self.set_status(f"{operation.title()} started: {len(items):,} item(s).")
        self._run_file_operation_in_background(
            operation,
            items,
            destination,
            source_side,
            new_name,
            overwrite,
            cancel_event,
            pause_event,
        )

    @work(thread=True, group="file-operation", exit_on_error=False)
    def _run_file_operation_in_background(
        self,
        operation: FileOperation,
        items: tuple[Path, ...],
        destination: Path | None,
        source_side: str,
        new_name: str | None,
        overwrite: bool,
        cancel_event: Event,
        pause_event: Event,
    ) -> None:
        """Run large file batches without blocking the Textual event loop."""
        last_update = 0.0

        def report(completed: int, total: int, name: str) -> None:
            nonlocal last_update
            now = time.monotonic()
            if completed == total or completed % 25 == 0 or now-last_update >= 0.08:
                last_update = now
                self.call_from_thread(
                    self._update_file_operation_progress,
                    completed,
                    name,
                )

        try:
            result = run_file_operation(
                operation,
                items,
                destination,
                new_name=new_name,
                overwrite=overwrite,
                cancel_event=cancel_event,
                progress=report,
            )
            fatal_error = None
        except Exception as exc:
            result = None
            fatal_error = str(exc)
        self.call_from_thread(
            self._finish_file_operation,
            source_side,
            destination,
            result,
            fatal_error,
            overwrite,
        )

    def _update_file_operation_progress(
        self, completed: int, item_name: str
    ) -> None:
        screen = self._file_operation_screen
        if screen is not None and screen.is_mounted:
            screen.update_progress(completed, item_name)

    def _finish_file_operation(
        self,
        source_side: str,
        destination: Path | None,
        result: FileOperationResult | None,
        fatal_error: str | None,
        overwrite: bool = False,
    ) -> None:
        screen = self._file_operation_screen
        self._file_operation_screen = None
        self._file_operation_cancel = None
        self._file_operation_pause = None
        self._file_operation_busy = False
        if screen is not None and screen.is_mounted:
            screen.dismiss(None)

        source = self.left if source_side == "left" else self.right
        target = self.right if source_side == "left" else self.left
        source.marked.clear()
        source.refresh_listing()
        if destination is not None:
            keep_name = None
            if result is not None and len(result.completed_names) == 1:
                keep_name = result.completed_names[0]
            target.refresh_listing(keep_name=keep_name)
        elif target.current_path == source.current_path:
            target.refresh_listing()

        if fatal_error or result is None:
            message = fatal_error or "Unknown file operation error"
            self.set_status(f"File operation failed: {message}")
            self.notify(message, title="File operation failed")
            self._start_next_queued_operation()
            return

        if result.completed_pairs:
            self.record_operation(
                result.operation,
                result.completed_pairs,
                undoable=not overwrite,
                note=(
                    "An existing target was overwritten, so automatic undo is disabled."
                    if overwrite
                    else ""
                ),
            )
        elif result.operation == "delete" and result.completed:
            self._operation_journal.record(
                "delete",
                (),
                undoable=False,
                note="Deleted items are managed by the operating-system Trash/Recycle Bin.",
            )

        summary = (
            f"{result.operation.title()}: {result.completed:,} completed"
        )
        if result.operation == "delete":
            summary += (
                f" ({result.recycled:,} trashed, "
                f"{result.permanently_deleted:,} permanently deleted)"
            )
        if result.skipped:
            summary += f", {result.skipped:,} skipped"
        if result.errors:
            summary += f", {len(result.errors):,} error(s)"
        if result.cancelled:
            summary += " (cancelled)"
        self.set_status(summary)
        if result.errors:
            self.notify(
                "\n".join(result.errors[:5]),
                title=f"{result.operation.title()} errors",
            )
        self._start_next_queued_operation()

    def _start_next_queued_operation(self) -> None:
        if self._file_operation_busy or not self._file_operation_queue:
            return
        queued = self._file_operation_queue.popleft()
        self.call_later(
            self._start_file_operation,
            queued.operation,
            queued.items,
            queued.destination,
            queued.source_side,
            new_name=queued.new_name,
            overwrite=queued.overwrite,
        )

    def record_operation(
        self,
        operation: str,
        pairs: object,
        *,
        undoable: bool = True,
        note: str = "",
    ) -> None:
        self._operation_journal.record(
            operation, pairs, undoable=undoable, note=note  # type: ignore[arg-type]
        )

    def action_undo_last(self) -> None:
        record = self._operation_journal.latest_undoable()
        if record is None:
            self.set_status("Undo Center: no safe operation is available.")
            return

        def confirmed(ok: bool) -> None:
            if not ok:
                self.set_status("Undo cancelled.")
                return
            errors = self._operation_journal.undo(record)
            self.left.refresh_listing()
            self.right.refresh_listing()
            if errors:
                self.set_status(f"Undo stopped safely: {errors[0]}")
                self.notify("\n".join(errors[:5]), title="Undo Center")
            else:
                self.set_status(f"Undone: {self._operation_journal.describe(record)}")

        self.push_screen(
            self.CONFIRM_SCREEN(
                f"Undo this operation?\n\n{self._operation_journal.describe(record)}",
                title="Undo Center",
            ),
            confirmed,
        )

    def action_save_workspace(self) -> None:
        def got_name(name: Optional[str]) -> None:
            name = (name or "").strip()
            if not name:
                self.set_status("Workspace save cancelled.")
                return
            self._workspace_store.save(
                Workspace(
                    name,
                    str(self.left.current_path),
                    str(self.right.current_path),
                    self.active_side,  # type: ignore[arg-type]
                    bool(self.show_hidden_system),
                )
            )
            self.set_status(f"Workspace saved: {name}")

        self.push_screen(self.PROMPT_SCREEN("Workspace name:", ""), got_name)

    def action_load_workspace(self) -> None:
        names = sorted(self._workspace_store.all(), key=str.casefold)
        if not names:
            self.set_status("No saved workspaces. Use Ctrl+Shift+S to save one.")
            return

        def got_name(name: Optional[str]) -> None:
            workspace = self._workspace_store.get((name or "").strip())
            if workspace is None:
                self.set_status("Workspace not found.")
                return
            left, right = Path(workspace.left), Path(workspace.right)
            if not left.is_dir() or not right.is_dir():
                self.set_status("Workspace contains an unavailable folder.")
                return
            self.left.current_path = left
            self.right.current_path = right
            self.show_hidden_system = workspace.show_hidden
            self.left.show_hidden_system = workspace.show_hidden
            self.right.show_hidden_system = workspace.show_hidden
            self.left.refresh_listing()
            self.right.refresh_listing()
            self.set_active(workspace.active)
            self.update_hidden_buttons()
            self.set_status(f"Workspace loaded: {workspace.name}")

        self.push_screen(
            self.PROMPT_SCREEN(
                "Workspace name (" + ", ".join(names[:8]) + "):", names[0]
            ),
            got_name,
        )

    def _show_advanced_results(
        self,
        title: str,
        summary: str,
        results: list[AdvancedResult],
        source_side: str,
    ) -> None:
        def selected(path: Path | None) -> None:
            if path is not None:
                reveal = getattr(self, "_reveal_search_result", None)
                if callable(reveal):
                    reveal(path, source_side)
            else:
                self.set_active(source_side)

        self.push_screen(AdvancedResultsScreen(title, summary, results), selected)

    def action_mindex(self) -> None:
        """Search a persistent filename index; prefix ! to rebuild it first."""
        root, source_side = self.active.current_path, self.active_side

        def got_query(value: Optional[str]) -> None:
            query = (value or "").strip()
            if not query:
                self.set_status("mIndex search cancelled.")
                return
            rebuild = query.startswith("!")
            if rebuild:
                query = query[1:].strip()
            if not query:
                self.set_status("Enter a filename search term after !.")
                return
            self.set_status(f"mIndex: preparing {root} ...")
            self._run_mindex(root, query, rebuild, source_side)

        self.push_screen(
            self.PROMPT_SCREEN("mIndex search (!term rebuilds index):", ""), got_query
        )

    @work(thread=True, exclusive=True, group="mdir-mindex", exit_on_error=False)
    def _run_mindex(
        self, root: Path, query: str, rebuild: bool, source_side: str
    ) -> None:
        try:
            index = FileIndex(self._file_index_path)
            indexed = 0
            if rebuild or not index.has_root(root):
                indexed = index.rebuild(
                    root,
                    progress=lambda count, path: self.call_from_thread(
                        self.set_status,
                        f"mIndex: indexed {count:,} entries [{path}]",
                    ),
                )
            hits = index.search(root, query)
            results = [
                AdvancedResult(
                    "mIndex",
                    hit.path.name,
                    str(hit.path.parent),
                    "DIR" if hit.is_directory else legacy.human_size(hit.size),
                    hit.path,
                )
                for hit in hits
            ]
            extra = f", rebuilt {indexed:,}" if indexed else ""
            self.call_from_thread(
                self._show_advanced_results,
                "mIndex — indexed filename search",
                f"{len(results):,} result(s) for '{query}'{extra}",
                results,
                source_side,
            )
        except Exception as exc:
            self.call_from_thread(self.set_status, f"mIndex failed: {exc}")

    def action_find_duplicates(self) -> None:
        selected = self.active.selected_path()
        root = selected if selected and selected.is_dir() else self.active.current_path
        source_side = self.active_side

        def confirmed(ok: bool) -> None:
            if not ok:
                return
            self.set_status(f"Duplicate search: scanning {root} ...")
            self._run_duplicate_search(root, source_side)

        self.push_screen(
            self.CONFIRM_SCREEN(
                f"Find exact duplicate files below?\n\n{root}\n\n"
                "This only reads files and never deletes them.",
                title="Duplicate finder",
            ),
            confirmed,
        )

    @work(thread=True, exclusive=True, group="mdir-duplicates", exit_on_error=False)
    def _run_duplicate_search(self, root: Path, source_side: str) -> None:
        try:
            groups = find_exact_duplicates(
                root,
                progress=lambda count, path: self.call_from_thread(
                    self.set_status,
                    f"Duplicate search: scanned {count:,} files [{path}]",
                ),
            )
            similar_groups = find_similar_images(root)
            rows = [
                AdvancedResult(
                    f"Group {group_number}",
                    path.name,
                    str(path.parent),
                    legacy.human_size(path.stat().st_size),
                    path,
                )
                for group_number, group in enumerate(groups, start=1)
                for path in group
            ]
            rows.extend(
                AdvancedResult(
                    f"Similar {group_number}",
                    path.name,
                    str(path.parent),
                    "visual dHash",
                    path,
                )
                for group_number, group in enumerate(similar_groups, start=1)
                for path in group
            )
            self.call_from_thread(
                self._show_advanced_results,
                "Exact duplicate files",
                f"{len(groups):,} exact and {len(similar_groups):,} similar group(s), "
                f"{len(rows):,} rows. No files were changed.",
                rows,
                source_side,
            )
        except Exception as exc:
            self.call_from_thread(self.set_status, f"Duplicate search failed: {exc}")

    def action_compare_folders(self) -> None:
        left, right, source_side = (
            self.active.current_path,
            self.passive.current_path,
            self.active_side,
        )
        self.set_status(f"Comparing folders: {left} ↔ {right} ...")
        self._run_folder_compare(left, right, source_side)

    @work(thread=True, exclusive=True, group="mdir-folder-compare", exit_on_error=False)
    def _run_folder_compare(
        self, left: Path, right: Path, source_side: str
    ) -> None:
        try:
            compared = compare_directories(left, right)
            rows = [
                AdvancedResult(
                    entry.status,
                    entry.relative.name,
                    str(entry.relative.parent),
                    "DIR" if entry.is_directory else "FILE",
                    (left if entry.status != "right-only" else right) / entry.relative,
                )
                for entry in compared
                if entry.status != "same"
            ]
            self.call_from_thread(
                self._show_advanced_results,
                "Safe folder comparison",
                f"{len(rows):,} difference(s). Comparison never changes files.",
                rows,
                source_side,
            )
        except Exception as exc:
            self.call_from_thread(self.set_status, f"Folder compare failed: {exc}")

    def action_safe_sync(self) -> None:
        source, destination = self.active.current_path, self.passive.current_path
        source_side = self.active_side
        try:
            compared = compare_directories(source, destination)
        except Exception as exc:
            self.set_status(f"Sync comparison failed: {exc}")
            return
        changes = [
            item
            for item in compared
            if item.status in {"left-only", "different"}
        ]
        if not changes:
            self.set_status("Safe sync: destination is already up to date.")
            return

        def confirmed(ok: bool) -> None:
            if not ok:
                self.set_status("Safe sync cancelled.")
                return
            self.set_status(f"Safe sync started: {len(changes):,} item(s).")
            self._run_safe_sync(source, destination, changes, source_side)

        self.push_screen(
            self.CONFIRM_SCREEN(
                f"Copy {len(changes):,} new/changed item(s)?\n\n"
                f"FROM: {source}\nTO: {destination}\n\n"
                "No destination files will be deleted.",
                title="Safe one-way sync",
            ),
            confirmed,
        )

    @work(thread=True, exclusive=True, group="mdir-safe-sync", exit_on_error=False)
    def _run_safe_sync(
        self, source: Path, destination: Path, changes: list[object], source_side: str
    ) -> None:
        pairs, errors = safe_sync_directories(
            source,
            destination,
            changes,  # type: ignore[arg-type]
            progress=lambda completed, total, name: self.call_from_thread(
                self.set_status, f"Safe sync: {completed:,}/{total:,} {name}"
            ),
        )
        self.call_from_thread(
            self._finish_safe_sync, pairs, errors, source_side
        )

    def _finish_safe_sync(
        self,
        pairs: list[tuple[Path, Path]],
        errors: list[str],
        source_side: str,
    ) -> None:
        if pairs:
            self.record_operation("copy", pairs, note="Safe folder sync")
        self.left.refresh_listing()
        self.right.refresh_listing()
        summary = f"Safe sync: {len(pairs):,} file(s) copied"
        if errors:
            summary += f", {len(errors):,} error(s)"
            self.notify("\n".join(errors[:5]), title="Safe sync errors")
        self.set_active(source_side)
        self.set_status(summary)

    def request_safe_ai_file_action(self, prompt: str) -> None:
        """Turn an explicit /file request into a visible, confirmed plan."""
        try:
            plan = parse_safe_file_request(
                prompt,
                selected=self.active.selected_items(),
                active_directory=self.active.current_path,
                passive_directory=self.passive.current_path,
            )
        except ValueError as exc:
            self.set_status(f"Safe AI file request: {exc}")
            self.notify(str(exc), title="Safe AI file request")
            return

        def confirmed(ok: bool) -> None:
            if not ok:
                self.set_status("Safe AI file plan cancelled; no files changed.")
                return
            if plan.operation in {"copy", "move", "delete"}:
                self._start_file_operation(
                    plan.operation,  # type: ignore[arg-type]
                    plan.items,
                    plan.destination,
                    self.active_side,
                    overwrite=False,
                )
            elif plan.operation == "rename":
                source = plan.items[0]
                target = source.with_name(plan.new_name or source.name)
                try:
                    if target.exists():
                        raise FileExistsError(f"'{target.name}' already exists")
                    source.rename(target)
                    self.record_operation("rename", ((source, target),))
                    self.left.refresh_listing()
                    self.right.refresh_listing()
                    self.set_status(f"Safe AI rename completed: {target.name}")
                except Exception as exc:
                    self.set_status(f"Safe AI rename failed: {exc}")
            elif plan.operation == "mkdir" and plan.destination is not None:
                try:
                    plan.destination.mkdir(exist_ok=False)
                    self.record_operation(
                        "mkdir", ((plan.destination, plan.destination),)
                    )
                    self.active.refresh_listing(keep_name=plan.destination.name)
                    self.set_status(f"Safe AI folder created: {plan.destination.name}")
                except Exception as exc:
                    self.set_status(f"Safe AI folder creation failed: {exc}")

        warning = (
            "\n\nDelete cannot be automatically restored by Undo Center."
            if plan.operation == "delete"
            else "\n\nUndo Center will record the completed operation."
        )
        self.push_screen(
            self.CONFIRM_SCREEN(
                "AI proposed this file plan:\n\n" + plan.describe() + warning,
                title="Approve safe AI file plan",
            ),
            confirmed,
        )

    def action_toggle_macro_recording(self) -> None:
        if self._macro_recording_name:
            name = self._macro_recording_name
            actions = tuple(self._macro_recording_actions)
            self._macro_recording_name = None
            self._macro_recording_actions = []
            if actions:
                self._macro_store.save(FileMacro(name, actions))
                self.set_status(f"Macro saved: {name} ({len(actions)} action(s))")
            else:
                self.set_status("Macro recording stopped; no Copy/Move action was recorded.")
            return

        def got_name(name: Optional[str]) -> None:
            name = (name or "").strip()
            if not name:
                self.set_status("Macro recording cancelled.")
                return
            self._macro_recording_name = name
            self._macro_recording_actions = []
            self.set_status(
                f"Recording macro '{name}'. Copy/Move actions will be recorded."
            )

        self.push_screen(self.PROMPT_SCREEN("New macro name:", ""), got_name)

    def action_play_macro(self) -> None:
        names = sorted(self._macro_store.all(), key=str.casefold)
        if not names:
            self.set_status("No macros saved. Use Ctrl+Shift+M to record one.")
            return

        def got_name(name: Optional[str]) -> None:
            macro = self._macro_store.get((name or "").strip())
            if macro is None:
                self.set_status("Macro not found.")
                return
            lines = [
                f"{index}. {action.operation.title()} {len(action.items)} item(s) "
                f"to {action.destination}"
                for index, action in enumerate(macro.actions, start=1)
            ]

            def confirmed(ok: bool) -> None:
                if not ok:
                    self.set_status("Macro cancelled; no action started.")
                    return
                valid = 0
                for action in macro.actions:
                    items = tuple(Path(path) for path in action.items if Path(path).exists())
                    destination = Path(action.destination)
                    if not items or not destination.is_dir():
                        continue
                    self._start_file_operation(
                        action.operation,
                        items,
                        destination,
                        action.source_side,
                        new_name=action.new_name,
                        overwrite=False,
                    )
                    valid += 1
                self.set_status(f"Macro queued: {macro.name} ({valid} valid action(s))")

            self.push_screen(
                self.CONFIRM_SCREEN(
                    f"Run macro '{macro.name}'?\n\n" + "\n".join(lines[:8]) +
                    "\n\nExisting targets are never overwritten automatically.",
                    title="Review macro",
                ),
                confirmed,
            )

        self.push_screen(
            self.PROMPT_SCREEN("Macro name (" + ", ".join(names[:8]) + "):", names[0]),
            got_name,
        )

    def _prompt_drive(self, pane: legacy.FilePane) -> None:
        """Select a useful Linux location or mounted filesystem."""
        from .platform_support import locations

        choices = [
            (f"{item.label}  {item.path}", str(item.path))
            for item in locations()
        ]
        current_path = str(pane.current_path)

        def location_selected(value: Optional[str]) -> None:
            if not value:
                self.set_status("Location selection cancelled.")
                return
            target = Path(value)
            try:
                if not target.is_dir():
                    raise NotADirectoryError(target)
                pane.current_path = target.resolve()
                pane.marked.clear()
                pane.refresh_listing()
                pane.update_summary()
                self._save_paths()
                pane.table.focus()
                self.set_status(f"Opened location: {target}")
            except OSError as exc:
                self.set_status(f"Could not open location: {exc}")

        self.push_screen(
            CompactDriveScreen(choices, current_path),
            location_selected,
        )
