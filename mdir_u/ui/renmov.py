"""Resolve a single F6 Rename/Move destination without altering files."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class RenameMovePlan:
    mode: str
    destination: Path
    new_name: str | None
    target: Path | None


def plan_rename_move(value: str, items: Sequence[Path], source_dir: Path) -> RenameMovePlan:
    """Bare filename renames one entry; a directory moves selected entries.

    A single entry can also be renamed *while moving* by providing a complete
    target filename in another existing directory. Multiple entries require
    an existing directory. No missing directories are implicitly created.
    """
    if not items:
        raise ValueError("Select one or more items.")
    raw = value.strip().strip('"')
    if not raw:
        raise ValueError("Enter a filename or existing destination folder.")
    source_dir = Path(source_dir).resolve(strict=False)
    candidate = Path(os.path.expandvars(raw)).expanduser()
    if not candidate.is_absolute():
        candidate = source_dir / candidate
    candidate = candidate.resolve(strict=False)
    selected = tuple(Path(item).resolve(strict=False) for item in items)

    if candidate.is_dir():
        destination = candidate
        new_name = None
        target = None
        mode = "move"
        if all(item.parent == destination for item in selected):
            mode = "noop"
    elif len(selected) != 1:
        raise ValueError("Select an existing destination folder for multiple items.")
    else:
        if candidate.name in ("", ".", "..") or not candidate.parent.is_dir():
            raise ValueError("The destination folder must already exist.")
        item = selected[0]
        destination = candidate.parent
        new_name = candidate.name if candidate.name != item.name else None
        target = candidate
        mode = "noop" if candidate == item else (
            "rename" if destination == item.parent else "move"
        )

    if mode == "move":
        for item in selected:
            # Moving a directory into itself or a child would corrupt layout.
            if item.is_dir() and (destination == item or item in destination.parents):
                raise ValueError("Cannot move a folder into itself or a child folder.")
    return RenameMovePlan(mode, destination, new_name, target)
