from __future__ import annotations

import json
import secrets
import socket
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .i18n import _
from .models import LibraryItem


@dataclass(slots=True)
class TogetherState:
    queue: list[LibraryItem] = field(default_factory=list)
    index: int = 0
    position_ms: int = 0
    playing: bool = False
    revision: int = 0
    sent_at_ms: int = 0

    def to_payload(self) -> dict:
        return {
            "queue": [asdict(item) for item in self.queue],
            "index": self.index,
            "position_ms": self.position_ms,
            "playing": self.playing,
            "revision": self.revision,
            "sent_at_ms": self.sent_at_ms,
        }

    @classmethod
    def from_payload(cls, payload: dict) -> TogetherState:
        return cls(
            queue=[LibraryItem(**item) for item in payload.get("queue", [])],
            index=max(0, int(payload.get("index", 0))),
            position_ms=max(0, int(payload.get("position_ms", 0))),
            playing=bool(payload.get("playing", False)),
            revision=max(0, int(payload.get("revision", 0))),
            sent_at_ms=max(0, int(payload.get("sent_at_ms", 0))),
        )

    def corrected_position_ms(self, now_ms: int | None = None) -> int:
        now_ms = now_ms or int(time.time() * 1000)
        delay = max(0, min(10_000, now_ms - self.sent_at_ms)) if self.playing else 0
        return self.position_ms + delay


class TogetherHost:
    def __init__(self, address: str = "0.0.0.0", port: int = 0) -> None:
        self.token = secrets.token_urlsafe(18)
        self.state = TogetherState()
        self._lock = threading.Lock()
        host = self

        class Handler(BaseHTTPRequestHandler):
            def _authorized(self) -> bool:
                supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
                return secrets.compare_digest(supplied, host.token)

            def do_GET(self):
                if self.path != "/state" or not self._authorized():
                    self.send_error(403)
                    return
                with host._lock:
                    payload = json.dumps(host.state.to_payload()).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer((address, port), Handler)
        threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
            name="listen-together-host",
        ).start()

    @property
    def port(self) -> int:
        return int(self.server.server_port)

    def update(self, state: TogetherState) -> None:
        with self._lock:
            state.revision = self.state.revision + 1
            state.sent_at_ms = int(time.time() * 1000)
            self.state = state

    def share_url(self, host: str | None = None) -> str:
        host = host or local_address()
        query = urllib.parse.urlencode({"host": host, "port": self.port, "token": self.token})
        return f"harmonia://listen-together?{query}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class TogetherClient:
    def __init__(self, share_url: str, opener=None) -> None:
        parsed = urllib.parse.urlsplit(share_url.strip())
        values = urllib.parse.parse_qs(parsed.query)
        if parsed.scheme != "harmonia" or parsed.netloc != "listen-together":
            raise ValueError(_("Link Listen Together inválido"))
        try:
            self.host = values["host"][0]
            self.port = int(values["port"][0])
            self.token = values["token"][0]
        except (KeyError, ValueError, IndexError) as exc:
            raise ValueError(_("Link Listen Together incompleto")) from exc
        if not self.host or not self.token or not 1 <= self.port <= 65535:
            raise ValueError(_("Link Listen Together inválido"))
        self._opener = opener or urllib.request.urlopen

    def fetch(self) -> TogetherState:
        request = urllib.request.Request(
            f"http://{self.host}:{self.port}/state",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        with self._opener(request, timeout=3) as response:
            return TogetherState.from_payload(json.loads(response.read()))


def local_address() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        return str(probe.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()
