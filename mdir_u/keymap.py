from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


KEYMAP_ENVIRONMENT_VARIABLE = "MDIR_U_KEYMAP"
DEFAULT_KEYMAP_PATH = Path.home() / ".config" / "mdir-u" / "keys.json"


@dataclass(frozen=True)
class KeyDefinition:
    label: str
    action: str
    default_key: str
    editable: bool
    binding_id: str | None = None


KEY_DEFINITIONS = (
    KeyDefinition("Switch pane", "switch_pane", "tab", False),
    KeyDefinition("Left pane", "focus_left", "left", False),
    KeyDefinition("Right pane", "focus_right", "right", False),
    KeyDefinition("Open", "open_item", "enter", False),
    KeyDefinition("Parent", "parent", "backspace", False),
    KeyDefinition("Mark", "mark", "space", False),
    KeyDefinition("Select up", "shift_select_up", "shift+up", False),
    KeyDefinition("Select down", "shift_select_down", "shift+down", False),
    KeyDefinition("Select to top", "shift_select_home", "shift+home", False),
    KeyDefinition("Select to bottom", "shift_select_end", "shift+end", False),
    KeyDefinition("Select page up", "shift_select_page_up", "shift+pageup", False),
    KeyDefinition("Select page down", "shift_select_page_down", "shift+pagedown", False),
    KeyDefinition("Options", "options", "f10", False),
    KeyDefinition("Rename", "rename", "f2", True, "mdir.rename"),
    KeyDefinition("Batch rename", "batch_rename", "ctrl+f2", True, "mdir.batch_rename"),
    KeyDefinition("View", "view", "f3", True, "mdir.view"),
    KeyDefinition("Edit", "edit", "f4", True, "mdir.edit"),
    KeyDefinition("Copy", "copy", "f5", True, "mdir.copy"),
    KeyDefinition("Move", "move", "f6", True, "mdir.move"),
    KeyDefinition("ZIP", "compress_zip", "alt+f5", True, "mdir.compress_zip"),
    KeyDefinition("Unzip", "extract_zip", "alt+f6", True, "mdir.extract_zip"),
    KeyDefinition("New folder", "mkdir", "f7", True, "mdir.mkdir"),
    KeyDefinition("Delete", "delete", "f8", True, "mdir.delete"),
    KeyDefinition("Delete alias", "delete", "delete", True, "mdir.delete_alias"),
    KeyDefinition("Drive", "drive", "f9", True, "mdir.drive"),
    KeyDefinition("Find", "search", "ctrl+f", True, "mdir.search"),
    KeyDefinition("mIndex", "mindex", "ctrl+shift+f", True, "mdir.mindex"),
    KeyDefinition("Duplicates", "find_duplicates", "ctrl+shift+d", True, "mdir.duplicates"),
    KeyDefinition("Compare", "compare_folders", "ctrl+shift+c", True, "mdir.compare"),
    KeyDefinition("Safe sync", "safe_sync", "ctrl+shift+y", True, "mdir.safe_sync"),
    KeyDefinition("Record macro", "toggle_macro_recording", "ctrl+shift+m", True, "mdir.record_macro"),
    KeyDefinition("Play macro", "play_macro", "ctrl+alt+m", True, "mdir.play_macro"),
    KeyDefinition("Save workspace", "save_workspace", "ctrl+shift+s", True, "mdir.save_workspace"),
    KeyDefinition("Load workspace", "load_workspace", "ctrl+shift+l", True, "mdir.load_workspace"),
    KeyDefinition("Name sort", "sort_name", "ctrl+n", True, "mdir.sort_name"),
    KeyDefinition("Extension sort", "sort_ext", "ctrl+e", True, "mdir.sort_ext"),
    KeyDefinition("Size sort", "sort_size", "ctrl+s", True, "mdir.sort_size"),
    KeyDefinition("Modified sort", "sort_date", "ctrl+d", True, "mdir.sort_date"),
    KeyDefinition("Refresh", "refresh_all", "ctrl+r", True, "mdir.refresh"),
    KeyDefinition("Refresh drives", "refresh_drives", "f11", True, "mdir.refresh_drives"),
    KeyDefinition("Hidden/System", "hidden_system", "ctrl+h", True, "mdir.hidden_system"),
    KeyDefinition("Column widths", "column_widths", "ctrl+w", True, "mdir.column_widths"),
    KeyDefinition("Reset widths", "reset_column_widths", "ctrl+shift+w", True, "mdir.reset_widths"),
    KeyDefinition("Properties", "properties", "alt+enter", True, "mdir.properties"),
    KeyDefinition("Folder size", "folder_size", "ctrl+g", True, "mdir.folder_size"),
    KeyDefinition("Terminal", "powershell_here", "shift+f10", True, "mdir.terminal"),
    KeyDefinition("Left drive", "drive_left", "alt+f1", True, "mdir.drive_left"),
    KeyDefinition("Right drive", "drive_right", "alt+f2", True, "mdir.drive_right"),
    KeyDefinition("AI/File", "toggle_ai_terminal", "f12", True, "mdir.ai"),
    KeyDefinition("Preview", "toggle_preview", "ctrl+f3", True, "mdir.preview"),
)


