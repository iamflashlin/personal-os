# pyright: reportMissingImports=false, reportAttributeAccessIssue=false
# (Windows-only APIs; the module is skipped elsewhere)
"""WindowsAdapter against a window this test creates itself (ADR 0002: touch only our own)."""

import os
import sys
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows desktop only")


@dataclass
class OwnWindow:
    title: str
    handle: int
    closed: list[bool] = field(default_factory=list[bool])

    def pump(self, seconds: float) -> None:
        import win32gui

        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not self.closed:
            win32gui.PumpWaitingMessages()
            time.sleep(0.02)


@pytest.fixture
def own_window() -> Iterator[OwnWindow]:
    import win32api
    import win32con
    import win32gui

    title = f"pos-adapter-test-{uuid.uuid4().hex[:8]}"
    window = OwnWindow(title=title, handle=0)

    def wndproc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        if msg == win32con.WM_CLOSE:
            window.closed.append(True)
            win32gui.DestroyWindow(hwnd)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    instance = win32api.GetModuleHandle(None)
    cls = win32gui.WNDCLASS()
    # pywin32's stubs declare these as read-only properties; at runtime they are settable.
    cls.lpfnWndProc = wndproc  # pyright: ignore[reportAttributeAccessIssue]
    cls.lpszClassName = f"pos-test-{uuid.uuid4().hex[:8]}"  # pyright: ignore[reportAttributeAccessIssue]
    cls.hInstance = instance  # pyright: ignore[reportAttributeAccessIssue]
    atom = win32gui.RegisterClass(cls)
    window.handle = win32gui.CreateWindow(
        atom, title, win32con.WS_OVERLAPPEDWINDOW, 40, 40, 320, 200, 0, 0, instance, None
    )
    win32gui.ShowWindow(window.handle, win32con.SW_SHOWNOACTIVATE)  # never takes focus
    win32gui.PumpWaitingMessages()
    yield window
    if win32gui.IsWindow(window.handle):
        win32gui.DestroyWindow(window.handle)
    win32gui.UnregisterClass(atom, instance)


def test_load_controller_picks_the_windows_adapter() -> None:
    from apps.desktop_agent.controller import load_controller
    from apps.desktop_agent.windows_adapter import WindowsAdapter

    assert isinstance(load_controller(), WindowsAdapter)


def test_finds_a_window_by_title_without_focusing_it(own_window: OwnWindow) -> None:
    from apps.desktop_agent.windows_adapter import WindowsAdapter

    adapter = WindowsAdapter()
    window = adapter.wait_for_window(own_window.title, 5)
    assert window is not None
    assert (window.title, window.handle, window.pid) == (
        own_window.title,
        own_window.handle,
        os.getpid(),
    )
    assert not adapter.is_foreground(window)


def test_a_missing_window_returns_none_after_the_timeout() -> None:
    from apps.desktop_agent.windows_adapter import WindowsAdapter

    started = time.monotonic()
    assert WindowsAdapter().wait_for_window(f"absent-{uuid.uuid4().hex}", 0.3) is None
    assert time.monotonic() - started < 2


def test_close_sends_wm_close_to_that_window_only(own_window: OwnWindow) -> None:
    from apps.desktop_agent.windows_adapter import WindowsAdapter

    adapter = WindowsAdapter()
    window = adapter.wait_for_window(own_window.title, 5)
    assert window is not None
    adapter.close(window)
    own_window.pump(3)
    assert own_window.closed == [True]


def test_a_window_without_a_page_is_not_captured(own_window: OwnWindow) -> None:
    from apps.desktop_agent.windows_adapter import WindowsAdapter, capture_document

    window = WindowsAdapter().wait_for_window(own_window.title, 5)
    assert window is not None
    assert capture_document(window, own_window.title, document_timeout_s=0.5) is None


def test_which_finds_programs_on_path() -> None:
    from apps.desktop_agent.windows_adapter import WindowsAdapter

    assert WindowsAdapter().which("cmd") is not None
    assert WindowsAdapter().which(f"absent-{uuid.uuid4().hex}") is None


def test_a_window_that_already_showed_the_title_is_not_evidence(own_window: OwnWindow) -> None:
    import ctypes

    from apps.desktop_agent.windows_adapter import WindowsAdapter

    adapter = WindowsAdapter()
    adapter.spawn([sys.executable, "-c", "pass"])  # an action: snapshot of open windows
    assert adapter.wait_for_window(own_window.title, 0.5) is None
    ctypes.windll.user32.SetWindowTextW(own_window.handle, own_window.title + " - changed")
    window = adapter.wait_for_window(own_window.title, 2)
    assert window is not None and window.title.endswith("changed")
