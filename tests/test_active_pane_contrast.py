"""mDir default theme should keep the active file list darker."""
import inspect
import unittest

from mdir_u.app import MDirApp
from mdir_u.theme import MDIR_THEME_CSS, OLD_M_THEME, NORTON_THEME


class ActivePaneContrastTests(unittest.TestCase):
    def test_modern_only_backgrounds(self):
        self.assertIn("FilePane.skin-modern.active DataTable", MDIR_THEME_CSS)
        self.assertIn("FilePane.skin-modern DataTable:focus", MDIR_THEME_CSS)
        self.assertIn("background: #191919;", MDIR_THEME_CSS)
        self.assertIn("background: #292929;", MDIR_THEME_CSS)
        self.assertIn('pane.set_class(self.theme == THEME_NAME, "skin-modern")',
                      inspect.getsource(MDirApp._sync_skin_classes))

    def test_retro_palettes_unchanged(self):
        self.assertEqual(OLD_M_THEME.background, "#000000")
        self.assertEqual(NORTON_THEME.panel, "#0000aa")

if __name__ == "__main__":
    unittest.main()
