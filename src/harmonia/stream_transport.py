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


def _is_googlevideo_host(host: str) -> bool:
    return host == "googlevideo.com" or host.endswith(".googlevideo.com")


def _failure_key(url: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return url

    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    host = (parsed.hostname or "").casefold()
    if _is_googlevideo_host(host):
        params = {name.casefold(): value for name, value in pairs if value}
        media_id = params.get("id")
        itag = params.get("itag")
        if media_id and itag:
            return f"googlevideo:{media_id}:itag:{itag}"

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
    if not url:
        return
    key = _failure_key(url)
    now = time.time()
    with _LOCK:
        _FAILURES[key] = max(_FAILURES.get(key, 0.0), now + max(1.0, ttl))


def clear_stream_transport(url: str | None = None) -> None:
    with _LOCK:
        if url is None:
            _TRANSPORTS.clear()
            _FAILURES.clear()
        else:
            _TRANSPORTS.pop(url, None)
            _FAILURES.pop(_failure_key(url), None)
