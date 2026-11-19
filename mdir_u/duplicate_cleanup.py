"""Conservative single-file cleanup of already verified exact-duplicate groups.

Only the freedesktop Trash may receive a confirmed selected file.
Never permanently delete, process visually similar results, or remove the
last verified copy. All paths and content are verified again before recycle.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, Iterable

from .file_operations import send_to_recycle_bin
from .duplicate_review import DuplicateReviewStore

DuplicateRow = tuple[str, Path, int]


def _fingerprint_file(path: Path, root: Path) -> tuple[int, int, int, int]:
    """Reject symlinks, directories and paths outside the chosen search root."""
    if path.is_symlink():
        raise ValueError(f"Symbolic links cannot be recycled here: {path}")
    if not path.is_file():
        raise ValueError(f"File unavailable or no longer regular: {path}")
    if not path.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
        raise ValueError(f"File is outside the scanned folder: {path}")
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_dev, stat.st_ino


def _hash_unchanged(path: Path, root: Path) -> tuple[str, tuple[int, int, int, int]]:
    before = _fingerprint_file(path, root)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    if _fingerprint_file(path, root) != before:
        raise ValueError(f"File changed during verification: {path}")
    return digest.hexdigest(), before


def recycle_selected_exact_duplicate(
    root: Path,
    rows: Iterable[DuplicateRow],
    selected: DuplicateRow,
    store: DuplicateReviewStore,
    *,
    recycle: Callable[[Path], None] | None = None,
) -> Path:
    """Recycle one explicitly selected exact duplicate after re-verification.

    Caller must separately obtain user confirmation. For regular runtime use
    the freedesktop Trash is required; there is no permanent-delete fallback.
    A test can inject a simulated recycle callable.
    Returns the surviving matching file path on success.
    """
    group, path, scanned_size = selected
    items = list(rows)
    if selected not in items:
        raise ValueError("Selected file is not in the reviewed duplicate results.")
    if not group.startswith("Exact "):
        raise ValueError("Only byte-identical Exact groups support deletion.")
    if path == root or path == root.parent:
        raise ValueError("Cannot delete the search root.")
    decision = store.get(path)
    if decision.status == "keep" or decision.changed:
        raise ValueError("KEEP or changed files are protected. Review them first.")
    peers = [
        candidate
        for candidate_group, candidate, candidate_size in items
        if candidate_group == group and candidate != path
        and candidate_size == scanned_size
    ]
    if not peers:
        raise ValueError("No other listed copy remains in this Exact group.")
    selected_hash, selected_meta = _hash_unchanged(path, root)
    if selected_meta[0] != scanned_size:
        raise ValueError("Selected file size changed since the duplicate scan.")

    surviving: Path | None = None
    for other in peers:
        try:
            other_hash, other_meta = _hash_unchanged(other, root)
            if other_meta[0] == scanned_size and other_hash == selected_hash:
                surviving = other
                break
        except (OSError, ValueError):
            continue
    if surviving is None:
        raise ValueError(
            "No remaining byte-identical copy could be re-verified. "
            "Nothing was recycled."
        )
    if _fingerprint_file(path, root) != selected_meta:
        raise ValueError("Selected file changed after verification.")

    if recycle is None:
        recycle = send_to_recycle_bin
    recycle(path)
    return surviving


def plan_marked_exact_duplicates(
    rows: Iterable[DuplicateRow],
    marked: Iterable[tuple[str, Path]],
    store: DuplicateReviewStore,
) -> tuple[list[DuplicateRow], list[str]]:
    """Preflight a batch without selecting which original the user must keep.

    For every exact group at least one *unmarked* existing copy is required.
    If every file in a group is marked, exclude the entire group and ask the
    user to unmark one. This never silently picks a survivor for them.
    """
    listing = list(rows)
    selected = set(marked)
    grouped: dict[str, list[DuplicateRow]] = {}
    for row in listing:
        if row[0].startswith("Exact "):
            grouped.setdefault(row[0], []).append(row)

    safe: list[DuplicateRow] = []
    skipped: list[str] = []
    for group, members in grouped.items():
        picked = [row for row in members if (row[0], row[1]) in selected]
        if not picked:
            continue
        survivors = [
            row for row in members
            if (row[0], row[1]) not in selected and row[1].is_file()
        ]
        if not survivors:
            skipped.append(
                f"{group}: all remaining copies are marked or unavailable. "
                "Unmark at least one copy to keep."
            )
            continue
        for row in picked:
            decision = store.get(row[1])
            if decision.status == "keep" or decision.changed:
                skipped.append(f"{group}: KEEP/changed file skipped: {row[1]}")
            elif not row[1].is_file() or row[1].is_symlink():
                skipped.append(f"{group}: unavailable or linked file: {row[1]}")
            else:
                safe.append(row)

    for group, path in selected:
        if not group.startswith("Exact "):
            skipped.append(f"{group}: visually similar (not exact): {path}")
        elif group not in grouped or not any(
            row[1] == path for row in grouped[group]
        ):
            skipped.append(f"{group}: row no longer exists: {path}")

    return safe, skipped


def recycle_marked_exact_duplicates(
    root: Path,
    rows: Iterable[DuplicateRow],
    selected: Iterable[DuplicateRow],
    store: DuplicateReviewStore,
    *,
    recycle: Callable[[Path], None] | None = None,
    on_progress: Callable[[int, int, Path], None] | None = None,
    cancel_event=None,
) -> tuple[list[DuplicateRow], list[str]]:
    """Reverify and recycle batch entries sequentially; never delete all copies.

    A fresh copy of the in-memory rows is pruned only after each successful
    recycle. Every next file is independently rehashed against a surviving
    copy. Failures are reported without attempting permanent deletion.
    """
    remaining = list(rows)
    picked = list(selected)
    succeeded: list[DuplicateRow] = []
    failures: list[str] = []
    for index, row in enumerate(picked, start=1):
        if cancel_event is not None and cancel_event.is_set():
            failures.append(f"Stopped by user with {len(picked) - index + 1} unprocessed")
            break
        try:
            recycle_selected_exact_duplicate(
                root, remaining, row, store, recycle=recycle
            )
        except (OSError, ValueError) as exc:
            failures.append(f"{row[1]}: {exc}")
        else:
            remaining.remove(row)
            succeeded.append(row)
        if on_progress is not None:
            on_progress(index, len(picked), row[1])
    return succeeded, failures


def refreshed_duplicate_review(
    rows: Iterable[DuplicateRow],
    recycled: Iterable[DuplicateRow],
) -> tuple[list[DuplicateRow], int, int]:
    """Return current duplicate groups after confirmed recycle operations.

    Do not rescan or hash the drive: refresh only the already reviewed rows,
    discarding recycled/missing files and resolved one-copy groups. Preserve
    original order so the current page and remaining marks remain meaningful.
    A group with only its protected last copy is no longer a duplicate.
    """
    listing = list(rows)
    removed = {(group, path) for group, path, _ in recycled}
    available: list[DuplicateRow] = []
    counts: dict[str, int] = {}
    original_groups: set[str] = set()
    for group, path, size in listing:
        original_groups.add(group)
        if (group, path) in removed or not path.is_file():
            continue
        available.append((group, path, size))
        counts[group] = counts.get(group, 0) + 1
    visible = [row for row in available if counts[row[0]] >= 2]
    resolved_groups = len(original_groups - {
        row[0] for row in visible
    })
    # Recycled, missing, and last surviving copies no longer shown as matches.
    hidden_rows = len(listing) - len(visible)
    return visible, resolved_groups, hidden_rows
