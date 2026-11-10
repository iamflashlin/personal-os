"""D0-05 spike: prove real GUI verification works on this Windows machine.

Creates a marker text file, opens it in Notepad, finds the window via pywinauto
(UIA backend) by the marker file name, screenshots only the document area,
closes the window, and confirms it is gone.

    uv run python scripts/verify/spike_notepad.py [--out .evidence/D0-05]

Privacy rules (ADR 0002):
- Refuse to run if any Notepad window is already open, so the window we close is
  one this script created. Win11 Notepad may restore previous tabs into it; closing
  the window closes those tabs too, but Notepad keeps them in its session.
- Capture only the text-document control, never the tab strip, title bar, window
  border or full screen: the tab strip can show the user's restored file names.

Exit codes: 0 all steps passed, 1 a step failed, 2 refused (Notepad already open).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if sys.platform != "win32":
    print("SKIP: Windows-only spike")
    raise SystemExit(0)

from PIL import ImageGrab
from pywinauto import Desktop

MARKER = "pos-spike-notepad"
TIMEOUT_S = 15.0


def notepad_windows() -> list[Any]:
    return Desktop(backend="uia").windows(class_name="Notepad")


def marker_windows() -> list[Any]:
    return [w for w in notepad_windows() if MARKER in w.window_text()]


def wait_for(predicate: Callable[[], bool], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.25)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=".evidence/D0-05")
    out = Path(parser.parse_args().out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {"started_at": datetime.now(UTC).isoformat(), "steps": {}}
    steps: dict[str, Any] = result["steps"]

    if notepad_windows():
        steps["refused"] = "a Notepad window is already open; close all Notepad windows and rerun"
        return finish(out, result, ok=False, code=2)

    marker_file = out / f"{MARKER}.txt"
    marker_file.write_text("Personal OS D0-05 spike. Safe to delete.\n", encoding="utf-8")

    # Win11's notepad.exe is a launcher stub that hands off to the packaged app,
    # so we track the window by title, not the PID we started.
    subprocess.Popen(["notepad.exe", str(marker_file)])
    steps["window_appeared"] = wait_for(lambda: bool(marker_windows()), TIMEOUT_S)
    if not steps["window_appeared"]:
        return finish(out, result, ok=False)

    if len(notepad_windows()) > 1:
        steps["error"] = "another Notepad window appeared during the run; not touching it"
        return finish(out, result, ok=False)

    win = marker_windows()[0]
    handle = win.handle
    title = win.window_text()
    steps["title"] = title
    steps["title_matches"] = MARKER in title and ("Notepad" in title or "记事本" in title)
    steps["tab_count"] = len(win.descendants(control_type="TabItem"))

    win.set_focus()
    time.sleep(0.5)
    docs = win.descendants(control_type="Document")
    steps["document_found"] = bool(docs)
    if docs:
        r = docs[0].rectangle()
        shot = out / "notepad.png"
        ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True).save(shot)
        steps["screenshot"] = shot.name
        steps["screenshot_bytes"] = shot.stat().st_size

    win.close()

    def gone() -> bool:
        return all(w.handle != handle for w in notepad_windows())

    steps["closed"] = wait_for(gone, TIMEOUT_S)

    ok = bool(steps["title_matches"] and steps.get("screenshot_bytes", 0) > 0 and steps["closed"])
    return finish(out, result, ok=ok)


def finish(out: Path, result: dict[str, Any], *, ok: bool, code: int | None = None) -> int:
    result["ok"] = ok
    result["finished_at"] = datetime.now(UTC).isoformat()
    text = json.dumps(result, ensure_ascii=False, indent=2)
    (out / "result.json").write_text(text, encoding="utf-8")
    print(text)
    if code is not None:
        return code
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
