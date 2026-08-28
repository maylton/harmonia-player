from __future__ import annotations

import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from threading import Lock

WEB_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0"
_SAFE_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_PLAYER_PATH = re.compile(r"^/s/player/[A-Za-z0-9_-]+/.+\.js(?:\?.*)?$")
_CONFIG_TTL = 30 * 60


@dataclass(frozen=True, slots=True)
class PlayerConfig:
    player_url: str
    signature_timestamp: int | None
    visitor_data: str | None = None
    client_version: str | None = None
    encrypted_host_flags: str | None = None


@dataclass(frozen=True, slots=True)
class _CachedConfig:
    config: PlayerConfig
    expires_at: float


_CACHE: dict[tuple[str, bool], _CachedConfig] = {}
_CACHE_LOCK = Lock()


def _extract_player_url(html: str) -> str | None:
    normalized = html.replace(r"\/", "/").replace(r"\u0026", "&")
    patterns = (
        re.compile(r'"PLAYER_JS_URL":"([^"]+)"'),
        re.compile(r'"jsUrl":"([^"]+)"'),
        re.compile(r'(?<![A-Za-z0-9:/])(/s/player/[^"\'\\]+/[^"\'\\]*\.js[^"\'\\]*)'),
    )
    for pattern in patterns:
        match = pattern.search(normalized)
        if not match:
            continue
        path = match.group(1)
        value = path if path.startswith("http") else f"https://www.youtube.com/{path.lstrip('/')}"
        parsed = urllib.parse.urlsplit(value)
        if (
            parsed.scheme == "https"
            and parsed.hostname
            and (
                parsed.hostname == "youtube.com"
                or parsed.hostname.endswith(".youtube.com")
                or parsed.hostname == "youtube-nocookie.com"
                or parsed.hostname.endswith(".youtube-nocookie.com")
            )
            and _PLAYER_PATH.match(parsed.path + (f"?{parsed.query}" if parsed.query else ""))
        ):
            return value
    return None


def _extract_signature_timestamp(text: str) -> int | None:
    patterns = (
        re.compile(r"(?:signatureTimestamp|sts)\s*:\s*([0-9]{5})"),
        re.compile(r'"STS":\s*([0-9]{5})'),
    )
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return int(match.group(1))
    return None


def _extract_config_string(text: str, name: str) -> str | None:
    match = re.search(rf'"{re.escape(name)}"\s*:\s*"([^"]+)"', text)
    return match.group(1) if match else None


class PlayerConfigResolver:
    """Fetch the player JS URL and signature timestamp used by player requests."""

    def __init__(self, client):
        self.client = client

    def _read_text(
        self,
        url: str,
        *,
        max_bytes: int,
        use_login_cookies: bool = False,
        referer: str | None = None,
    ) -> str:
        headers = {
            "User-Agent": WEB_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": getattr(self.client, "hl", "pt-BR"),
        }
        if referer:
            headers["Referer"] = referer
        cookie = getattr(self.client, "cookie", "").strip()
        if use_login_cookies and cookie:
            headers["Cookie"] = cookie
        request = urllib.request.Request(url, headers=headers)
        with self.client._open(request, timeout=10) as response:
            raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise OSError("YouTube player configuration exceeded the size limit")
        return raw.decode(errors="replace")

    def _iframe_player_url(self) -> str | None:
        try:
            script = self._read_text(
                "https://www.youtube.com/iframe_api",
                max_bytes=1024 * 1024,
            )
        except (urllib.error.URLError, TimeoutError, OSError):
            return None
        match = re.search(r"/s/player/([A-Za-z0-9_-]+)/", script.replace(r"\/", "/"))
        if not match:
            return None
        player_id = match.group(1)
        return f"https://www.youtube.com/s/player/{player_id}/player_ias.vflset/en_GB/base.js"

    def fetch(
        self,
        video_id: str,
        *,
        use_login_cookies: bool = False,
        force: bool = False,
    ) -> PlayerConfig:
        if not _SAFE_VIDEO_ID.fullmatch(video_id):
            raise ValueError("Invalid YouTube video ID")
        cache_key = (video_id, bool(use_login_cookies))
        now = time.time()
        if not force:
            with _CACHE_LOCK:
                cached = _CACHE.get(cache_key)
            if cached and cached.expires_at > now:
                return cached.config

        page = self._read_text(
            f"https://www.youtube.com/watch?v={video_id}&bpctr=9999999999&has_verified=1",
            max_bytes=4 * 1024 * 1024,
            use_login_cookies=use_login_cookies,
        )
        player_url = _extract_player_url(page) or self._iframe_player_url()
        if not player_url:
            raise OSError("Unable to locate YouTube player JavaScript")

        signature_timestamp = _extract_signature_timestamp(page)
        if signature_timestamp is None:
            try:
                player_js = self._read_text(player_url, max_bytes=8 * 1024 * 1024)
            except (urllib.error.URLError, TimeoutError, OSError):
                player_js = ""
            signature_timestamp = _extract_signature_timestamp(player_js)

        config = PlayerConfig(
            player_url=player_url,
            signature_timestamp=signature_timestamp,
            visitor_data=_extract_config_string(page, "VISITOR_DATA")
            or _extract_config_string(page, "visitorData"),
            client_version=_extract_config_string(page, "INNERTUBE_CLIENT_VERSION"),
            encrypted_host_flags=_extract_config_string(page, "encryptedHostFlags"),
        )
        with _CACHE_LOCK:
            _CACHE[cache_key] = _CachedConfig(config, now + _CONFIG_TTL)
        return config
