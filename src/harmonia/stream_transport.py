from __future__ import annotations

import threading
import time
import urllib.parse
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StreamTransport:
    headers: tuple[tuple[str, str], ...] = ()
    expires_at: int | None = None


_LOCK = threading.Lock()
_TRANSPORTS: dict[str, StreamTransport] = {}
_FAILURES: dict[str, float] = {}
_VOLATILE_FAILURE_PARAMS = {"cpn", "pot"}


def _expired(transport: StreamTransport, now: float) -> bool:
    return transport.expires_at is not None and transport.expires_at <= int(now)


def _failure_key(url: str) -> str:
    """Normalize request-scoped tokens and prefer the Googlevideo itag."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return url
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    host = (parsed.hostname or "").casefold()
    if host.endswith("googlevideo.com"):
        itag = next((value for name, value in pairs if name.casefold() == "itag" and value), "")
        if itag:
            return f"googlevideo:itag:{itag}"
    query = [
        (name, value) for name, value in pairs if name.casefold() not in _VOLATILE_FAILURE_PARAMS
    ]
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urllib.parse.urlencode(query),
            "",
        )
    )


def register_stream_transport(
    url: str,
    headers: tuple[tuple[str, str], ...] = (),
    *,
    expires_at: int | None = None,
) -> None:
    """Remember the HTTP contract required to consume one resolved media URL."""
    if not url:
        return
    with _LOCK:
        _TRANSPORTS[url] = StreamTransport(tuple(headers), expires_at)


def stream_transport_headers(url: str) -> tuple[tuple[str, str], ...]:
    if not url:
        return ()
    now = time.time()
    with _LOCK:
        transport = _TRANSPORTS.get(url)
        if transport is None:
            return ()
        if _expired(transport, now):
            _TRANSPORTS.pop(url, None)
            return ()
        return transport.headers


def stream_transport_blocked(url: str) -> bool:
    if not url:
        return False
    key = _failure_key(url)
    now = time.time()
    with _LOCK:
        blocked_until = _FAILURES.get(key, 0.0)
        if blocked_until <= now:
            _FAILURES.pop(key, None)
            return False
        return True


def mark_stream_transport_failure(url: str, *, ttl: float = 120.0) -> None:
    """Temporarily quarantine a failed URL/Googlevideo representation."""
    if not url:
        return
    key = _failure_key(url)
    now = time.time()
    with _LOCK:
        _FAILURES[key] = max(_FAILURES.get(key, 0.0), now + max(1.0, ttl))


def clear_stream_transport(url: str | None = None) -> None:
    """Test/support hook; clear one transport or the complete in-memory registry."""
    with _LOCK:
        if url is None:
            _TRANSPORTS.clear()
            _FAILURES.clear()
        else:
            _TRANSPORTS.pop(url, None)
            _FAILURES.pop(_failure_key(url), None)
