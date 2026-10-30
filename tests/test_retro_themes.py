"""Ubuntu theme parity: active-pane focus, classic colors, selection contrast."""
import unittest
from mdir_u.theme import (THEME_NAME, MDIR_THEME, OLD_M_THEME,
    NORTON_THEME, OLD_M_THEME_NAME, NORTON_THEME_NAME,
    selection_colors, install_file_colors)

class RetroThemeTests(unittest.TestCase):
    def tearDown(self):
        install_file_colors(MDIR_THEME)

    def test_registered_colors(self):
        self.assertEqual(MDIR_THEME.name, THEME_NAME)
        self.assertEqual(OLD_M_THEME_NAME, "Old-MDIR")
        self.assertEqual(OLD_M_THEME.name, OLD_M_THEME_NAME)
        self.assertEqual(OLD_M_THEME.background, "#000000")
        self.assertEqual(NORTON_THEME.name, NORTON_THEME_NAME)
        self.assertEqual(NORTON_THEME.panel, "#0000aa")

    def test_selected_row_active_is_more_vivid(self):
        for theme, active, inactive in (
            (MDIR_THEME, "#159bb8", "#364953"),
            (OLD_M_THEME, "#ff5a61", "#99484d"),
            (NORTON_THEME, "#55ffff", "#315fc2"),
        ):
            with self.subTest(theme=theme.name):
                install_file_colors(theme)
                self.assertEqual(selection_colors(active=True)[0], active)
                self.assertEqual(selection_colors(active=False)[0], inactive)
                self.assertNotEqual(active, inactive)

if __name__ == "__main__":
    unittest.main()
