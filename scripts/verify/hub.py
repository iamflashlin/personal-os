"""Real-behaviour checks against a running Hub process.

    uv run python scripts/verify/hub.py health

Each subcommand starts `python -m apps.hub` on a free 127.0.0.1 port with a fresh data
dir under `data/verify/` (gitignored, on the repo drive), talks to it over real HTTP,
then stops it. Exit code 0 only if every check passed.
"""

from __future__ import annotations

import argparse
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from apps.hub.core.db import DB_FILENAME, head_revision  # noqa: E402

STARTUP_TIMEOUT_S = 30.0


class CheckFailed(Exception):
    pass


def check(ok: bool, message: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {message}", flush=True)
    if not ok:
        raise CheckFailed(message)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def running_hub(data_dir: Path) -> Iterator[httpx.Client]:
    port = free_port()
    env = {**os.environ, "POS_DATA_DIR": str(data_dir), "POS_HUB_PORT": str(port)}
    env.pop("POS_HUB_HOST", None)
    log_path = data_dir.parent / "hub.log"
    print(f"start  python -m apps.hub  port={port}  data_dir={data_dir}", flush=True)
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "apps.hub"], cwd=ROOT, env=env, stdout=log, stderr=log
        )
    base_url = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(base_url=base_url, timeout=5.0) as client:
            deadline = time.monotonic() + STARTUP_TIMEOUT_S
            while True:
                if proc.poll() is not None:
                    check(False, f"hub process stayed up (exited {proc.returncode})")
                try:
                    client.get("/health")
                    break
                except httpx.TransportError:
                    if time.monotonic() > deadline:
                        check(False, f"hub answered within {STARTUP_TIMEOUT_S}s")
                    time.sleep(0.2)
            print(f"ready  {base_url}", flush=True)
            check(
                f"Uvicorn running on {base_url}" in log_path.read_text(encoding="utf-8"),
                "hub bound to loopback 127.0.0.1 by default",
            )
            yield client
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        print(f"stop   hub exit={proc.returncode}", flush=True)
        print("--- hub log ---")
        print(log_path.read_text(encoding="utf-8").rstrip())
        print("--- end hub log ---")


def verify_health(client: httpx.Client, data_dir: Path) -> None:
    response = client.get("/health")
    print(f"GET /health -> {response.status_code} {response.text}", flush=True)
    check(response.status_code == 200, "GET /health returns 200")
    body = response.json()
    check(body.get("status") == "ok", 'status is "ok"')
    check(body.get("schema_version") == head_revision(), f"schema_version == {head_revision()}")

    db = data_dir / DB_FILENAME
    check(db.is_file(), f"database file created at {db}")
    with sqlite3.connect(db) as conn:
        (mode,) = conn.execute("PRAGMA journal_mode").fetchone()
    check(mode == "wal", f"journal_mode is wal (got {mode})")


COMMANDS: dict[str, Callable[[httpx.Client, Path], None]] = {"health": verify_health}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS))
    args = parser.parse_args()

    scratch_root = ROOT / "data" / "verify"
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch_root, ignore_cleanup_errors=True) as tmp:
        data_dir = Path(tmp) / "data"
        try:
            with running_hub(data_dir) as client:
                COMMANDS[args.command](client, data_dir)
        except CheckFailed as exc:
            print(f"\nRESULT: FAIL ({exc})")
            return 1
    print(f"\nRESULT: PASS ({args.command})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
