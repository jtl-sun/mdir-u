from __future__ import annotations

import os
from functools import lru_cache


def _is_korean_character(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x1100 <= codepoint <= 0x11FF  # Hangul Jamo
        or 0x3130 <= codepoint <= 0x318F  # Compatibility Jamo
        or 0xA960 <= codepoint <= 0xA97F  # Jamo Extended-A
        or 0xAC00 <= codepoint <= 0xD7A3  # Hangul syllables
        or 0xD7B0 <= codepoint <= 0xD7FF  # Jamo Extended-B
    )


def enable_windows_korean_width_compatibility() -> bool:
    """Optionally use one terminal cell for Hangul on unusual terminals.

    Windows Terminal normally renders Hangul in two cells, which is also the
    Unicode width used by Rich/Textual. Forcing a one-cell width breaks the IME
    composition cursor and may visually reorder Korean syllables.

    The non-standard one-cell mode therefore requires the explicit setting
    MDIR_KOREAN_WIDTH=1. The default is the safe, standard two-cell mode.
    """
    requested_width = os.environ.get("MDIR_KOREAN_WIDTH", "2").strip()
    if os.name != "nt" or requested_width != "1":
        return False

    import rich.cells as rich_cells

    original_get_size = rich_cells.get_character_cell_size
    if getattr(original_get_size, "_mdir_korean_compat", False):
        return True

    @lru_cache(maxsize=4096)
    def get_character_cell_size(
        character: str, unicode_version: str = "auto"
    ) -> int:
        if len(character) == 1 and _is_korean_character(character):
            return 1
        return original_get_size(character, unicode_version)

    get_character_cell_size._mdir_korean_compat = True  # type: ignore[attr-defined]
    rich_cells.get_character_cell_size = get_character_cell_size
    rich_cells.cached_cell_len.cache_clear()

    # Input imported this function directly, so update that reference too.
    try:
        import textual.widgets._input as textual_input

        textual_input.get_character_cell_size = get_character_cell_size
    except ImportError:
        pass

    return True
