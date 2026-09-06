from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


MAX_SHORTCUTS = 16
SHORTCUT_KINDS = {"folder", "file", "program", "web", "action", "command"}
CONFIG_ENVIRONMENT_VARIABLE = "MDIR_U_SHORTCUTS"
DEFAULT_CONFIG_PATH = Path.home() / ".mdir-u-shortcuts.json"


@dataclass(frozen=True)
class ShortcutDefinition:
    """One user-configurable item displayed in the top shortcut bar."""

    label: str
    kind: str
    target: str
    args: tuple[str, ...] = ()
    pane: str = "active"


DEFAULT_SHORTCUTS = (
    ShortcutDefinition("Home", "folder", "{home}"),
    ShortcutDefinition("MDIR-U", "folder", "{project}"),
    ShortcutDefinition("Terminal", "action", "powershell_here"),
    ShortcutDefinition("Preview", "action", "toggle_preview"),
    ShortcutDefinition("AI", "action", "toggle_ai_terminal"),
    ShortcutDefinition("GitHub", "web", "https://github.com/jtl-sun/mdir-u"),
)


def shortcut_config_path() -> Path:
    configured = os.environ.get(CONFIG_ENVIRONMENT_VARIABLE, "").strip()
    if configured:
        return Path(os.path.expandvars(configured)).expanduser()
    return DEFAULT_CONFIG_PATH


def _definition_from_value(value: object) -> ShortcutDefinition | None:
    if not isinstance(value, dict):
        return None

    label = str(value.get("label", "")).strip()
    kind = str(value.get("type", value.get("kind", ""))).strip().lower()
    target = str(value.get("target", "")).strip()
    pane = str(value.get("pane", "active")).strip().lower()
    raw_args = value.get("args", [])

    if not label or kind not in SHORTCUT_KINDS or not target:
        return None
    if pane not in {"active", "left", "right"}:
        pane = "active"
    if not isinstance(raw_args, list):
        raw_args = []

    return ShortcutDefinition(
        label=label[:24],
        kind=kind,
        target=target,
        args=tuple(str(argument) for argument in raw_args),
        pane=pane,
    )


def parse_shortcuts(values: object) -> list[ShortcutDefinition]:
    """Validate untrusted JSON values and return a bounded shortcut list."""
    if not isinstance(values, list):
        return []
    parsed: list[ShortcutDefinition] = []
    for value in values:
        definition = _definition_from_value(value)
        if definition is not None:
            parsed.append(definition)
        if len(parsed) >= MAX_SHORTCUTS:
            break
    return parsed


def load_shortcuts(path: Path | None = None) -> list[ShortcutDefinition]:
    """Load user shortcuts, or use the safe built-in defaults."""
    config_path = path or shortcut_config_path()
    try:
        values = json.loads(config_path.read_text(encoding="utf-8"))
        if isinstance(values, list):
            return parse_shortcuts(values)
        return list(DEFAULT_SHORTCUTS)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return list(DEFAULT_SHORTCUTS)


def _serializable(shortcuts: Iterable[ShortcutDefinition]) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for shortcut in shortcuts:
        value = asdict(shortcut)
        value["type"] = value.pop("kind")
        value["args"] = list(shortcut.args)
        values.append(value)
    return values


def ensure_shortcut_config(path: Path | None = None) -> Path:
    """Create an editable default shortcut file when one does not exist."""
    config_path = path or shortcut_config_path()
    if config_path.exists():
        return config_path
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            _serializable(DEFAULT_SHORTCUTS),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return config_path


def save_shortcuts(
    shortcuts: Iterable[ShortcutDefinition],
    path: Path | None = None,
) -> Path:
    """Persist a validated shortcut list using an atomic file replacement."""
    config_path = path or shortcut_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = config_path.with_suffix(config_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(
            _serializable(tuple(shortcuts)[:MAX_SHORTCUTS]),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(config_path)
    return config_path


def expand_shortcut_text(
    value: str,
    *,
    current: Path,
    left: Path,
    right: Path,
    project: Path,
    selected: Path | None = None,
    left_selected: Path | None = None,
    right_selected: Path | None = None,
) -> str:
    """Expand MDIR placeholders and platform environment variables."""
    replacements = {
        "{current}": str(current),
        "{left}": str(left),
        "{right}": str(right),
        "{selected}": str(selected or current),
        "{left_selected}": str(left_selected or left),
        "{right_selected}": str(right_selected or right),
        "{home}": str(Path.home()),
        "{project}": str(project),
    }
    expanded = value
    for token, replacement in replacements.items():
        expanded = expanded.replace(token, replacement)
    return os.path.expandvars(os.path.expanduser(expanded))
