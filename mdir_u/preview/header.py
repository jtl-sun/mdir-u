from __future__ import annotations

from rich.text import Text


PREVIEW_BADGE_TEXT = "PREVIEW"
PREVIEW_BADGE_BACKGROUND = "#f59e0b"
PREVIEW_BADGE_FOREGROUND = "#101010"
PREVIEW_FILENAME_COLOR = "default"


def rich_preview_title(filename: str = "") -> Text:
    """Build the emphasized Preview badge followed by a file name."""
    title = Text()
    title.append(
        f" {PREVIEW_BADGE_TEXT} ",
        style=(
            f"bold {PREVIEW_BADGE_FOREGROUND} "
            f"on {PREVIEW_BADGE_BACKGROUND}"
        ),
    )
    if filename:
        title.append("  ")
        title.append(filename, style=f"bold {PREVIEW_FILENAME_COLOR}")
    return title
