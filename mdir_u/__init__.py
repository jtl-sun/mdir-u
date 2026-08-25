"""MDIR-U: a fast dual-pane Ubuntu and universal terminal file manager."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import MDirApp

__all__ = ["MDirApp"]
__version__ = "2.23.15"


def __getattr__(name: str):
    if name == "MDirApp":
        from .app import MDirApp

        return MDirApp
    raise AttributeError(name)
