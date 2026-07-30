from __future__ import annotations

import sys

from .app import MDirApp, self_check
from .window import center_terminal_window


def main() -> int:
    if "--check" in sys.argv:
        return self_check()
    center_terminal_window()
    MDirApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
