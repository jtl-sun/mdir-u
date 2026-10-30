"""Verify full-surface focus contrast across all themed pane skins."""
import unittest
from mdir_u.theme import MDIR_THEME_CSS, OLD_M_THEME_NAME


class PaneContrastTests(unittest.TestCase):
    def test_retro_name_and_palette_selectors(self):
        self.assertEqual(OLD_M_THEME_NAME, "Old-MDIR")
        css = MDIR_THEME_CSS
        # Earlier generic CSS has Old-MDIR/Norton selectors too; inspect the
        # dedicated active-vs-passive section to validate its final overrides.
        modern, classic = css.split(
            "/* Strong active/quiet passive distinction", 1,
        )
        for skin, dim, vivid in (
            ("skin-modern", "#292929", "#191919"),
            ("skin-original", "#202020", "#000000"),
            ("skin-norton", "#171752", "#0000aa"),
            ("skin-light", "#f0f0f0", "#e0e0e0"),
        ):
            with self.subTest(skin=skin):
                section = modern if skin == "skin-modern" else classic
                passive = section.index(f"FilePane.{skin},")
                focused = section.index(f"FilePane.{skin}.active,")
                self.assertIn("background: "+dim+";", section[passive:focused])
                self.assertIn("background: "+vivid+";", section[focused:])

    def test_muted_passive_and_full_contrast_active(self):
        self.assertIn("text-opacity: 72%;", MDIR_THEME_CSS)
        self.assertIn("text-opacity: 100%;", MDIR_THEME_CSS)


if __name__ == "__main__":
    unittest.main()
