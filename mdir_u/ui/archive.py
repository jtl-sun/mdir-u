from __future__ import annotations

import os
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Optional, Sequence

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static


class ArchiveError(RuntimeError):
    """A user-facing archive validation or processing error."""


WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


@dataclass(frozen=True)
class CreateZipRequest:
    destination: Path
    overwrite: bool = False
    compression_level: int = 6


@dataclass(frozen=True)
class ExtractZipRequest:
    destination: Path
    overwrite: bool = False


@dataclass(frozen=True)
class ArchiveResult:
    files: int
    directories: int
    bytes_processed: int


def next_available_zip_path(destination: Path) -> Path:
    """Return *destination* or a Windows-style numbered ZIP filename."""
    candidate = destination.expanduser()
    if candidate.suffix.lower() != ".zip":
        candidate = candidate.with_suffix(".zip")
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    for number in range(2, 10_000):
        numbered = candidate.with_name(f"{stem} ({number}).zip")
        if not numbered.exists():
            return numbered
    raise ArchiveError("Could not find an available ZIP filename.")


def _same_path(first: Path, second: Path) -> bool:
    try:
        return first.resolve(strict=False) == second.resolve(strict=False)
    except OSError:
        return os.path.abspath(first) == os.path.abspath(second)


def _path_is_within(path: Path, directory: Path) -> bool:
    """Return whether *path* is inside *directory* after normalization."""
    try:
        path.resolve(strict=False).relative_to(directory.resolve(strict=False))
        return True
    except (OSError, ValueError):
        return False


def _archive_entries(items: Sequence[Path], destination: Path):
    """Yield (source, archive-name, is-directory), excluding the output ZIP."""
    seen_names: set[str] = set()
    for item in items:
        source = Path(item)
        if not source.exists():
            raise ArchiveError(f"Source does not exist: {source}")
        root_name = source.name
        folded = root_name.casefold()
        if folded in seen_names:
            raise ArchiveError(f"Duplicate top-level name: {root_name}")
        seen_names.add(folded)

        if source.is_dir():
            yield source, f"{root_name}/", True
            for current, directories, filenames in os.walk(source):
                directories.sort(key=str.casefold)
                filenames.sort(key=str.casefold)
                current_path = Path(current)
                relative = current_path.relative_to(source)
                archive_dir = PurePosixPath(root_name, *relative.parts)
                if not directories and not filenames and relative.parts:
                    yield current_path, f"{archive_dir.as_posix()}/", True
                for filename in filenames:
                    file_path = current_path / filename
                    if _same_path(file_path, destination):
                        continue
                    archive_name = (archive_dir / filename).as_posix()
                    yield file_path, archive_name, False
        else:
            if _same_path(source, destination):
                raise ArchiveError("The output ZIP cannot also be a source file.")
            yield source, root_name, False


