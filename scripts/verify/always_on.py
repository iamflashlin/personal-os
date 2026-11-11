"""Check the always-on Hub (ADR 0021) on this PC.

    uv run python scripts/verify/always_on.py [--expect-task] [--data-dir D:\\dev\\personal-os-data]

Checks: /health answers on 127.0.0.1:8765 and the page loads; the supervisor log says the
Hub runs from the runtime copy with the expected data dir; after the Hub process is killed
the supervisor brings it back within 60 s. With --expect-task, also checks that the
"PersonalOS Hub" scheduled task exists with a logon trigger. Exit code 0 only if all pass.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import httpx

HUB = "http://127.0.0.1:8765"


class CheckFailed(Exception):
    pass


def check(ok: bool, message: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {message}", flush=True)
    if not ok:
        raise CheckFailed(message)


def healthy() -> bool:
    try:
        return httpx.get(f"{HUB}/health", timeout=2).json().get("status") == "ok"
    except (httpx.HTTPError, ValueError):
        return False


def wait_until(condition: object, seconds: float) -> float | None:
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        if condition():  # type: ignore[operator]
            return time.monotonic() - started
        time.sleep(1)
    return None


def powershell(command: str) -> str:
    done = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return done.stdout.strip()


def listener_path() -> str:
    """The executable of the process listening on 127.0.0.1:8765, or ''."""
    return powershell(
        "$c = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue"
        " | Select-Object -First 1; if ($c) { (Get-CimInstance Win32_Process -Filter "
        '"ProcessId = $($c.OwningProcess)").ExecutablePath }'
    )


def supervisor_log(data_dir: Path) -> str:
    logs = data_dir / "logs"
    return "".join(
        (logs / name).read_text(encoding="utf-8", errors="replace")
        for name in ("hub.log.1", "hub.log")
        if (logs / name).exists()
    )


def run(data_dir: Path, copy_dir: Path, expect_task: bool) -> None:
    up = wait_until(healthy, 60)
    check(up is not None, "GET /health answers ok on 127.0.0.1:8765")
    page = httpx.get(f"{HUB}/", timeout=5)
    check(page.status_code == 200 and "<div id=" in page.text, "the web page loads at /")
    served_by = listener_path()
    check(
        served_by.lower().startswith(str(copy_dir).lower() + "\\"),
        f"the Hub on 8765 runs from the runtime copy ({served_by})",
    )

    starts = [line for line in supervisor_log(data_dir).splitlines() if "starting Hub" in line]
    check(bool(starts), "the supervisor started the Hub")
    check(f"data_dir={data_dir}" in starts[-1], f"with data in {data_dir}")
    check((data_dir / "hub.sqlite").is_file(), "the database lives in the data folder")
    runs = sorted((data_dir / "logs").glob("hub-run-*-err.log"))
    check(
        bool(runs) and "Uvicorn running" in runs[-1].read_text(encoding="utf-8", errors="replace"),
        "the Hub's own output is written while it runs",
    )

    pid = int((data_dir / "hub.pid").read_text().strip())
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
    down = wait_until(lambda: not healthy(), 15)
    check(down is not None, "killing the Hub process stops it")
    back = wait_until(healthy, 60)
    check(back is not None, f"the supervisor brought it back ({back or 0:.0f} s)")
    new_pid = int((data_dir / "hub.pid").read_text().strip())
    check(new_pid != pid, "it is a new Hub process")
    exited = [line for line in supervisor_log(data_dir).splitlines() if "exited with code" in line]
    check(bool(exited) and "code ;" not in exited[-1], f"the exit code is recorded ({exited[-1:]})")

    if expect_task:
        triggers = powershell(
            "(Get-ScheduledTask -TaskName 'PersonalOS Hub').Triggers | "
            "ForEach-Object { $_.CimClass.CimClassName }"
        )
        check("MSFT_TaskLogonTrigger" in triggers, "the scheduled task starts it at logon")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(r"D:\dev\personal-os-data"))
    parser.add_argument("--copy-dir", type=Path, default=Path(r"D:\dev\personal-os-run"))
    parser.add_argument("--expect-task", action="store_true")
    args = parser.parse_args()
    try:
        run(args.data_dir, args.copy_dir, args.expect_task)
    except CheckFailed as exc:
        print(f"\nRESULT: FAIL ({exc})")
        return 1
    print("\nRESULT: PASS (always_on)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
