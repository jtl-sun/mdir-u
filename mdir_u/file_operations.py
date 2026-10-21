from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from time import sleep
from typing import Callable, Iterable, Literal

from .progress import OperationCancelled, ProgressTracker


FileOperation = Literal["copy", "move", "delete"]
ProgressCallback = Callable[[int, int, str], None]
PERMANENT_DELETE_THRESHOLD_BYTES = 10 * 1024**3


@dataclass
class FileOperationResult:
    """Summary returned after a copy, move, or delete batch."""

    operation: FileOperation
    total: int
    completed: int = 0
    skipped: int = 0
    cancelled: bool = False
    recycled: int = 0
    permanently_deleted: int = 0
    completed_names: list[str] = field(default_factory=list)
    completed_pairs: list[tuple[Path, Path]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _same_path(first: Path, second: Path) -> bool:
    """Compare paths without a filesystem round-trip for every selected item."""
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(
        os.path.abspath(second)
    )


def _path_exists(path: Path) -> bool:
    """Return True for normal entries and broken symbolic links."""
    return os.path.lexists(path)


def destination_conflicts(
    items: Iterable[Path],
    destination: Path,
    *,
    new_name: str | None = None,
) -> list[Path]:
    """Return existing top-level targets that would be overwritten."""
    paths = tuple(Path(item) for item in items)
    conflicts: list[Path] = []
    for source in paths:
        target_name = (
            new_name if len(paths) == 1 and new_name else source.name
        )
        target = Path(destination) / target_name
        if not _same_path(source, target) and _path_exists(target):
            conflicts.append(target)
    return conflicts


def _remove_existing_target(path: Path) -> None:
    """Remove one explicitly approved overwrite target on Linux."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def should_permanently_delete(*, is_directory: bool, size: int) -> bool:
    """Only individual files of 10 GiB or larger bypass the Trash."""
    return not is_directory and size >= PERMANENT_DELETE_THRESHOLD_BYTES


def send_to_recycle_bin(path: Path) -> None:
    """Move an item to the freedesktop Trash without unsafe fallback."""
    gio = shutil.which("gio")
    if gio is None:
        raise OSError("gio is unavailable; item was not deleted")
    completed = subprocess.run(
        [gio, "trash", "--", str(path.resolve(strict=False))],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise OSError(detail or "could not move item to Trash")


def _estimate_size(path: Path) -> int:
    """Best-effort byte estimate including nested files."""
    try:
        if not path.is_dir() or path.is_symlink():
            return max(0, path.stat().st_size)
        total = 0
        for root, dirs, files in os.walk(path, followlinks=False):
            for name in files:
                try:
                    total += max(0, (Path(root) / name).stat().st_size)
                except OSError:
                    pass
        return total
    except OSError:
        return 0


def _copy_with_progress(source: str, target: str, tracker: ProgressTracker | None) -> str:
    if tracker is None:
        return shutil.copy2(source, target)
    tracker.begin_item(str(source), _estimate_size(Path(source)))
    target_path = Path(target)
    # Never truncate an existing destination before an interruptible transfer.
    temporary = target_path.with_name(f".{target_path.name}.mdir-copy-{uuid.uuid4().hex}")
    try:
        with open(source, "rb") as src, temporary.open("wb") as dst:
            while True:
                tracker.checkpoint()
                block = src.read(1024 * 1024)
                if not block:
                    break
                dst.write(block)
                tracker.advance(len(block))
        shutil.copystat(source, temporary)
        tracker.checkpoint()
        os.replace(temporary, target_path)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _move_with_rollback(source: Path, target: Path, tracker: ProgressTracker | None) -> None:
    """Back up an overwritten destination until the move has succeeded."""
    backup = None
    if _path_exists(target):
        backup = target.with_name(f".{target.name}.mdir-backup-{uuid.uuid4().hex}")
        target.replace(backup)
    try:
        shutil.move(
            str(source), str(target),
            copy_function=lambda s, d: _copy_with_progress(s, d, tracker),
        )
    except Exception:
        try:
            if _path_exists(target):
                _remove_existing_target(target)
        finally:
            if backup is not None and _path_exists(backup):
                backup.replace(target)
        raise
    if backup is not None and _path_exists(backup):
        _remove_existing_target(backup)


def run_file_operation(
    operation: FileOperation,
    items: Iterable[Path],
    destination: Path | None = None,
    *,
    new_name: str | None = None,
    overwrite: bool = False,
    cancel_event: Event | None = None,
    pause_event: Event | None = None,
    progress: ProgressCallback | None = None,
    tracker: ProgressTracker | None = None,
) -> FileOperationResult:
    """Run a batch file operation without touching any UI objects.

    The caller is expected to run this function in a worker thread.  Progress
    is reported after each top-level item; UI callers should coalesce those
    notifications before repainting.
    """
    paths = tuple(Path(item) for item in items)
    if pause_event is None and cancel_event is not None:
        pause_event = getattr(cancel_event, "mdir_pause_event", None)
    result = FileOperationResult(operation=operation, total=len(paths))
    if tracker is not None:
        tracker.set_totals(items=len(paths), bytes_total=sum(_estimate_size(p) for p in paths))
    if operation in {"copy", "move"} and destination is None:
        raise ValueError(f"{operation} requires a destination")

    for index, source in enumerate(paths, start=1):
        while pause_event is not None and pause_event.is_set():
            if cancel_event is not None and cancel_event.is_set():
                break
            sleep(0.05)
        if cancel_event is not None and cancel_event.is_set():
            result.cancelled = True
            break

        display_name = source.name
        item_size = _estimate_size(source) if tracker is not None else 0
        item_start = tracker.snapshot().bytes_done if tracker is not None else 0
        if tracker is not None:
            try:
                tracker.begin_item(str(source), item_size if not source.is_dir() else 0)
            except OperationCancelled:
                result.cancelled = True
                break
        try:
            if operation == "delete":
                is_directory = source.is_dir() and not source.is_symlink()
                size = 0 if is_directory else int(source.stat().st_size)
                if should_permanently_delete(
                    is_directory=is_directory, size=size
                ):
                    source.unlink()
                    result.permanently_deleted += 1
                else:
                    send_to_recycle_bin(source)
                    result.recycled += 1
            else:
                assert destination is not None
                target_name = (
                    new_name
                    if len(paths) == 1 and new_name
                    else source.name
                )
                target = destination / target_name
                if _same_path(source, target):
                    result.skipped += 1
                    if tracker is not None:
                        tracker.complete_item(remaining_bytes=item_size)
                    if progress is not None:
                        progress(index, result.total, display_name)
                    continue
                target_exists = _path_exists(target)
                if target_exists and not overwrite:
                    result.skipped += 1
                    if tracker is not None:
                        tracker.complete_item(remaining_bytes=item_size)
                    if progress is not None:
                        progress(index, result.total, display_name)
                    continue
                if operation == "copy":
                    if source.is_dir():
                        if target_exists and (
                            not target.is_dir() or target.is_symlink()
                        ):
                            _remove_existing_target(target)
                        shutil.copytree(source, target, dirs_exist_ok=True, copy_function=lambda s, d: _copy_with_progress(s, d, tracker))
                    else:
                        if target_exists and target.is_dir():
                            _remove_existing_target(target)
                        _copy_with_progress(str(source), str(target), tracker)
                else:
                    _move_with_rollback(source, target, tracker)
                display_name = target_name
                result.completed_pairs.append((source, target))

            result.completed += 1
            result.completed_names.append(display_name)
        except OperationCancelled:
            result.cancelled = True
            break
        except Exception as exc:
            result.errors.append(f"{source.name}: {exc}")

        if tracker is not None:
            transferred = tracker.snapshot().bytes_done - item_start
            tracker.complete_item(remaining_bytes=max(0, item_size - transferred))
        if progress is not None:
            progress(index, result.total, display_name)

    if cancel_event is not None and cancel_event.is_set():
        result.cancelled = True
    if tracker is not None:
        tracker.finish("cancelled" if result.cancelled else "completed")
    return result
