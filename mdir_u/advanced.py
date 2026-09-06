from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Event
from typing import Callable, Iterable, Literal


def advanced_data_dir(product: str) -> Path:
    """Return a small per-user data directory without importing UI modules."""
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        path = root / product
    else:
        root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
        path = root / product.lower()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _atomic_json_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


@dataclass(frozen=True)
class Workspace:
    name: str
    left: str
    right: str
    active: Literal["left", "right"] = "left"
    show_hidden: bool = False
    saved_at: float = field(default_factory=time.time)


class WorkspaceStore:
    """Named two-pane workspaces stored in a human-readable JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def all(self) -> dict[str, Workspace]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return {name: Workspace(**data) for name, data in raw.items()}
        except (OSError, ValueError, TypeError):
            return {}

    def save(self, workspace: Workspace) -> None:
        workspaces = self.all()
        workspaces[workspace.name] = workspace
        _atomic_json_write(
            self.path, {name: asdict(item) for name, item in workspaces.items()}
        )

    def get(self, name: str) -> Workspace | None:
        return self.all().get(name)


@dataclass(frozen=True)
class MacroAction:
    operation: Literal["copy", "move"]
    items: tuple[str, ...]
    destination: str
    source_side: Literal["left", "right"]
    new_name: str | None = None


@dataclass(frozen=True)
class FileMacro:
    name: str
    actions: tuple[MacroAction, ...]
    created_at: float = field(default_factory=time.time)


class MacroStore:
    """Named, reviewable copy/move macros. Delete is intentionally excluded."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def all(self) -> dict[str, FileMacro]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return {
                name: FileMacro(
                    data["name"],
                    tuple(
                        MacroAction(
                            action["operation"],
                            tuple(action.get("items", [])),
                            action["destination"],
                            action["source_side"],
                            action.get("new_name"),
                        )
                        for action in data.get("actions", [])
                    ),
                    float(data.get("created_at", 0)),
                )
                for name, data in raw.items()
            }
        except (OSError, ValueError, TypeError, KeyError):
            return {}

    def save(self, macro: FileMacro) -> None:
        macros = self.all()
        macros[macro.name] = macro
        _atomic_json_write(
            self.path, {name: asdict(item) for name, item in macros.items()}
        )

    def get(self, name: str) -> FileMacro | None:
        return self.all().get(name)


@dataclass(frozen=True)
class FileActionPlan:
    operation: Literal["copy", "move", "delete", "rename", "mkdir"]
    items: tuple[Path, ...] = ()
    destination: Path | None = None
    new_name: str | None = None

    def describe(self) -> str:
        if self.operation == "mkdir":
            return f"Create folder: {self.destination}"
        names = ", ".join(path.name for path in self.items[:3])
        if len(self.items) > 3:
            names += f" (+{len(self.items) - 3})"
        suffix = f"\nDestination: {self.destination}" if self.destination else ""
        if self.new_name:
            suffix += f"\nNew name: {self.new_name}"
        return f"{self.operation.title()} {len(self.items)} item(s): {names}{suffix}"


def parse_safe_file_request(
    prompt: str,
    *,
    selected: Iterable[Path],
    active_directory: Path,
    passive_directory: Path,
) -> FileActionPlan:
    """Parse a deliberately small Korean/English natural-language command set."""
    import re

    text = prompt.strip()
    folded = text.casefold()
    for prefix in ("/file", "/파일", "file:", "파일작업:"):
        if folded.startswith(prefix.casefold()):
            text = text[len(prefix) :].strip()
            folded = text.casefold()
            break
    items = tuple(Path(path) for path in selected)

    if any(word in folded for word in ("복사", "copy")):
        if not items:
            raise ValueError("Select one or more files before requesting Copy.")
        return FileActionPlan("copy", items, passive_directory)
    if any(word in folded for word in ("이동", "move")):
        if not items:
            raise ValueError("Select one or more files before requesting Move.")
        return FileActionPlan("move", items, passive_directory)
    if any(word in folded for word in ("삭제", "delete", "trash")):
        if not items:
            raise ValueError("Select one or more files before requesting Delete.")
        return FileActionPlan("delete", items)

    rename = re.search(r"(?:rename.*?(?:to|as)|이름.*?(?:을|를))\s+(.+?)(?:으로|로)?$", text, re.I)
    if rename:
        if len(items) != 1:
            raise ValueError("Rename requires exactly one selected item.")
        new_name = rename.group(1).strip().strip('"\'')
        if not new_name or Path(new_name).name != new_name:
            raise ValueError("The new name must not contain a folder path.")
        return FileActionPlan("rename", items, items[0].parent, new_name)

    mkdir = re.search(r"(?:mkdir|create folder|폴더)\s+(.+?)(?:\s*(?:만들어|생성))?$", text, re.I)
    if mkdir:
        name = mkdir.group(1).strip().strip('"\'')
        if not name or Path(name).name != name:
            raise ValueError("The folder name must not contain a path.")
        return FileActionPlan("mkdir", destination=active_directory / name)

    raise ValueError(
        "Use /file with Copy, Move, Delete, Rename to NAME, or Create folder NAME."
    )


