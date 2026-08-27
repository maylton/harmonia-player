from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StreamTransport:
    headers: tuple[tuple[str, str], ...] = ()
    expires_at: int | None = None
    blocked_until: float = 0.0


_LOCK = threading.Lock()
_TRANSPORTS: dict[str, StreamTransport] = {}


def _expired(transport: StreamTransport, now: float) -> bool:
    return transport.expires_at is not None and transport.expires_at <= int(now)


def register_stream_transport(
    url: str,
    headers: tuple[tuple[str, str], ...] = (),
    *,
    expires_at: int | None = None,
) -> None:
    """Remember the HTTP contract required to consume one resolved media URL."""
    if not url:
        return
    now = time.time()
    with _LOCK:
        previous = _TRANSPORTS.get(url)
        blocked_until = 0.0
        if previous is not None and not _expired(previous, now):
            blocked_until = previous.blocked_until
        _TRANSPORTS[url] = StreamTransport(tuple(headers), expires_at, blocked_until)


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
    now = time.time()
    with _LOCK:
        transport = _TRANSPORTS.get(url)
        if transport is None:
            return False
        if _expired(transport, now):
            _TRANSPORTS.pop(url, None)
            return False
        return transport.blocked_until > now


def mark_stream_transport_failure(url: str, *, ttl: float = 120.0) -> None:
    """Temporarily quarantine a URL that passed HTTP probing but failed playback."""
    if not url:
        return
    now = time.time()
    with _LOCK:
        previous = _TRANSPORTS.get(url)
        headers = previous.headers if previous is not None else ()
        expires_at = previous.expires_at if previous is not None else None
        blocked_until = max(previous.blocked_until if previous is not None else 0.0, now + ttl)
        _TRANSPORTS[url] = StreamTransport(headers, expires_at, blocked_until)


def clear_stream_transport(url: str | None = None) -> None:
    """Test/support hook; clear one transport or the complete in-memory registry."""
    with _LOCK:
        if url is None:
            _TRANSPORTS.clear()
        else:
            _TRANSPORTS.pop(url, None)
