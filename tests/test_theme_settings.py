from pathlib import Path
import tempfile
import unittest

from mdir_u.theme_settings import load_theme_name, save_theme_name


class ThemeSettingsTests(unittest.TestCase):
    def test_missing_file_uses_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "theme.json"
            self.assertEqual(load_theme_name("mDir theme", path), "mDir theme")

    def test_save_and_load_theme(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "theme.json"
            save_theme_name("old_M_tema", path)
            self.assertEqual(load_theme_name("mDir theme", path), "old_M_tema")
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_invalid_setting_uses_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "theme.json"
            path.write_text('{"theme": 3}', encoding="utf-8")
            self.assertEqual(load_theme_name("mDir theme", path), "mDir theme")


if __name__ == "__main__":
    unittest.main()
