from __future__ import annotations

import json
import os
from pathlib import Path


DEFAULT_RECENT_FOLDER_LIMIT = 40


def _path_key(value: str) -> str:
    """Return a stable comparison key without touching the filesystem."""
    return os.path.normcase(os.path.normpath(value.strip()))


class RecentFolderStore:
    """Small persistent MRU list shared by the left and right panes."""

    def __init__(self, path: Path, limit: int = DEFAULT_RECENT_FOLDER_LIMIT) -> None:
        self.path = path
        self.limit = max(1, int(limit))

    def load(self) -> list[str]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return []
        if not isinstance(raw, list):
            return []
        result: list[str] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, str):
                continue
            value = item.strip()
            if not value:
                continue
            key = _path_key(value)
            if key in seen:
                continue
            seen.add(key)
            result.append(value)
            if len(result) >= self.limit:
                break
        return result

    def _save(self, values: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(values[: self.limit], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def record(self, path: Path | str) -> list[str]:
        value = str(path).strip()
        if not value:
            return self.load()
        key = _path_key(value)
        current = self.load()
        if current and _path_key(current[0]) == key:
            return current
        values = [item for item in current if _path_key(item) != key]
        values.insert(0, value)
        values = values[: self.limit]
        self._save(values)
        return values

    def remove(self, path: Path | str) -> list[str]:
        value = str(path).strip()
        key = _path_key(value)
        values = [item for item in self.load() if _path_key(item) != key]
        self._save(values)
        return values

    def clear(self) -> None:
        self._save([])
