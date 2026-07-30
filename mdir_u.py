"""Direct launcher for MDIR-U."""

from __future__ import annotations

import sys

from mdir_u.app import MDirApp, self_check
from mdir_u.window import center_terminal_window


MDirU = MDirApp


def main() -> int:
    if "--check" in sys.argv:
        return self_check()
    center_terminal_window()
    MDirApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
