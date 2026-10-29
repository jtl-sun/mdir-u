"""F6 rename/move planning and footer visibility regression tests."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path

from mdir_u.core import MDir as LegacyApp
from mdir_u.ui.renmov import default_rename_move_input, plan_rename_move


class RenameMoveTests(unittest.TestCase):
    def test_footer_hides_unneeded_items_but_keeps_bindings(self):
        bindings = {b.key: b for b in LegacyApp.BINDINGS}
        for key in ("backspace", "space", "f2"):
            self.assertFalse(bindings[key].show)
        self.assertTrue(bindings["f6"].show)
        self.assertEqual(bindings["f6"].description, "RenMov")

    def test_f6_default_for_one_or_many(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            src, dst = home / "source", home / "destination"
            src.mkdir()
            dst.mkdir()
            one = src / "sample.design.pdf"
            two = src / "other.pdf"
            one.touch()
            two.touch()
            self.assertEqual(
                default_rename_move_input([one], dst), str(dst / one.name)
            )
            self.assertEqual(
                default_rename_move_input([one, two], dst), str(dst)
            )
            initial = default_rename_move_input([one], dst)
            plan = plan_rename_move(
                initial, [one], src, default_target=Path(initial)
            )
            self.assertEqual(plan.mode, "move")
            self.assertEqual(plan.destination, dst.resolve(strict=False))
            self.assertIsNone(plan.new_name)
            changed = plan_rename_move(str(dst / "updated.pdf"), [one], src)
            self.assertEqual(changed.new_name, "updated.pdf")

    def test_existing_target_directory_is_not_nesting_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            src, dst = home / "src", home / "dst"
            src.mkdir()
            dst.mkdir()
            one = src / "Samples"
            one.mkdir()
            (dst / "Samples").mkdir()
            initial = default_rename_move_input([one], dst)
            plan = plan_rename_move(
                initial, [one], src, default_target=Path(initial)
            )
            self.assertEqual(plan.destination, dst.resolve(strict=False))
            self.assertEqual(plan.target, (dst / "Samples").resolve(strict=False))

    def test_single_name_rename(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root)
            source = p / "old.txt"
            source.write_text("keep")
            result = plan_rename_move("new.txt", [source], p)
            self.assertEqual(result.mode, "rename")
            self.assertEqual(result.target, (p / "new.txt").resolve(strict=False))
            self.assertEqual(source.read_text(), "keep")

    def test_default_move_and_explicit_new_name(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root)
            a = p / "left"
            b = p / "right"
            a.mkdir()
            b.mkdir()
            source = a / "old.txt"
            source.write_text("data")
            planned = plan_rename_move(str(b), [source], a)
            self.assertEqual(planned.mode, "move")
            self.assertEqual(planned.destination, b.resolve(strict=False))
            self.assertIsNone(planned.new_name)
            planned = plan_rename_move(str(b / "new.txt"), [source], a)
            self.assertEqual(planned.new_name, "new.txt")

    def test_multiple_only_existing_folder_and_no_self_move(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root)
            a = p / "a"
            b = p / "b"
            a.mkdir()
            b.mkdir()
            source = a / "one.txt"
            other = a / "two.txt"
            source.touch()
            other.touch()
            with self.assertRaises(ValueError):
                plan_rename_move("new.txt", [source, other], a)
            self.assertEqual(plan_rename_move(str(b), [source, other], a).mode, "move")
            sub = a / "inside"
            sub.mkdir()
            with self.assertRaises(ValueError):
                plan_rename_move(str(sub), [a], p)

if __name__ == "__main__":
    unittest.main()
