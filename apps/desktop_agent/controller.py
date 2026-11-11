"""The only door to the desktop. Actions call these methods and nothing else.

The Windows implementation arrives in T-0008 as `apps.desktop_agent.windows_adapter`.
It is imported lazily, so the agent core runs (and is tested) on any platform.
"""

import importlib
import shutil
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class WindowInfo:
    title: str
    pid: int


class DesktopUnavailable(Exception):
    """This machine has no desktop adapter; the action needs the user."""


class DesktopController(Protocol):
    def open_url(self, url: str) -> None: ...

    def which(self, command: str) -> str | None: ...

    def spawn(self, argv: list[str]) -> None:
        """Start a process with an argument list, never through a shell."""
        ...

    def wait_for_window(self, title_contains: str, timeout_s: float) -> WindowInfo | None:
        """Poll top-level window titles; never focuses or brings a window forward."""
        ...


class UnsupportedController:
    """Used when no adapter exists for this platform yet: every desktop call refuses."""

    def open_url(self, url: str) -> None:
        raise DesktopUnavailable("no desktop adapter on this machine yet")

    def which(self, command: str) -> str | None:
        return shutil.which(command)

    def spawn(self, argv: list[str]) -> None:
        raise DesktopUnavailable("no desktop adapter on this machine yet")

    def wait_for_window(self, title_contains: str, timeout_s: float) -> WindowInfo | None:
        raise DesktopUnavailable("no desktop adapter on this machine yet")


def load_controller() -> DesktopController:
    name = "apps.desktop_agent.windows_adapter"
    try:
        module = importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise  # the adapter exists but one of its own imports is missing
        return UnsupportedController()
    return module.WindowsAdapter()
