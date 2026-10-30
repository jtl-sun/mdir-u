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
            self.assertEqual(load_theme_name("mDir theme", path), "Old-MDIR")
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_new_name_is_preserved_without_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "theme.json"
            save_theme_name("Old-MDIR", path)
            self.assertEqual(load_theme_name("mDir theme", path), "Old-MDIR")

    def test_invalid_setting_uses_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "theme.json"
            path.write_text('{"theme": 3}', encoding="utf-8")
            self.assertEqual(load_theme_name("mDir theme", path), "mDir theme")


if __name__ == "__main__":
    unittest.main()
