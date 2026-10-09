"""Which InnerTube clients ask for streams, and in which order.

YouTube breaks clients from time to time (an old version starts to be
refused, a client loses direct URLs). Two things keep playback going without
a new Harmonia release:

- A list of client profiles published in the repository
  (data/player-clients.json), fetched in the background at most once a day
  and cached. It is plain data, strictly validated; anything unexpected and
  the built-in profiles (innertube/protocol.py) are used instead.
- The clients' health in this session: the last one that delivered a
  stream is asked first, and one that keeps failing goes to the end, still
  tried after the others.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.request
from collections.abc import Callable, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

from .protocol import PLAYER_CLIENTS

LOGGER = logging.getLogger(__name__)
REMOTE_URL = (
    "https://raw.githubusercontent.com/maylton/harmonia-player/main/data/player-clients.json"
)
SCHEMA_VERSION = 1
REFRESH_S = 24 * 60 * 60
MAX_BYTES = 64 * 1024
MAX_CLIENTS = 12
FAILURES_TO_DEMOTE = 3

_NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,40}$")
_ID = re.compile(r"^\d{1,4}$")
_TEXT_KEYS = ("version", "user_agent")
_FLAGS = ("authenticated", "live_version")


def validate(document: Any) -> list[dict[str, Any]]:
    """The client profiles of a published list; ValueError if anything is off."""
    if not isinstance(document, dict) or document.get("schema") != SCHEMA_VERSION:
        raise ValueError("unknown schema")
    clients = document.get("clients")
    if not isinstance(clients, list) or not 0 < len(clients) <= MAX_CLIENTS:
        raise ValueError("clients must be a non-empty list")
    profiles = []
    for entry in clients:
        if not isinstance(entry, dict):
            raise ValueError("a client must be an object")
        if entry.get("enabled", True) is False:
            continue
        name, client_id = entry.get("name"), entry.get("id")
        if not isinstance(name, str) or not _NAME.match(name):
            raise ValueError(f"bad client name: {name!r}")
        if not isinstance(client_id, str) or not _ID.match(client_id):
            raise ValueError(f"bad client id for {name}")
        profile: dict[str, Any] = {"name": name, "id": client_id}
        for key in _TEXT_KEYS:
            value = entry.get(key)
            if not isinstance(value, str) or not 0 < len(value) <= 300:
                raise ValueError(f"bad {key} for {name}")
            profile[key] = value
        context = entry.get("context", {})
        if not isinstance(context, dict) or not all(
            isinstance(key, str) and isinstance(value, str | int) and not isinstance(value, bool)
            for key, value in context.items()
        ):
            raise ValueError(f"bad context for {name}")
        if context:
            profile["context"] = dict(context)
        for flag in _FLAGS:
            if entry.get(flag) is True:
                profile[flag] = True
        profiles.append(profile)
    if not profiles:
        raise ValueError("every client is disabled")
    return profiles


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Harmonia"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read(MAX_BYTES + 1)


class PlayerClientCatalog:
    def __init__(
        self,
        cache_file: Callable[[], Path] | None = None,
        download: Callable[[str], bytes] = _download,
        builtin: Sequence[dict[str, Any]] = PLAYER_CLIENTS,
    ) -> None:
        self._cache_file = cache_file or _default_cache_file
        self._download = download
        self._builtin = [dict(profile) for profile in builtin]
        self._lock = threading.Lock()
        self._health: dict[str, list[int]] = {}  # name -> [consecutive failures]
        self._last_success: str | None = None
        self._refreshing = False

    # Profiles

    def profiles(self) -> list[dict[str, Any]]:
        """The clients to ask, healthiest first; refreshes the published list if stale."""
        published, fetched_at = self._cached()
        if time.time() - fetched_at > REFRESH_S:
            self._refresh_in_background()
        return self.ordered(published or self._builtin)

    def _cached(self) -> tuple[list[dict[str, Any]] | None, float]:
        """The cached list if valid, and when it was last fetched (or tried)."""
        path = self._cache_file()
        try:
            fetched_at = path.stat().st_mtime
        except OSError:
            return None, 0.0
        try:
            return validate(json.loads(path.read_text(encoding="utf-8"))), fetched_at
        except (OSError, ValueError):
            return None, fetched_at

    def _refresh_in_background(self) -> None:
        with self._lock:
            if self._refreshing:
                return
            self._refreshing = True
        threading.Thread(target=self.refresh, daemon=True, name="player-clients").start()

    def refresh(self) -> bool:
        """Fetch and cache the published list; False keeps what there was."""
        try:
            body = self._download(REMOTE_URL)
            if len(body) > MAX_BYTES:
                raise ValueError("list too large")
            validate(json.loads(body.decode("utf-8")))
            path = self._cache_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            return True
        except Exception:
            LOGGER.debug("Lista de clientes publicada indisponível", exc_info=True)
            with suppress(OSError):  # retry tomorrow, not on every stream
                self._cache_file().touch()
            return False
        finally:
            with self._lock:
                self._refreshing = False

    # Health

    def ordered(self, profiles: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        with self._lock:
            last, health = self._last_success, dict(self._health)

        def rank(indexed: tuple[int, dict[str, Any]]) -> tuple[int, int, int]:
            index, profile = indexed
            failing = health.get(profile["name"], [0])[0] >= FAILURES_TO_DEMOTE
            return (int(failing), 0 if profile["name"] == last else 1, index)

        return [profile for _index, profile in sorted(enumerate(profiles), key=rank)]

    def record(self, name: str, ok: bool) -> None:
        with self._lock:
            entry = self._health.setdefault(name, [0])
            if ok:
                entry[0] = 0
                self._last_success = name
            else:
                entry[0] += 1


def _default_cache_file() -> Path:
    from .. import host

    return host.cache_dir() / "player-clients.json"


CATALOG = PlayerClientCatalog()
