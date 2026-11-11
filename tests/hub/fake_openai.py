"""A local OpenAI-compatible `/chat/completions` stub for the DeepSeek adapter."""

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class Reply:
    status: int = 200
    content: str | None = '{"answer": "ok"}'
    usage: dict[str, int] | None = field(
        default_factory=lambda: {
            "prompt_tokens": 120,
            "prompt_cache_hit_tokens": 20,
            "prompt_cache_miss_tokens": 100,
            "completion_tokens": 30,
        }
    )
    raw: bytes | None = None  # sent as-is instead of a built body
    prefix: bytes = b""  # e.g. keep-alive blank lines before the JSON
    delay_s: float = 0.0
    headers: dict[str, str] = field(default_factory=dict[str, str])  # e.g. Location


class FakeOpenAI:
    def __init__(self) -> None:
        self.replies: list[Reply] = []
        self.requests: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                stub.requests.append(json.loads(self.rfile.read(length)))
                stub.headers.append(dict(self.headers.items()))
                reply = stub.replies.pop(0) if stub.replies else Reply()
                if reply.delay_s:
                    threading.Event().wait(reply.delay_s)
                if reply.raw is not None:
                    body = reply.raw
                elif reply.status != 200:
                    body = json.dumps({"error": {"message": "nope"}}).encode()
                else:
                    body = json.dumps(
                        {
                            "id": "req-123",
                            "choices": [
                                {
                                    "message": {"role": "assistant", "content": reply.content},
                                    "finish_reason": "stop",
                                }
                            ],
                            "usage": reply.usage,
                        }
                    ).encode()
                body = reply.prefix + body
                self.send_response(reply.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                for name, value in reply.headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "FakeOpenAI":
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()
