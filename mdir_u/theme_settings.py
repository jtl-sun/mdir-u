from __future__ import annotations

import json
from pathlib import Path

from .advanced import advanced_data_dir


THEME_SETTINGS_FILENAME = "theme.json"


def theme_settings_path() -> Path:
    return advanced_data_dir("mDIR-U") / THEME_SETTINGS_FILENAME


def load_theme_name(default: str, path: Path | None = None) -> str:
    config_path = path or theme_settings_path()
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default
    if isinstance(value, dict):
        name = value.get("theme")
        if isinstance(name, str) and name.strip():
            # Preserve users' previously selected old_M_tema preference.
            return "Old-MDIR" if name.strip() == "old_M_tema" else name.strip()
    return default


def save_theme_name(name: str, path: Path | None = None) -> Path:
    config_path = path or theme_settings_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = config_path.with_suffix(config_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"theme": str(name)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(config_path)
    return config_path