def create_zip_archive(
    items: Sequence[Path],
    request: CreateZipRequest,
) -> ArchiveResult:
    """Create a ZIP atomically so a failed operation never replaces a good ZIP."""
    if not items:
        raise ArchiveError("Select one or more files or folders first.")
    destination = request.destination.expanduser()
    if destination.suffix.lower() != ".zip":
        destination = destination.with_suffix(".zip")
    if destination.exists() and not request.overwrite:
        raise ArchiveError(f"Archive already exists: {destination}")

    # The archive is created as a temporary file beside the destination.  If
    # that location is inside a selected source directory, os.walk() can see
    # the growing temporary ZIP and try to add it to itself.  Apart from being
    # surprising, that can rapidly consume disk space.  Require the archive to
    # be placed outside every selected directory.
    for item in items:
        source = Path(item).expanduser()
        if source.is_dir() and _path_is_within(destination, source):
            raise ArchiveError(
                "Save the ZIP outside the folder being compressed: "
                f"{source}"
            )
    destination.parent.mkdir(parents=True, exist_ok=True)

    temporary_path: Optional[Path] = None
    files = directories = bytes_processed = 0
    try:
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        os.close(handle)
        temporary_path = Path(temporary_name)
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=max(0, min(9, request.compression_level)),
            allowZip64=True,
        ) as archive:
            for source, archive_name, is_directory in _archive_entries(
                items, destination
            ):
                if is_directory:
                    info = zipfile.ZipInfo(archive_name)
                    info.external_attr = (0o40755 << 16) | 0x10
                    archive.writestr(info, b"")
                    directories += 1
                else:
                    archive.write(source, archive_name)
                    files += 1
                    try:
                        bytes_processed += source.stat().st_size
                    except OSError:
                        pass
        os.replace(temporary_path, destination)
        temporary_path = None
    except ArchiveError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise ArchiveError(f"Could not create ZIP: {exc}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
    return ArchiveResult(files, directories, bytes_processed)


def _safe_member_path(destination: Path, member_name: str) -> Path:
    normalized = member_name.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if (
        not normalized
        or pure.is_absolute()
        or ".." in pure.parts
        or any(":" in part for part in pure.parts)
    ):
        raise ArchiveError(f"Unsafe path in ZIP: {member_name}")
    for part in pure.parts:
        base = part.split(".", 1)[0].upper()
        if (
            any(ord(character) < 32 or character in '<>"|?*' for character in part)
            or part.endswith((" ", "."))
            or base in WINDOWS_RESERVED_NAMES
        ):
            raise ArchiveError(f"Invalid Windows filename in ZIP: {member_name}")
    target = destination.joinpath(*pure.parts)
    try:
        target.resolve(strict=False).relative_to(destination.resolve(strict=False))
    except (OSError, ValueError) as exc:
        raise ArchiveError(f"Unsafe path in ZIP: {member_name}") from exc
    return target


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def extract_zip_archive(
    archive_path: Path,
    request: ExtractZipRequest,
) -> ArchiveResult:
    """Extract a ZIP without path traversal, symlinks, or partial file writes."""
    archive_path = Path(archive_path)
    if not archive_path.is_file() or not zipfile.is_zipfile(archive_path):
        raise ArchiveError(f"Not a valid ZIP file: {archive_path}")
    destination = request.destination.expanduser()
    destination.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            members = archive.infolist()
            if len(members) > 100_000:
                raise ArchiveError("ZIP contains too many entries (maximum 100,000).")

            targets: list[tuple[zipfile.ZipInfo, Path]] = []
            collisions: list[Path] = []
            seen_targets: set[str] = set()
            member_kinds: dict[str, bool] = {}
            for info in members:
                if _is_zip_symlink(info):
                    raise ArchiveError(f"Symbolic links are not extracted: {info.filename}")
                target = _safe_member_path(destination, info.filename)
                target_key = str(target.resolve(strict=False)).casefold()
                if target_key in seen_targets:
                    raise ArchiveError(f"Duplicate path in ZIP: {info.filename}")
                seen_targets.add(target_key)
                member_kinds[target_key] = info.is_dir()
                targets.append((info, target))
                if target.exists():
                    if info.is_dir() and not target.is_dir():
                        raise ArchiveError(
                            f"ZIP directory conflicts with a file: {target}"
                        )
                    if not info.is_dir() and target.is_dir():
                        raise ArchiveError(
                            f"ZIP file conflicts with a directory: {target}"
                        )
                    if not info.is_dir() and not request.overwrite:
                        collisions.append(target)

            # Validate the complete member tree before writing anything.  A
            # malformed archive can otherwise create a file named "folder"
            # and fail later when extracting "folder/item.txt", leaving a
            # partially extracted result behind.
            destination_key = str(destination.resolve(strict=False)).casefold()
            for info, target in targets:
                parent = target.parent
                while str(parent.resolve(strict=False)).casefold() != destination_key:
                    parent_key = str(parent.resolve(strict=False)).casefold()
                    if member_kinds.get(parent_key) is False:
                        raise ArchiveError(
                            "ZIP member has a file where a folder is required: "
                            f"{info.filename}"
                        )
                    if parent.exists() and not parent.is_dir():
                        raise ArchiveError(
                            f"Extraction folder conflicts with a file: {parent}"
                        )
                    next_parent = parent.parent
                    if next_parent == parent:
                        break
                    parent = next_parent
            if collisions:
                sample = ", ".join(path.name for path in collisions[:3])
                extra = f" (+{len(collisions) - 3})" if len(collisions) > 3 else ""
                raise ArchiveError(f"Existing file(s) would be replaced: {sample}{extra}")

            files = directories = bytes_processed = 0
            for info, target in targets:
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    directories += 1
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                handle, temporary_name = tempfile.mkstemp(
                    prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
                )
                os.close(handle)
                temporary_path = Path(temporary_name)
                try:
                    with archive.open(info, "r") as source, temporary_path.open("wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
                    os.replace(temporary_path, target)
                    temporary_path = None
                    try:
                        timestamp = datetime(*info.date_time).timestamp()
                        os.utime(target, (timestamp, timestamp))
                    except (OSError, ValueError, OverflowError):
                        pass
                    files += 1
                    bytes_processed += info.file_size
                finally:
                    if temporary_path is not None:
                        temporary_path.unlink(missing_ok=True)
    except ArchiveError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ArchiveError(f"Could not extract ZIP: {exc}") from exc
    return ArchiveResult(files, directories, bytes_processed)


ARCHIVE_CSS = """
CreateZipScreen, ExtractZipScreen {
    align: center middle;
    background: #00000073;
}
#archive_dialog {
    width: 92;
    max-width: 94%;
    height: auto;
    max-height: 26;
    border: solid $primary;
    background: $surface;
    padding: 0 1;
}
#archive_header { height: 1; }
#archive_title { width: 1fr; height: 1; text-style: bold; }
#archive_close {
    width: 3; min-width: 3; height: 1; min-height: 1; max-height: 1;
    padding: 0; border: none; background: $error-darken-1;
}
.archive_label { height: 1; margin-top: 1; }
#archive_path { height: 3; }
#archive_summary { height: 2; color: #bbbbbb; }
#archive_options { height: 3; }
#archive_level { width: 28; margin-left: 2; }
#archive_actions { height: 3; align-horizontal: right; margin-top: 1; }
#archive_actions Button { min-width: 12; margin-left: 1; }
"""


class ArchiveDialog(ModalScreen):
    CSS = ARCHIVE_CSS

    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#archive_cancel")
    @on(Button.Pressed, "#archive_close")
    def cancel_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        self._cancel()

    def key_escape(self) -> None:
        self._cancel()


class CreateZipScreen(ArchiveDialog):
    def __init__(self, items: Sequence[Path], destination: Path) -> None:
        super().__init__()
        self.items = tuple(items)
        self.destination = destination

    def compose(self) -> ComposeResult:
        with Vertical(id="archive_dialog"):
            with Horizontal(id="archive_header"):
                yield Label("Create ZIP archive", id="archive_title")
                yield Button("X", id="archive_close")
            yield Static(
                f"{len(self.items)} selected item(s) will be compressed.",
                id="archive_summary",
            )
            yield Label("ZIP file:", classes="archive_label")
            yield Input(str(self.destination), id="archive_path")
            with Horizontal(id="archive_options"):
                yield Checkbox("Overwrite existing ZIP", id="archive_overwrite")
                yield Select(
                    [("Fast", 1), ("Normal", 6), ("Maximum", 9)],
                    value=6,
                    allow_blank=False,
                    id="archive_level",
                )
            with Horizontal(id="archive_actions"):
                yield Button("Create ZIP", id="archive_accept", variant="primary")
                yield Button("Cancel", id="archive_cancel")

    @on(Button.Pressed, "#archive_accept")
    def accept_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        raw = self.query_one("#archive_path", Input).value.strip()
        if not raw:
            self.app.notify("Enter a ZIP filename.", title="Create ZIP")
            return
        destination = Path(raw).expanduser()
        if destination.suffix.lower() != ".zip":
            destination = destination.with_suffix(".zip")
        overwrite = self.query_one("#archive_overwrite", Checkbox).value
        if destination.exists() and not overwrite:
            self.app.notify(
                "That ZIP already exists. Change the filename or enable "
                "Overwrite existing ZIP.",
                title="ZIP already exists",
            )
            self.query_one("#archive_path", Input).focus()
            return

        level = self.query_one("#archive_level", Select).value
        self.dismiss(
            CreateZipRequest(
                destination,
                overwrite,
                int(level) if isinstance(level, int) else 6,
            )
        )


class ExtractZipScreen(ArchiveDialog):
    def __init__(self, archive_path: Path, destination: Path) -> None:
        super().__init__()
        self.archive_path = archive_path
        self.destination = destination

    def compose(self) -> ComposeResult:
        with Vertical(id="archive_dialog"):
            with Horizontal(id="archive_header"):
                yield Label("Extract ZIP archive", id="archive_title")
                yield Button("X", id="archive_close")
            yield Static(f"Archive: {self.archive_path.name}", id="archive_summary")
            yield Label("Extract to:", classes="archive_label")
            yield Input(str(self.destination), id="archive_path")
            with Horizontal(id="archive_options"):
                yield Checkbox("Overwrite existing files", id="archive_overwrite")
            with Horizontal(id="archive_actions"):
                yield Button("Extract", id="archive_accept", variant="primary")
                yield Button("Cancel", id="archive_cancel")

    @on(Button.Pressed, "#archive_accept")
    def accept_clicked(self, event: Button.Pressed) -> None:
        event.stop()
        raw = self.query_one("#archive_path", Input).value.strip()
        if not raw:
            self.app.notify("Enter an extraction folder.", title="Extract ZIP")
            return
        self.dismiss(
            ExtractZipRequest(
                Path(raw),
                self.query_one("#archive_overwrite", Checkbox).value,
            )
        )
