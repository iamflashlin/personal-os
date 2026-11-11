# pyright: reportMissingImports=false, reportAttributeAccessIssue=false
"""Spike R2/R3 (ADR 0014): can we capture our own browser page without focusing it?

    uv run python scripts/verify/spike_printwindow.py [--out spike.png]

Serves a page with a unique title on 127.0.0.1, opens it with the default browser, finds
the browser window by that title, captures the window with PrintWindow
(PW_RENDERFULLCONTENT) into memory, crops to the page's UIA Document control, and checks
that the crop is our page (its solid background colour), not blank or another window.
The page then tries to close itself. Nothing is focused, typed or clicked.
Exit 0 if the crop is our page.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from apps.desktop_agent.windows_adapter import WindowsAdapter, capture_document  # noqa: E402

PAGE_RGB = (17, 136, 68)


class MarkerPage:
    """A one-page server on 127.0.0.1 whose title is unique to this run.

    The page reports each real load with a POST to /beacon (a GET for a favicon or a
    prefetch is not counted), and asks the browser to close it after `close_after_s`.
    """

    def __init__(self, background: tuple[int, int, int], close_after_s: float) -> None:
        self.title = f"POS-verify-{uuid.uuid4().hex[:10]}"
        self.loads = 0
        colour = "#{:02x}{:02x}{:02x}".format(*background)
        html = (
            f"<!doctype html><html><head><meta charset='utf-8'><title>{self.title}</title>"
            f"<style>html,body{{margin:0;height:100%;background:{colour}}}</style></head>"
            "<body><script>fetch('/beacon',{method:'POST'});"
            f"setTimeout(function(){{window.close()}},{int(close_after_s * 1000)});"
            "</script></body></html>"
        ).encode()
        page = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                body = html if self.path == "/" else b""
                self.send_response(200 if body else 404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                if self.path == "/beacon":
                    page.loads += 1
                self.send_response(204)
                self.end_headers()

            def log_message(self, format: str, *args: Any) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}/"

    def __enter__(self) -> MarkerPage:
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "data" / "verify" / "spike_printwindow.png"))
    args = parser.parse_args()
    if sys.platform != "win32":
        print("SKIP  Windows only")
        return 0

    desktop = WindowsAdapter()
    ok = True
    with MarkerPage(background=PAGE_RGB, close_after_s=15) as page:
        print(f"page   {page.url}  title={page.title}", flush=True)
        desktop.open_url(page.url)
        window = desktop.wait_for_window(page.title, 20)
        print(f"window {window}", flush=True)
        if window is None:
            print("FAIL  no window with our title appeared")
            return 1
        print(f"info   foreground at capture: {desktop.is_foreground(window)}", flush=True)
        image = capture_document(window, page.title)
        if image is None:
            print("FAIL  PrintWindow / UIA Document capture returned nothing")
            return 1
        share = page_colour_share(image)
        print(f"crop   {image.size[0]}x{image.size[1]}  page colour share {share:.0%}")
        if share > 0.6:
            # Saved only once we know it is our page (ADR 0014 D5).
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            image.save(args.out)
        else:
            ok = False
        print(f"{'PASS' if share > 0.6 else 'FAIL'}  the crop shows only our page")

        covered = capture_while_covered(window, page.title)
        print(
            f"{'PASS' if covered > 0.6 else 'FAIL'}  captured while our own window covered it "
            f"({covered:.0%} page colour)"
        )
        ok = ok and covered > 0.6
        print(f"beacon page loads counted: {page.loads}")
        gone = wait_gone(desktop, page.title, 20)
        print(f"info   the page closed itself: {gone}")
    return 0 if ok else 1


def capture_while_covered(window: Any, title: str) -> float:
    """R2: put a window of our own (never activated) over the page, then capture."""
    import win32con
    import win32gui

    left, top, right, bottom = win32gui.GetWindowRect(window.handle)
    cover = win32gui.CreateWindowEx(
        win32con.WS_EX_TOPMOST | win32con.WS_EX_NOACTIVATE | win32con.WS_EX_TOOLWINDOW,
        "STATIC",
        "pos-spike-cover",
        win32con.WS_POPUP | win32con.WS_VISIBLE,
        left,
        top,
        right - left,
        bottom - top,
        0,
        0,
        0,
        None,
    )
    try:
        win32gui.PumpWaitingMessages()
        time.sleep(0.5)
        image = capture_document(window, title)
        return 0.0 if image is None else page_colour_share(image)
    finally:
        win32gui.DestroyWindow(cover)


def page_colour_share(image: object) -> float:
    rgb = image.convert("RGB")  # type: ignore[attr-defined]
    total = rgb.width * rgb.height
    colours = rgb.getcolors(total) or []
    near = sum(
        n for n, c in colours if all(abs(a - b) <= 12 for a, b in zip(c, PAGE_RGB, strict=True))
    )
    return near / max(total, 1)


def wait_gone(desktop: WindowsAdapter, title: str, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if desktop.wait_for_window(title, 0.1) is None:
            return True
        time.sleep(0.5)
    return False


if __name__ == "__main__":
    raise SystemExit(main())
