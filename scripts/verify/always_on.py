"""Check the always-on Hub (ADR 0021) on this PC.

    uv run python scripts/verify/always_on.py [--expect-task] [--data-dir D:\\dev\\personal-os-data]

Checks: /health answers on 127.0.0.1:8765 and the page loads; the supervisor log says the
Hub runs from the runtime copy with the expected data dir; after the Hub process is killed
the supervisor brings it back within 60 s. With --expect-task, also checks that the
"PersonalOS Hub" scheduled task exists with a logon trigger that repeats every 5 minutes.
With --watchdog, also kills the supervisor and the Hub and waits (up to 6 min) for the task
to start them again. Exit code 0 only if all pass.
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


def listener_paths() -> list[str]:
    """Executables of the process listening on 127.0.0.1:8765 and of its parent.

    On Windows a venv's python.exe is a launcher: the interpreter that owns the socket is
    its child and runs from the base Python install, so the parent identifies the copy.
    """
    out = powershell(
        "$c = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue"
        " | Select-Object -First 1; if ($c) { $p = Get-CimInstance Win32_Process -Filter "
        '"ProcessId = $($c.OwningProcess)"; $p.ExecutablePath; (Get-CimInstance '
        'Win32_Process -Filter "ProcessId = $($p.ParentProcessId)").ExecutablePath }'
    )
    return [line.strip() for line in out.splitlines() if line.strip()]


def supervisor_log(data_dir: Path) -> str:
    logs = data_dir / "logs"
    return "".join(
        (logs / name).read_text(encoding="utf-8", errors="replace")
        for name in ("hub.log.1", "hub.log")
        if (logs / name).exists()
    )


def supervisors(copy_dir: Path) -> list[int]:
    """Process ids of run-hub.ps1 supervisors for this copy, never the listing shell itself."""
    out = powershell(
        "Get-CimInstance Win32_Process -Filter \"Name = 'powershell.exe' OR Name = 'pwsh.exe'\" "
        "| Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -like '*run-hub.ps1*' "
        f"-and $_.CommandLine -like '*{copy_dir}*' }} | ForEach-Object {{ $_.ProcessId }}"
    )
    return [int(line) for line in out.split() if line.isdigit()]


def supervisor_starts(data_dir: Path) -> list[str]:
    return [line for line in supervisor_log(data_dir).splitlines() if "supervisor started" in line]


def run(data_dir: Path, copy_dir: Path, expect_task: bool, watchdog: bool) -> None:
    up = wait_until(healthy, 60)
    check(up is not None, "GET /health answers ok on 127.0.0.1:8765")
    page = httpx.get(f"{HUB}/", timeout=5)
    check(page.status_code == 200 and "<div id=" in page.text, "the web page loads at /")
    served_by = listener_paths()
    check(
        any(path.lower().startswith(str(copy_dir).lower() + "\\") for path in served_by),
        f"the Hub on 8765 runs from the runtime copy ({' <- '.join(served_by)})",
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
        repeat = powershell(
            "$r = (Get-ScheduledTask -TaskName 'PersonalOS Hub').Triggers[0].Repetition; "
            '"$($r.Interval)|$($r.Duration)"'
        )
        interval, _, duration = repeat.partition("|")
        check(interval == "PT5M", f"and checks every 5 minutes that it runs ({interval!r})")
        check(duration == "", f"forever: the repetition has no end ({duration!r})")

    if watchdog:
        before = supervisors(copy_dir)
        check(len(before) == 1, f"one supervisor runs from the copy (pids {before})")
        starts_before = supervisor_starts(data_dir)
        subprocess.run(["taskkill", "/PID", str(before[0]), "/F"], capture_output=True, check=False)
        gone = wait_until(lambda: before[0] not in supervisors(copy_dir), 15)
        check(gone is not None, f"the supervisor (pid {before[0]}) is killed")
        pid = int((data_dir / "hub.pid").read_text().strip())
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
        down = wait_until(lambda: not healthy(), 15)
        check(down is not None, "and the Hub is down with nobody to restart it")
        back = wait_until(healthy, 6 * 60)
        check(back is not None, f"the watchdog brought it back ({back or 0:.0f} s, at most 5 min)")
        after = supervisors(copy_dir)
        check(
            len(after) == 1 and after[0] != before[0],
            f"by a new supervisor (pid {after}, was {before[0]})",
        )
        new = supervisor_starts(data_dir)[len(starts_before) :]
        check(
            any(f"(pid {after[0]})" in line for line in new),
            f"the supervisor log records that new start ({new[-1:]})",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(r"D:\dev\personal-os-data"))
    parser.add_argument("--copy-dir", type=Path, default=Path(r"D:\dev\personal-os-run"))
    parser.add_argument("--expect-task", action="store_true")
    parser.add_argument(
        "--watchdog", action="store_true", help="also kill the supervisor (up to 6 min)"
    )
    args = parser.parse_args()
    try:
        run(args.data_dir, args.copy_dir, args.expect_task, args.watchdog)
    except CheckFailed as exc:
        print(f"\nRESULT: FAIL ({exc})")
        return 1
    print("\nRESULT: PASS (always_on)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
