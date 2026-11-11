"""A recording fake desktop and a real Hub served by uvicorn in a background thread."""

import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import uvicorn

from apps.desktop_agent.controller import WindowInfo
from apps.hub.core.settings import Settings
from apps.hub.main import create_app


@dataclass
class FakeDesktop:
    """Records every desktop call; windows appear unless `windows` is False."""

    code_path: str | None = "C:/Program Files/VS Code/bin/code.cmd"
    windows: bool = True
    delay_s: float = 0.0
    gate: threading.Event | None = None  # open_url waits for it, when set
    calls: list[tuple[str, ...]] = field(default_factory=list[tuple[str, ...]])
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _record(self, *call: str) -> None:
        with self._lock:
            self.calls.append(call)

    def open_url(self, url: str) -> None:
        self._record("open_url", url)
        time.sleep(self.delay_s)
        if self.gate is not None:
            assert self.gate.wait(15), "the test never opened the gate"

    def which(self, command: str) -> str | None:
        self._record("which", command)
        return self.code_path

    def spawn(self, argv: list[str]) -> None:
        self._record("spawn", *argv)

    def wait_for_window(self, title_contains: str, timeout_s: float) -> WindowInfo | None:
        self._record("wait_for_window", title_contains)
        return WindowInfo(title=f"{title_contains} - Window", pid=4242) if self.windows else None

    def count(self, name: str) -> int:
        return sum(1 for call in self.calls if call[0] == name)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class HubThread:
    """The real Hub app on 127.0.0.1:<port>; `restart()` keeps the port and the data."""

    def __init__(self, data_dir: Path, heartbeat_s: float = 1.0) -> None:
        self.settings = Settings(data_dir=data_dir, agent_heartbeat_s=heartbeat_s)
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        config = uvicorn.Config(
            create_app(self.settings, web_dist=None),
            host="127.0.0.1",
            port=self.port,
            ws="websockets-sansio",
            log_level="warning",
        )
        self._server = server = uvicorn.Server(config)
        self._thread = threading.Thread(target=server.run, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 15
        while not server.started:
            assert time.monotonic() < deadline, "in-process Hub did not start"
            time.sleep(0.02)

    def stop(self) -> None:
        assert self._server is not None and self._thread is not None
        self._server.should_exit = True
        self._thread.join(timeout=15)
        assert not self._thread.is_alive(), "in-process Hub did not stop"

    def restart(self) -> None:
        self.stop()
        self.start()
