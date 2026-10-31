"""Ensure the Theme chooser uses the exact requested order."""
import unittest
from types import SimpleNamespace

from textual.theme import BUILTIN_THEMES

from mdir_u.theme import MDIR_THEME, NORTON_THEME, OLD_M_THEME, THEME_NAME
from mdir_u.theme_order import THEME_ORDER, OrderedThemeProvider
from mdir_u.theme_settings import load_theme_name, save_theme_name


class ThemeOrderTests(unittest.TestCase):
    def test_exact_24_theme_order_and_default(self):
        self.assertEqual(THEME_NAME, "mDir theme (basic)")
        self.assertEqual(len(THEME_ORDER), 24)
        self.assertEqual(THEME_ORDER[:3], (
            "mDir theme (basic)", "Old-MDIR", "Norton Commander",
        ))
        self.assertEqual(THEME_ORDER[-1], "tokyo-night")
        self.assertEqual(
            set(THEME_ORDER), set(BUILTIN_THEMES)
            | {MDIR_THEME.name, OLD_M_THEME.name, NORTON_THEME.name},
        )

    def test_provider_preserves_order_and_callbacks(self):
        themes = dict(BUILTIN_THEMES)
        themes.update((x.name, x) for x in (MDIR_THEME, OLD_M_THEME, NORTON_THEME))
        app = SimpleNamespace(available_themes=themes, theme=None)
        dummy = SimpleNamespace(app=app)
        commands = OrderedThemeProvider.commands.fget(dummy)
        self.assertEqual([name for name, _ in commands], list(THEME_ORDER))
        commands[0][1]()
        self.assertEqual(app.theme, "mDir theme (basic)")
        commands[-1][1]()
        self.assertEqual(app.theme, "tokyo-night")

    def test_missing_theme_config_uses_basic(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "theme.json"
            self.assertEqual(load_theme_name(THEME_NAME, path), THEME_NAME)
            save_theme_name("mDir theme", path)
            self.assertEqual(load_theme_name(THEME_NAME, path), THEME_NAME)


if __name__ == "__main__":
    unittest.main()