@dataclass(frozen=True)
class OperationPair:
    source: str
    target: str
    target_size: int | None = None
    target_mtime_ns: int | None = None
    target_signature: str | None = None


def _tree_signature(path: Path) -> str:
    """Fingerprint names and metadata, not file contents, for safe copy undo."""
    digest = hashlib.sha256()
    if path.is_file():
        stat = path.stat()
        digest.update(f"F\0{stat.st_size}\0{stat.st_mtime_ns}".encode())
        return digest.hexdigest()
    for directory, directories, files in os.walk(path):
        base = Path(directory)
        for name in sorted([*directories, *files], key=str.casefold):
            child = base / name
            stat = child.stat()
            relative = child.relative_to(path)
            kind = "D" if child.is_dir() else "F"
            digest.update(
                f"{kind}\0{relative}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode(
                    "utf-8", errors="surrogatepass"
                )
            )
    return digest.hexdigest()


@dataclass
class OperationRecord:
    operation: str
    pairs: list[OperationPair]
    undoable: bool
    note: str = ""
    created_at: float = field(default_factory=time.time)
    undone_at: float | None = None


class OperationJournal:
    """Persistent, conservative undo history for completed file operations."""

    def __init__(self, path: Path, *, limit: int = 200) -> None:
        self.path = path
        self.limit = limit

    def _load(self) -> list[OperationRecord]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return [
                OperationRecord(
                    operation=item["operation"],
                    pairs=[OperationPair(**pair) for pair in item.get("pairs", [])],
                    undoable=bool(item.get("undoable")),
                    note=str(item.get("note", "")),
                    created_at=float(item.get("created_at", 0)),
                    undone_at=item.get("undone_at"),
                )
                for item in raw
            ]
        except (OSError, ValueError, TypeError, KeyError):
            return []

    def _save(self, records: list[OperationRecord]) -> None:
        _atomic_json_write(self.path, [asdict(item) for item in records[-self.limit :]])

    def record(
        self,
        operation: str,
        pairs: Iterable[tuple[Path, Path]],
        *,
        undoable: bool = True,
        note: str = "",
    ) -> OperationRecord:
        saved_pairs: list[OperationPair] = []
        for source, target in pairs:
            size = mtime = None
            signature = None
            try:
                if target.exists():
                    stat = target.stat()
                    size, mtime = stat.st_size, stat.st_mtime_ns
                    signature = _tree_signature(target)
            except OSError:
                pass
            saved_pairs.append(
                OperationPair(str(source), str(target), size, mtime, signature)
            )
        record = OperationRecord(operation, saved_pairs, undoable, note)
        records = self._load()
        records.append(record)
        self._save(records)
        return record

    def latest_undoable(self) -> OperationRecord | None:
        return next(
            (item for item in reversed(self._load()) if item.undoable and item.undone_at is None),
            None,
        )

    @staticmethod
    def describe(record: OperationRecord) -> str:
        names = ", ".join(Path(pair.target).name for pair in record.pairs[:3])
        if len(record.pairs) > 3:
            names += f" (+{len(record.pairs) - 3})"
        return f"{record.operation.title()} {len(record.pairs)} item(s): {names}"

    def undo(self, record: OperationRecord) -> list[str]:
        """Undo only when current filesystem state still matches the journal."""
        errors: list[str] = []
        for pair in reversed(record.pairs):
            source, target = Path(pair.source), Path(pair.target)
            try:
                if record.operation == "copy":
                    if not target.exists():
                        continue
                    if target.is_file() and pair.target_size is not None:
                        stat = target.stat()
                        if (stat.st_size, stat.st_mtime_ns) != (
                            pair.target_size,
                            pair.target_mtime_ns,
                        ):
                            raise RuntimeError("copied file was modified; kept it")
                        target.unlink()
                    elif target.is_dir():
                        try:
                            target.rmdir()
                        except OSError:
                            if pair.target_signature != _tree_signature(target):
                                raise RuntimeError(
                                    "copied folder contents were modified; kept it"
                                )
                            shutil.rmtree(target)
                    else:
                        raise RuntimeError("unsupported copied item")
                elif record.operation in {"move", "rename"}:
                    if not target.exists() and source.exists():
                        continue
                    if source.exists():
                        raise RuntimeError("original path is already occupied")
                    if not target.exists():
                        raise RuntimeError("moved item no longer exists")
                    source.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(target), str(source))
                elif record.operation == "mkdir":
                    target.rmdir()
                else:
                    raise RuntimeError("this operation cannot be undone safely")
            except Exception as exc:
                errors.append(f"{target.name}: {exc}")
        if not errors:
            records = self._load()
            for item in reversed(records):
                if (
                    item.created_at == record.created_at
                    and item.operation == record.operation
                    and item.undone_at is None
                ):
                    item.undone_at = time.time()
                    break
            self._save(records)
        return errors


