"""Theme palette order shared by the Options > Theme picker.

Textual's stock ThemeProvider sorts alphabetically. Override its command
order while retaining fuzzy search and standard CommandPalette behavior.
"""
from __future__ import annotations

from functools import partial
from typing import Callable

from textual.theme import ThemeProvider

THEME_ORDER: tuple[str, ...] = (
    "mDir theme (basic)",
    "Old-MDIR",
    "Norton Commander",
    "ansi-dark",
    "ansi-light",
    "atom-one-dark",
    "atom-one-light",
    "catppuccin-frappe",
    "catppuccin-latte",
    "catppuccin-macchiato",
    "catppuccin-mocha",
    "dracula",
    "flexoki",
    "gruvbox",
    "monokai",
    "nord",
    "rose-pine",
    "rose-pine-dawn",
    "rose-pine-moon",
    "solarized-dark",
    "solarized-light",
    "textual-dark",
    "textual-light",
    "tokyo-night",
)


class OrderedThemeProvider(ThemeProvider):
    """Keep the three mDIR themes first, followed by selected built-in skins."""

    @property
    def commands(self) -> list[tuple[str, Callable[[], None]]]:
        themes = self.app.available_themes

        def set_theme(name: str) -> None:
            self.app.theme = name

        return [
            (name, partial(set_theme, name))
            for name in THEME_ORDER
            if name in themes
        ]