EDITABLE_DEFINITIONS = tuple(
    definition for definition in KEY_DEFINITIONS if definition.editable
)
DEFINITION_BY_ID = {
    definition.binding_id: definition
    for definition in EDITABLE_DEFINITIONS
    if definition.binding_id
}
FIXED_KEYS = frozenset(
    definition.default_key for definition in KEY_DEFINITIONS if not definition.editable
)
_NAMED_KEYS = {
    "backspace", "delete", "down", "end", "enter", "escape", "home",
    "insert", "left", "pagedown", "pageup", "right", "space", "tab", "up",
}
_MODIFIERS = {"alt", "ctrl", "shift", "super"}
_SIMPLE_KEY = re.compile(r"^(?:[a-z0-9]|f(?:[1-9]|1[0-9]|2[0-4]))$")


def keymap_config_path() -> Path:
    configured = os.environ.get(KEYMAP_ENVIRONMENT_VARIABLE, "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_KEYMAP_PATH


def normalize_shortcut(value: str) -> str:
    """Normalize and validate one user-entered Textual shortcut."""
    parts = [part.strip().lower() for part in value.split("+") if part.strip()]
    if not parts:
        raise ValueError("Enter a key, for example ctrl+alt+x or f5.")
    key = parts[-1]
    modifiers = parts[:-1]
    if len(set(modifiers)) != len(modifiers) or any(
        modifier not in _MODIFIERS for modifier in modifiers
    ):
        raise ValueError("Use ctrl, alt, shift, or super before the key.")
    if key not in _NAMED_KEYS and not _SIMPLE_KEY.fullmatch(key):
        raise ValueError("Unsupported key name.")
    order = {"ctrl": 0, "alt": 1, "shift": 2, "super": 3}
    return "+".join([*sorted(modifiers, key=order.get), key])


def effective_keys(overrides: Mapping[str, str]) -> dict[str, str]:
    return {
        definition.binding_id: overrides.get(
            definition.binding_id, definition.default_key
        )
        for definition in EDITABLE_DEFINITIONS
        if definition.binding_id
    }


def validate_keymap(values: Mapping[str, object]) -> dict[str, str]:
    """Keep known editable bindings and reject collisions or fixed keys."""
    validated: dict[str, str] = {}
    used = set(FIXED_KEYS)
    for definition in EDITABLE_DEFINITIONS:
        binding_id = definition.binding_id
        if binding_id is None:
            continue
        raw = values.get(binding_id, definition.default_key)
        if not isinstance(raw, str):
            raise ValueError(f"Invalid key for {definition.label}.")
        key = normalize_shortcut(raw)
        if key in used:
            raise ValueError(f"The key {key} is already assigned.")
        used.add(key)
        if key != definition.default_key:
            validated[binding_id] = key
    return validated


def load_keymap(path: Path | None = None) -> dict[str, str]:
    config_path = path or keymap_config_path()
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return {}
        return validate_keymap(value)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def save_keymap(
    values: Mapping[str, object], path: Path | None = None
) -> Path:
    config_path = path or keymap_config_path()
    validated = validate_keymap(values)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = config_path.with_suffix(config_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(validated, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(config_path)
    return config_path