@dataclass(frozen=True)
class IndexedHit:
    path: Path
    size: int
    modified: float
    is_directory: bool


class FileIndex:
    """Small SQLite filename index, opened only when mIndex is used."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        import sqlite3

        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS files ("
            "root TEXT NOT NULL, path TEXT NOT NULL, name TEXT NOT NULL, "
            "size INTEGER NOT NULL, modified REAL NOT NULL, is_directory INTEGER NOT NULL, "
            "PRIMARY KEY (root, path))"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS indexed_roots ("
            "root TEXT PRIMARY KEY, indexed_at REAL NOT NULL)"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS files_name ON files(name)")
        return connection

    def rebuild(
        self,
        root: Path,
        *,
        cancel_event: Event | None = None,
        progress: Callable[[int, str], None] | None = None,
    ) -> int:
        root = root.resolve()
        rows: list[tuple[str, str, str, int, float, int]] = []
        stack = [root]
        count = 0
        while stack:
            if cancel_event and cancel_event.is_set():
                break
            directory = stack.pop()
            try:
                entries = list(os.scandir(directory))
            except (OSError, PermissionError):
                continue
            for entry in entries:
                if cancel_event and cancel_event.is_set():
                    break
                try:
                    stat = entry.stat(follow_symlinks=False)
                    is_directory = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                path = Path(entry.path)
                rows.append(
                    (str(root), str(path), entry.name, stat.st_size, stat.st_mtime, int(is_directory))
                )
                if is_directory and not entry.is_symlink():
                    stack.append(path)
                count += 1
                if progress and count % 500 == 0:
                    progress(count, str(directory))
        with self._connect() as connection:
            connection.execute("DELETE FROM files WHERE root = ?", (str(root),))
            connection.executemany(
                "INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?, ?, ?)", rows
            )
            connection.execute(
                "INSERT OR REPLACE INTO indexed_roots VALUES (?, ?)",
                (str(root), time.time()),
            )
        return count

    def has_root(self, root: Path) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM indexed_roots WHERE root = ?", (str(root.resolve()),)
            ).fetchone()
        return row is not None

    def search(self, root: Path, query: str, *, limit: int = 1000) -> list[IndexedHit]:
        terms = [term.casefold() for term in query.split() if term]
        if not terms:
            return []
        clauses = " AND ".join("lower(name) LIKE ?" for _ in terms)
        parameters: list[object] = [str(root.resolve()), *[f"%{term}%" for term in terms], limit]
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT path, size, modified, is_directory FROM files "
                f"WHERE root = ? AND {clauses} ORDER BY lower(name) LIMIT ?",
                parameters,
            ).fetchall()
        return [IndexedHit(Path(path), size, modified, bool(is_dir)) for path, size, modified, is_dir in rows]


def find_exact_duplicates(
    root: Path,
    *,
    cancel_event: Event | None = None,
    progress: Callable[[int, str], None] | None = None,
) -> list[list[Path]]:
    """Find exact duplicates with size grouping before expensive SHA-256 reads."""
    by_size: dict[int, list[Path]] = {}
    scanned = 0
    for directory, _, names in os.walk(root):
        for name in names:
            if cancel_event and cancel_event.is_set():
                return []
            path = Path(directory) / name
            try:
                by_size.setdefault(path.stat().st_size, []).append(path)
            except OSError:
                continue
            scanned += 1
            if progress and scanned % 250 == 0:
                progress(scanned, str(path.parent))

    by_digest: dict[tuple[int, str], list[Path]] = {}
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        for path in paths:
            if cancel_event and cancel_event.is_set():
                return []
            digest = hashlib.sha256()
            try:
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
            except OSError:
                continue
            by_digest.setdefault((size, digest.hexdigest()), []).append(path)
    return [paths for paths in by_digest.values() if len(paths) > 1]


def find_similar_images(
    root: Path,
    *,
    max_distance: int = 6,
    max_images: int = 5_000,
    cancel_event: Event | None = None,
) -> list[list[Path]]:
    """Find visually similar images with optional Pillow, imported on demand."""
    try:
        from PIL import Image
    except ImportError:
        return []

    extensions = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
    images: list[tuple[Path, int, tuple[int, int]]] = []
    for directory, _, names in os.walk(root):
        for name in names:
            if cancel_event and cancel_event.is_set():
                return []
            path = Path(directory) / name
            if path.suffix.casefold() not in extensions:
                continue
            try:
                with Image.open(path) as source:
                    dimensions = source.size
                    pixels = list(source.convert("L").resize((9, 8)).getdata())
                value = 0
                for row in range(8):
                    offset = row * 9
                    for column in range(8):
                        value = (value << 1) | int(
                            pixels[offset + column] > pixels[offset + column + 1]
                        )
                images.append((path, value, dimensions))
            except (OSError, ValueError):
                continue
            if len(images) >= max_images:
                break
        if len(images) >= max_images:
            break

    parents = list(range(len(images)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        first_root, second_root = find(first), find(second)
        if first_root != second_root:
            parents[second_root] = first_root

    by_dimensions: dict[tuple[int, int], list[int]] = {}
    for index, (_, _, dimensions) in enumerate(images):
        by_dimensions.setdefault(dimensions, []).append(index)
    for indices in by_dimensions.values():
        for offset, first in enumerate(indices):
            for second in indices[offset + 1 :]:
                if (images[first][1] ^ images[second][1]).bit_count() <= max_distance:
                    union(first, second)
    groups: dict[int, list[Path]] = {}
    for index, (path, _, _) in enumerate(images):
        groups.setdefault(find(index), []).append(path)
    return [paths for paths in groups.values() if len(paths) > 1]


@dataclass(frozen=True)
class CompareEntry:
    relative: Path
    status: Literal["left-only", "right-only", "different", "same"]
    is_directory: bool


def compare_directories(left: Path, right: Path) -> list[CompareEntry]:
    """Compare trees by relative path, type, size and modification time."""
    def collect(root: Path) -> dict[Path, tuple[bool, int, int]]:
        result: dict[Path, tuple[bool, int, int]] = {}
        for directory, directories, files in os.walk(root):
            base = Path(directory)
            for name in [*directories, *files]:
                path = base / name
                try:
                    stat = path.stat()
                    result[path.relative_to(root)] = (
                        path.is_dir(), stat.st_size, stat.st_mtime_ns
                    )
                except OSError:
                    continue
        return result

    left_items, right_items = collect(left), collect(right)
    rows: list[CompareEntry] = []
    for relative in sorted(set(left_items) | set(right_items), key=lambda p: str(p).casefold()):
        left_meta, right_meta = left_items.get(relative), right_items.get(relative)
        if left_meta is None:
            status = "right-only"
            is_directory = bool(right_meta and right_meta[0])
        elif right_meta is None:
            status = "left-only"
            is_directory = left_meta[0]
        else:
            is_directory = left_meta[0]
            status = "same" if left_meta == right_meta else "different"
        rows.append(CompareEntry(relative, status, is_directory))
    return rows


def safe_sync_directories(
    source: Path,
    destination: Path,
    entries: Iterable[CompareEntry],
    *,
    cancel_event: Event | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> tuple[list[tuple[Path, Path]], list[str]]:
    """Copy new/changed source files without deleting anything at destination."""
    candidates = [
        entry
        for entry in entries
        if entry.status in {"left-only", "different"}
    ]
    completed: list[tuple[Path, Path]] = []
    errors: list[str] = []
    for index, entry in enumerate(candidates, start=1):
        if cancel_event and cancel_event.is_set():
            break
        source_path = source / entry.relative
        target_path = destination / entry.relative
        try:
            if entry.is_directory:
                existed = target_path.exists()
                target_path.mkdir(parents=True, exist_ok=True)
                if not existed:
                    completed.append((source_path, target_path))
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)
                completed.append((source_path, target_path))
        except Exception as exc:
            errors.append(f"{entry.relative}: {exc}")
        if progress:
            progress(index, len(candidates), str(entry.relative))
    return completed, errors
