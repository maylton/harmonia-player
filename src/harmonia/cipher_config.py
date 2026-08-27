from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from .player_config import WEB_USER_AGENT

CONFIG_URL = (
    "https://raw.githubusercontent.com/ZemerTeam/zemer-cipher/master/"
    "library/src/main/assets/player_configs.json"
)
SUPPORTED_SCHEMA_VERSION = 1
_CONFIG_TTL = 6 * 60 * 60
_MAX_CONFIG_SIZE = 2 * 1024 * 1024
_HASH_RE = re.compile(r"^[a-f0-9]{8}$")
_SIG_RE = re.compile(r"^[A-Za-z0-9$_]{1,8}\(\d+,\d+,INPUT\)$")
_NCLASS_RE = re.compile(r"^[A-Za-z0-9$_]{1,8}$")
_PLAYER_HASH_PATTERNS = (
    re.compile(r"/player/([a-f0-9]{8})/"),
    re.compile(r"player_ias\.vflset/[^/]+/([a-f0-9]{8})/"),
    re.compile(r"/s/player/([a-f0-9]{8})/"),
)


@dataclass(frozen=True, slots=True)
class CipherConfig:
    signature_expression: str
    n_class: str
    signature_timestamp: int


@dataclass(frozen=True, slots=True)
class _ConfigCache:
    values: dict[str, CipherConfig]
    expires_at: float


_CACHE: _ConfigCache | None = None
_CACHE_LOCK = threading.Lock()


def extract_player_hash(player_url: str) -> str | None:
    for pattern in _PLAYER_HASH_PATTERNS:
        match = pattern.search(player_url)
        if match:
            return match.group(1)
    return None


def parse_cipher_configs(raw: str) -> dict[str, CipherConfig]:
    try:
        root = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("malformed cipher configuration JSON") from exc
    if not isinstance(root, dict):
        raise ValueError("cipher configuration root is not an object")
    schema = root.get("schemaVersion")
    if not isinstance(schema, int) or schema <= 0:
        raise ValueError("cipher configuration schemaVersion is invalid")
    if schema > SUPPORTED_SCHEMA_VERSION:
        raise ValueError(f"unsupported cipher configuration schema {schema}")
    players = root.get("players")
    if not isinstance(players, dict):
        raise ValueError("cipher configuration players map is missing")

    result: dict[str, CipherConfig] = {}
    for player_hash, value in players.items():
        if not isinstance(player_hash, str) or not _HASH_RE.fullmatch(player_hash):
            continue
        if not isinstance(value, dict):
            continue
        signature = value.get("sig")
        n_class = value.get("nClass")
        sts = value.get("sts")
        if not isinstance(signature, str) or not _SIG_RE.fullmatch(signature):
            continue
        if not isinstance(n_class, str) or not _NCLASS_RE.fullmatch(n_class):
            continue
        if not isinstance(sts, int) or sts <= 0:
            continue

        config = CipherConfig(signature, n_class, sts)
        keys = [player_hash]
        aliases = value.get("aliases", [])
        if isinstance(aliases, list):
            keys.extend(
                alias
                for alias in aliases
                if isinstance(alias, str) and _HASH_RE.fullmatch(alias)
            )
        if any(key in result for key in keys):
            raise ValueError(f"duplicate cipher player hash/alias: {player_hash}")
        for key in keys:
            result[key] = config
    return result


class RemoteCipherConfigStore:
    def __init__(self, client):
        self.client = client

    def _download(self) -> str:
        request = urllib.request.Request(
            CONFIG_URL,
            headers={"User-Agent": WEB_USER_AGENT, "Accept": "application/json"},
        )
        with self.client._open(request, timeout=10) as response:
            raw = response.read(_MAX_CONFIG_SIZE + 1)
        if len(raw) > _MAX_CONFIG_SIZE:
            raise OSError("cipher configuration exceeded size limit")
        return raw.decode(errors="strict")

    def load(self, *, force: bool = False) -> dict[str, CipherConfig]:
        global _CACHE
        now = time.time()
        if not force:
            with _CACHE_LOCK:
                cached = _CACHE
            if cached is not None and cached.expires_at > now:
                return cached.values

        try:
            values = parse_cipher_configs(self._download())
        except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError, ValueError):
            with _CACHE_LOCK:
                cached = _CACHE
            if cached is not None:
                return cached.values
            raise

        with _CACHE_LOCK:
            _CACHE = _ConfigCache(values, now + _CONFIG_TTL)
        return values

    def for_player(self, player_url: str) -> CipherConfig | None:
        player_hash = extract_player_hash(player_url)
        if not player_hash:
            return None
        return self.load().get(player_hash)
