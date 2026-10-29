from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OldMThemeStructureTests(unittest.TestCase):
    def test_retro_theme_registered_and_default_preserved(self):
        theme = (ROOT / "mdir_u" / "theme.py").read_text(encoding="utf-8")
        app = (ROOT / "mdir_u" / "app.py").read_text(encoding="utf-8")
        self.assertIn('THEME_NAME = "mDir theme"', theme)
        self.assertIn('OLD_M_THEME_NAME = "old_M_tema"', theme)
        self.assertIn('name=OLD_M_THEME_NAME', theme)
        self.assertIn('self.register_theme(OLD_M_THEME)', app)
        self.assertIn('def get_theme_variable_defaults', app)
        self.assertIn('preferred_theme = load_theme_name(THEME_NAME)', app)
        self.assertIn('else THEME_NAME', app)

    def test_classic_extension_colors_are_theme_local(self):
        theme = (ROOT / "mdir_u" / "theme.py").read_text(encoding="utf-8")
        for extension, color in (
            (".exe", "#55ff55"),
            (".com", "#55ffff"),
            (".bat", "#ffff55"),
            (".ps1", "#ff55ff"),
        ):
            self.assertIn(f'"{extension}": "{color}"', theme)
        self.assertIn('if theme.name == OLD_M_THEME_NAME', theme)

    def test_version_stays_in_v2_line(self):
        version_text = (ROOT / "mdir_u" / "__init__.py").read_text(encoding="utf-8")
        match = re.search(r'__version__ = "([^"]+)"', version_text)
        self.assertIsNotNone(match)
        self.assertTrue(match.group(1).startswith("2."))
        self.assertEqual(match.group(1), "2.26.41")


if __name__ == "__main__":
    unittest.main()
