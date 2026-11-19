"""Non-destructive duplicate review decisions and portable path manifest.

No file is deleted, relocated, replaced, or hard-linked by this module.
The only writes are the per-user review JSON and explicitly exported CSV.
"""
from __future__ import annotations

import csv
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Literal

ReviewStatus = Literal["review", "keep", "candidate"]
STATUSES = frozenset(("review", "keep", "candidate"))


@dataclass(frozen=True)
class ReviewDecision:
    status: ReviewStatus = "review"
    note: str = ""
    changed: bool = False


def _key(path: Path) -> str:
    """Preserve the original absolute path for future reference."""
    return str(path.absolute())


def _fingerprint(path: Path) -> tuple[int, int]:
    details = path.stat()
    if not path.is_file():
        raise ValueError(f"Not a regular file: {path}")
    return int(details.st_size), int(details.st_mtime_ns)


def _write_atomic(path: Path, content: str) -> None:
    """A failed save must never replace the previous review manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class DuplicateReviewStore:
    """Store *intentions*, not deletion decisions; reset changed files to review."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.records: dict[str, dict[str, object]] = {}
        if self.path.is_file():
            document = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                not isinstance(document, dict)
                or document.get("version") != 1
                or not isinstance(document.get("records"), dict)
            ):
                raise ValueError("Unsupported duplicate review manifest format")
            for key, record in document["records"].items():
                if isinstance(key, str) and isinstance(record, dict):
                    self.records[key] = record

    def get(self, path: Path) -> ReviewDecision:
        saved = self.records.get(_key(path))
        if not saved:
            return ReviewDecision()
        status = saved.get("status", "review")
        if not isinstance(status, str) or status not in STATUSES:
            status = "review"
        note = str(saved.get("note", ""))
        try:
            size, stamp = _fingerprint(path)
        except (OSError, ValueError):
            return ReviewDecision("review", note, changed=True)
        changed = saved.get("size") != size or saved.get("mtime_ns") != stamp
        return ReviewDecision("review" if changed else status, note, changed)

    def set(self, path: Path, status: ReviewStatus, note: str | None = None) -> ReviewDecision:
        if status not in STATUSES:
            raise ValueError("Unsupported duplicate review status")
        size, stamp = _fingerprint(path)
        existing = self.get(path)
        revised_note = existing.note if note is None else note[:1000]
        updated = dict(self.records)
        updated[_key(path)] = {
            "status": status,
            "note": revised_note,
            "size": size,
            "mtime_ns": stamp,
            "reviewed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        _write_atomic(
            self.path,
            json.dumps({"version": 1, "records": updated}, ensure_ascii=False, indent=2),
        )
        self.records = updated
        return ReviewDecision(status, revised_note)


def _csv_safe(value: str) -> str:
    """Prevent spreadsheet formula execution from untrusted filenames/notes."""
    if value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_duplicate_report(
    report_path: Path,
    rows: Iterable[tuple[str, Path, int]],
    store: DuplicateReviewStore,
) -> int:
    """Export all results, including KEEP copies and full original locations.

    This creates a reference CSV and never modifies the scanned files.
    """
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_name(report_path.name + "." + uuid.uuid4().hex + ".tmp")
    count = 0
    try:
        with temporary.open("w", newline="", encoding="utf-8-sig") as output:
            writer = csv.writer(output)
            writer.writerow(
                ("Group", "Status", "Review note", "File name", "Full path",
                 "File size (bytes)", "Changed since review")
            )
            for group, path, size in rows:
                decision = store.get(path)
                writer.writerow((
                    _csv_safe(group),
                    decision.status.upper(),
                    _csv_safe(decision.note),
                    _csv_safe(path.name),
                    _csv_safe(str(path.absolute())),
                    size,
                    "YES" if decision.changed else "NO",
                ))
                count += 1
        os.replace(temporary, report_path)
    finally:
        temporary.unlink(missing_ok=True)
    return count
