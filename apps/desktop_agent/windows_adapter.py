# pyright: reportMissingImports=false
# (pywin32, pywinauto and pillow are installed on Windows only; elsewhere this module
#  is never imported, see controller.load_controller)
"""DesktopController for Windows (ADR 0016).

Rules from ADR 0002 and HANDOFF §8.3: never focus, click, type into or close a window the
agent did not create; find windows by title without needing the foreground.
"""

import sys

if sys.platform != "win32":
    # load_controller() treats this as "no adapter here" and falls back (ADR 0015 §6).
    raise ModuleNotFoundError("the Windows adapter runs on Windows only", name=__name__)

import contextlib
import ctypes
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any

import win32gui
import win32process
import win32ui

from apps.desktop_agent.controller import WindowInfo

PW_RENDERFULLCONTENT = 2  # lets Chromium render a window that is covered or off-screen
DPI_AWARENESS_PER_MONITOR_V2 = -4


@dataclass(frozen=True)
class WindowsWindow(WindowInfo):
    handle: int = 0


def _windows() -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []

    def visit(hwnd: int, _extra: Any) -> bool:
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                found.append((hwnd, title))
        return True

    win32gui.EnumWindows(visit, None)
    return found


class WindowsAdapter:
    def __init__(self) -> None:
        # (window, title) pairs that existed before our last action. A window already
        # showing the expected title is not evidence that our action did anything.
        self._before: set[tuple[int, str]] = set()

    def _remember_windows(self) -> None:
        self._before = set(_windows())

    def open_url(self, url: str) -> None:
        self._remember_windows()
        # The default browser decides tab or window; we never bring it forward ourselves.
        os.startfile(url)  # type: ignore[attr-defined]  # Windows only

    def which(self, command: str) -> str | None:
        return shutil.which(command)

    def spawn(self, argv: list[str]) -> None:
        self._remember_windows()
        subprocess.Popen(argv, close_fds=True)  # an argument list, never shell=True

    def wait_for_window(self, title_contains: str, timeout_s: float) -> WindowsWindow | None:
        """A window whose title contains the text and that our last action produced:
        a new window, or an existing one whose title changed (a browser's new tab)."""
        deadline = time.monotonic() + timeout_s
        while True:
            for hwnd, title in _windows():
                if title_contains in title and (hwnd, title) not in self._before:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    return WindowsWindow(title=title, pid=pid, handle=hwnd)
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.25)

    def is_foreground(self, window: WindowsWindow) -> bool:
        return win32gui.GetForegroundWindow() == window.handle

    def close(self, window: WindowsWindow) -> None:
        """Ask a window to close (WM_CLOSE). Only for windows this program created."""
        win32gui.PostMessage(window.handle, 0x0010, 0, 0)


def _dpi_aware() -> None:
    # On a scaled display an unaware process sees virtualised window rectangles, while
    # UIA reports physical ones; both must be physical for the crop to line up.
    with contextlib.suppress(AttributeError, OSError):
        ctypes.windll.user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_PER_MONITOR_V2)


def _print_window(hwnd: int) -> Any:
    from PIL import Image

    if win32gui.IsIconic(hwnd):
        return None
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return None
    window_dc = win32gui.GetWindowDC(hwnd)
    source = memory = bitmap = previous = None
    try:
        source = win32ui.CreateDCFromHandle(window_dc)
        memory = source.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(source, width, height)
        previous = memory.SelectObject(bitmap)
        if not ctypes.windll.user32.PrintWindow(hwnd, memory.GetSafeHdc(), PW_RENDERFULLCONTENT):
            return None
        bits = bitmap.GetBitmapBits(True)
        return Image.frombuffer("RGB", (width, height), bits, "raw", "BGRX", 0, 1), (left, top)
    finally:
        # A bitmap cannot be deleted while selected, and a GetWindowDC DC is only released.
        if memory is not None:
            if previous is not None:
                memory.SelectObject(previous)
            memory.DeleteDC()
        if bitmap is not None:
            win32gui.DeleteObject(bitmap.GetHandle())
        # `source` only wraps window_dc and owns nothing; releasing window_dc is enough.
        win32gui.ReleaseDC(hwnd, window_dc)


def capture_document(
    window: WindowsWindow, expected_title: str, document_timeout_s: float = 5
) -> Any:
    """Our page only: the browser window captured in memory, cropped to the UIA Document
    named `expected_title` (ADR 0014 D5). No tab strip, address bar or other tabs.

    Returns a PIL image, or None if our page is not the one showing, before and after the
    capture. Nothing is written to disk here.
    """
    from pywinauto import Desktop

    _dpi_aware()
    browser = Desktop(backend="uia").window(handle=window.handle)
    document = browser.child_window(control_type="Document", title=expected_title)
    if not document.exists(timeout=document_timeout_s):
        return None
    rect = document.rectangle()
    captured = _print_window(window.handle)
    if captured is None:
        return None
    # The user may have switched tabs while we captured: then this is not our page.
    if expected_title not in win32gui.GetWindowText(window.handle):
        return None
    image, (left, top) = captured
    box = (rect.left - left, rect.top - top, rect.right - left, rect.bottom - top)
    if box[2] - box[0] < 10 or box[3] - box[1] < 10:
        return None
    return image.crop(box)
