from __future__ import annotations

import os
import time
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


def move_confirmation_message(
    items: list[Path],
    destination: Path,
    metadata_by_path: Mapping[Path, object] | None = None,
) -> str:
    """Build a compact Move summary from cached pane metadata."""
    file_count = folder_count = total_size = 0
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
                is_directory, size = False, 0
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
    """Build a compact warning without expanding a large selection list."""
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
    """Summarize Trash and permanent-delete counts without listing names."""
    file_count = folder_count = total_size = permanent_count = 0
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
                is_directory, size = False, 0
        if is_directory:
            folder_count += 1
        else:
            file_count += 1
            total_size += size
            permanent_count += int(size >= PERMANENT_DELETE_THRESHOLD_BYTES)
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
        self._file_operation_screen: FileOperationProgressScreen | None = None
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
            items, destination, getattr(self.active, "metadata_by_path", None)
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
            items, getattr(self.active, "metadata_by_path", None)
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
        if self._file_operation_busy:
            self.set_status("Another file operation is already running.")
            return
        self._file_operation_busy = True
        cancel_event = Event()
        screen = FileOperationProgressScreen(
            operation, len(items), cancel_event
        )
        self._file_operation_cancel = cancel_event
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
    ) -> None:
        screen = self._file_operation_screen
        self._file_operation_screen = None
        self._file_operation_cancel = None
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
            return

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
