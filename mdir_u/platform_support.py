from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Location:
    label: str
    path: Path


def shell_executable() -> str | None:
    """Return the user's local command shell."""
    configured = os.environ.get("SHELL", "").strip()
    if configured and Path(configured).is_file():
        return configured
    for name in ("bash", "zsh", "fish", "sh", "pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return None


def open_with_default_app(path: Path) -> None:
    """Open a path using the desktop's default application."""
    if os.name == "nt":
        os.startfile(str(path))
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
        return
    opener = shutil.which("xdg-open")
    if opener:
        subprocess.Popen([opener, str(path)])
        return
    gio = shutil.which("gio")
    if gio:
        subprocess.Popen([gio, "open", str(path)])
        return
    raise OSError("No desktop opener was found (install xdg-utils).")


def terminal_command(cwd: Path) -> list[str] | None:
    """Build a terminal-emulator command rooted at *cwd*."""
    candidates = (
        ("x-terminal-emulator", ["x-terminal-emulator"]),
        ("gnome-terminal", ["gnome-terminal", f"--working-directory={cwd}"]),
        ("konsole", ["konsole", "--workdir", str(cwd)]),
        ("xfce4-terminal", ["xfce4-terminal", "--working-directory", str(cwd)]),
        ("xterm", ["xterm"]),
    )
    for executable, command in candidates:
        found = shutil.which(executable)
        if not found:
            continue
        command[0] = found
        return command
    return None


def locations() -> list[Location]:
    """Return useful Ubuntu locations and mounted filesystems."""
    home = Path.home()
    found: list[Location] = [
        Location("Root", Path("/")),
        Location("Home", home),
    ]
    for label, path in (
        ("Mnt", Path("/mnt")),
        ("Media", Path("/media")),
        ("User media", Path("/run/media") / os.environ.get("USER", "")),
    ):
        if path.is_dir():
            found.append(Location(label, path))

    seen = {str(item.path.resolve()) for item in found}
    for parent in (Path("/mnt"), Path("/media"), Path("/run/media") / os.environ.get("USER", "")):
        if not parent.is_dir():
            continue
        try:
            children = sorted(
                (child for child in parent.iterdir() if child.is_dir()),
                key=lambda child: child.name.casefold(),
            )
        except OSError:
            continue
        for child in children:
            try:
                key = str(child.resolve())
            except OSError:
                key = str(child)
            if key not in seen:
                seen.add(key)
                found.append(Location(child.name, child))
    return found


def filesystem_usage_text(path: Path) -> str:
    """Return concise free/total storage information for a pane."""
    try:
        usage = shutil.disk_usage(path)
        gib = 1024 ** 3
        return (
            f"{path}  {usage.free / gib:,.1f} GiB free / "
            f"{usage.total / gib:,.1f} GiB total"
        )
    except OSError:
        return str(path)
