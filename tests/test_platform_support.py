import unittest
from pathlib import Path

from mdir_u.ai.providers import PROVIDERS, ShellProvider
from mdir_u.platform_support import filesystem_usage_text, locations


class PlatformSupportTests(unittest.TestCase):
    def test_shell_provider_is_registered(self) -> None:
        self.assertIsInstance(PROVIDERS["shell"], ShellProvider)

    def test_shell_provider_uses_non_interactive_command(self) -> None:
        provider = ShellProvider()
        command = provider.build_command("printf hello", Path.cwd(), None)
        self.assertEqual(command[-2:], ["-lc", "printf hello"])

    def test_locations_include_home(self) -> None:
        self.assertTrue(any(item.label == "Home" for item in locations()))

    def test_filesystem_usage_has_path(self) -> None:
        self.assertIn(str(Path.cwd()), filesystem_usage_text(Path.cwd()))


if __name__ == "__main__":
    unittest.main()
