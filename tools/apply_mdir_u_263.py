from __future__ import annotations

import base64
import json
import lzma
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD_DIR = ROOT / "tools" / "mdir_u_263_payload"


def unpack(payload: str, target: str) -> None:
    path = ROOT / target
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(lzma.decompress(base64.b64decode(payload.strip())))


unpack((PAYLOAD_DIR / "advanced.b64").read_text(encoding="utf-8"), "mdir_u/advanced.py")
unpack((PAYLOAD_DIR / "base.b64").read_text(encoding="utf-8"), "mdir_u/base.py")
rest = json.loads((PAYLOAD_DIR / "rest.json").read_text(encoding="utf-8"))
unpack(rest["file_operations"], "mdir_u/file_operations.py")
unpack(rest["keymap"], "mdir_u/keymap.py")
unpack(rest["test_advanced"], "tests/test_advanced.py")
unpack(rest["install"], "install_ubuntu.sh")

# Keep package and build metadata on the same release number.
init_path = ROOT / "mdir_u" / "__init__.py"
text = init_path.read_text(encoding="utf-8")
text = text.replace('__version__ = "2.26.2"', '__version__ = "2.26.3"')
init_path.write_text(text, encoding="utf-8")

pyproject = ROOT / "pyproject.toml"
text = pyproject.read_text(encoding="utf-8")
text = text.replace('version = "2.26.2"', 'version = "2.26.3"')
pyproject.write_text(text, encoding="utf-8")

# Remove obsolete Undo guidance and document the safer update path.
readme = ROOT / "README.md"
text = readme.read_text(encoding="utf-8")
text = text.replace(
    "- installs the required Ubuntu packages, including nano;",
    "- installs only missing required Ubuntu packages, including nano;",
)
text = text.replace(
    "- installs all Preview dependencies;",
    "- installs missing Preview dependencies while reusing the existing venv and pip cache;",
)
text = text.replace(
    "The installer can be run again at any time. It safely updates the program and\n"
    "keeps personal settings.",
    "The installer can be run again at any time. It safely updates the program, reuses\n"
    "already-installed dependencies, and keeps personal settings.",
)
text = text.replace(
    "Copy/Move/Rename/MkDir are recorded by Undo Center. Trash\n"
    "deletes are intentionally not restored automatically by mDIR-U.",
    "mDIR-U does not provide automatic Undo. Copy/Move/Rename/MkDir therefore rely\n"
    "on explicit review, overwrite confirmation, and rollback-aware file handling.\n"
    "Delete continues to use Ubuntu Trash whenever the item qualifies for Trash.",
)
text = text.replace("| `Ctrl+Z` | Undo Center |\n", "")
needle = (
    "Copy, Move, and Delete run in a background worker. Large batches show progress\n"
    "and an ETA; press `Esc` or choose **Cancel** to close the progress dialog\n"
    "immediately and prevent another top-level item from starting.\n"
)
replacement = needle + (
    "\nCopy/Move also block a directory from being copied or moved into itself or its\n"
    "own subtree. Approved overwrites are staged first, so a failed replacement can\n"
    "restore the previous destination instead of leaving it deleted.\n"
)
text = text.replace(needle, replacement)
readme.write_text(text, encoding="utf-8")

changelog = ROOT / "CHANGELOG.md"
text = changelog.read_text(encoding="utf-8")
section = """## 2.26.3

- Removed automatic Undo from mDIR-U. File safety now relies on explicit confirmation, Ubuntu Trash, conflict checks, and rollback-aware replacement rather than a second automatic filesystem mutation.
- Blocked Copy and Move when a directory target is the source itself or lies inside the source tree.
- Hardened Safe Sync against destination-inside-source recursion, symbolic links, and file/folder type conflicts; changed file replacement now uses a staged atomic publish.
- Preserved the previous `mIndex` when a rebuild is cancelled and staged rebuild rows in SQLite before publishing them.
- Protected approved Copy/Move overwrites with staging and rollback so a failed operation keeps the previous destination.
- Moved Safe Sync comparison off the Textual UI thread before showing the confirmation dialog.
- Optimized `install_ubuntu.sh` to reuse its private venv and pip cache, avoid forced reinstalls and repeated pip upgrades, and run `apt` only for missing system packages.
- Added regression coverage for subtree operations, overwrite rollback, Safe Sync conflicts, and cancelled index rebuilds.

"""
if "## 2.26.3" not in text:
    text = text.replace("# Changelog\n\n", "# Changelog\n\n" + section, 1)
changelog.write_text(text, encoding="utf-8")

# Safety assertions: fail the automation instead of publishing a partial update.
if '__version__ = "2.26.3"' not in init_path.read_text(encoding="utf-8"):
    raise RuntimeError("package version was not updated")
if 'version = "2.26.3"' not in pyproject.read_text(encoding="utf-8"):
    raise RuntimeError("pyproject version was not updated")
for relative in ("mdir_u/keymap.py", "README.md"):
    value = (ROOT / relative).read_text(encoding="utf-8")
    if "Undo Center" in value or '"undo_last"' in value:
        raise RuntimeError(f"Undo residue remains in {relative}")

print("mDIR-U 2.26.3 safety update applied")
