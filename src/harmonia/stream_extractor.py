from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .cipher import YouTubeCipherService
from .player_config import PlayerConfig, PlayerConfigResolver

LOGGER = logging.getLogger(__name__)

ORIGIN = "https://music.youtube.com"
API_URL = f"{ORIGIN}/youtubei/v1"
WEB_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) "
    "Gecko/20100101 Firefox/140.0"
)
_CACHE_LOCK = threading.Lock()
_STREAM_CACHE: dict[str, "StreamCandidate"] = {}


@dataclass(frozen=True, slots=True)
class PlayerClientProfile:
    id: str
    name: str
    version: str
    user_agent: str
    login_supported: bool = False
    login_required: bool = False
    use_live_version: bool = False
    use_signature_timestamp: bool = False
    use_web_potoken: bool = False
    require_potoken: bool = False
    include_user_agent_in_context: bool = False
    use_music_player_endpoint: bool = False
    skip_response_validation: bool = False
    context: tuple[tuple[str, Any], ...] = ()

    def context_values(self) -> dict[str, Any]:
        return dict(self.context)


# Playback profiles mirror the useful non-SABR part of InnerTubeX's current
# catalog. Token-mandatory profiles will be enabled once the shared PoToken
# provider is connected; profiles for which PoToken is optional can already
# benefit from signature timestamp and cipher transforms.
PLAYER_CLIENTS: tuple[PlayerClientProfile, ...] = (
    PlayerClientProfile(
        id="101",
        name="VISIONOS_0_1",
        version="0.1",
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
        ),
        use_music_player_endpoint=True,
        skip_response_validation=True,
        context=(
            ("osName", "VISION_OS"),
            ("osVersion", "1.3"),
            ("deviceMake", "Apple"),
            ("deviceModel", "RealityDevice14,1"),
            ("platform", "MOBILE"),
        ),
    ),
    PlayerClientProfile(
        id="67",
        name="WEB_REMIX",
        version="1.20260707.12.00",
        user_agent=WEB_USER_AGENT,
        login_supported=True,
        use_live_version=True,
        use_signature_timestamp=True,
        use_web_potoken=True,
    ),
    PlayerClientProfile(
        id="62",
        name="WEB_CREATOR",
        version="1.20260708.06.00",
        user_agent=WEB_USER_AGENT,
        login_supported=True,
        login_required=True,
        use_signature_timestamp=True,
        use_web_potoken=True,
    ),
    PlayerClientProfile(
        id="5",
        name="IOS",
        version="21.03.1",
        user_agent=(
            "com.google.ios.youtube/21.03.1 "
            "(iPhone16,2; U; CPU iOS 18_2 like Mac OS X;)"
        ),
        context=(("osName", "iOS"), ("osVersion", "18.2")),
    ),
    PlayerClientProfile(
        id="28",
        name="ANDROID_VR_1_43_32",
        version="1.43.32",
        user_agent=(
            "com.google.android.apps.youtube.vr.oculus/1.43.32 "
            "(Linux; U; Android 12; en_US; Quest 3; "
            "Build/SQ3A.220605.009.A1; Cronet/107.0.5284.2)"
        ),
        include_user_agent_in_context=True,
        use_music_player_endpoint=True,
        context=(
            ("osName", "Android"),
            ("osVersion", "12"),
            ("deviceMake", "Oculus"),
            ("deviceModel", "Quest 3"),
            ("androidSdkVersion", "32"),
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class StreamCandidate:
    url: str
    client: str
    mime_type: str
    bitrate: int
    itag: int | None
    duration_ms: int | None
    width: int = 0
    height: int = 0
    fps: int = 0
    muxed: bool = False
    headers: tuple[tuple[str, str], ...] = ()
    expires_at: int | None = None
    playback_tracking_url: str | None = None

    @property
    def codecs(self) -> str:
        mime = self.mime_type.lower()
        marker = "codecs="
        if marker not in mime:
            return ""
        codecs = mime.split(marker, 1)[1].strip()
        codecs = (
            codecs[1:].split('"', 1)[0]
            if codecs.startswith('"')
            else codecs.split(";", 1)[0]
        )
        return codecs

    @property
    def is_audio(self) -> bool:
        return self.mime_type.lower().startswith("audio/")

    @property
    def is_video(self) -> bool:
        return self.mime_type.lower().startswith("video/")

    def valid_at(self, timestamp: int, margin: int = 90) -> bool:
        return self.expires_at is None or timestamp + margin < self.expires_at


@dataclass(slots=True)
class ExtractionDiagnostics:
    video_id: str
    attempts: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)

    def details(self) -> str:
        return "; ".join((*self.attempts, *self.rejected))


class StreamExtractionError(RuntimeError):
    def __init__(self, message: str, diagnostics: ExtractionDiagnostics | None = None):
        super().__init__(message)
        self.diagnostics = diagnostics


def _stream_expiration(url: str) -> int | None:
    values = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("expire")
    try:
        return int(values[0]) if values else None
    except (TypeError, ValueError):
        return None


def _cipher_url(fmt: dict[str, Any]) -> str | None:
    """Compatibility helper for formats that need no JavaScript deciphering."""
    if fmt.get("url"):
        return str(fmt["url"])
    raw = fmt.get("signatureCipher") or fmt.get("cipher")
    if not raw:
        return None
    values = urllib.parse.parse_qs(str(raw), keep_blank_values=True)
    urls = values.get("url")
    if not urls:
        return None
    url = urls[0]
    signature = (values.get("sig") or values.get("signature") or [None])[0]
    if signature:
        parameter = (values.get("sp") or ["signature"])[0]
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        query.append((parameter, signature))
        return urllib.parse.urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                urllib.parse.urlencode(query),
                parsed.fragment,
            )
        )
    return None if values.get("s") else url


def _video_codec_rank(mime_type: str) -> int:
    mime = mime_type.lower()
    if "vp9" in mime or "vp09" in mime:
        return 3
    if "avc1" in mime or "h264" in mime:
        return 2
    if "av01" in mime or "av1" in mime:
        return 1
    return 0


def _audio_codec_rank(mime_type: str) -> int:
    mime = mime_type.lower()
    if "opus" in mime or mime.startswith("audio/webm"):
        return 2
    if "mp4a" in mime or mime.startswith("audio/mp4"):
        return 1
    return 0


class InnerTubeStreamExtractor:
    """Shared resilient stream resolver for Harmonia audio and video.

    Player configuration, signature deciphering, n-throttling transforms,
    fallback clients, format scoring, CDN probing and diagnostics live here so
    GTK and Qt consume the same extraction contract.
    """

    def __init__(self, client):
        self.client = client
        self.config_resolver = PlayerConfigResolver(client)
        self.cipher_service = YouTubeCipherService(
            client,
            config_resolver=self.config_resolver,
        )
        self._player_configs: dict[bool, PlayerConfig] = {}

    def _player_config(self, video_id: str, *, authenticated: bool) -> PlayerConfig | None:
        cached = self._player_configs.get(authenticated)
        if cached is not None:
            return cached
        try:
            config = self.config_resolver.fetch(
                video_id,
                use_login_cookies=authenticated,
            )
        except Exception as exc:
            LOGGER.debug("YouTube player config unavailable: %s", exc)
            return None
        self._player_configs[authenticated] = config
        return config

    def _authenticated(self) -> bool:
        try:
            return bool(self.client.authenticated)
        except Exception:
            return False

    def _profile_version(self, profile: PlayerClientProfile) -> str:
        if profile.use_live_version and getattr(self.client, "client_version", None):
            return str(self.client.client_version)
        return profile.version

    def _request_player(
        self,
        video_id: str,
        profile: PlayerClientProfile,
        diagnostics: ExtractionDiagnostics,
    ) -> dict[str, Any] | None:
        if profile.login_required and not self._authenticated():
            diagnostics.attempts.append(f"{profile.name}: login necessário")
            return None
        if profile.require_potoken:
            diagnostics.attempts.append(f"{profile.name}: PoToken obrigatório ainda indisponível")
            return None

        authenticated = profile.login_supported and self._authenticated()
        config = (
            self._player_config(video_id, authenticated=authenticated)
            if profile.use_signature_timestamp
            else None
        )
        version = (
            config.client_version
            if profile.use_live_version and config and config.client_version
            else self._profile_version(profile)
        )
        client_name = profile.name.split("_0_1", 1)[0].split("_1_", 1)[0]
        client_context: dict[str, Any] = {
            "clientName": client_name,
            "clientVersion": version,
            "hl": getattr(self.client, "hl", "pt-BR"),
            "gl": getattr(self.client, "gl", "BR"),
            **profile.context_values(),
        }
        if profile.include_user_agent_in_context:
            client_context["userAgent"] = profile.user_agent
        visitor_data = getattr(self.client, "visitor_data", None) or (
            config.visitor_data if config else None
        )
        if visitor_data:
            client_context["visitorData"] = visitor_data

        user_context: dict[str, Any] = {}
        data_sync_id = getattr(self.client, "data_sync_id", None)
        if authenticated and data_sync_id:
            user_context["onBehalfOfUser"] = data_sync_id

        body: dict[str, Any] = {
            "context": {"client": client_context, "user": user_context},
            "videoId": video_id,
            "contentCheckOk": True,
            "racyCheckOk": True,
        }
        if config and config.signature_timestamp is not None:
            body["playbackContext"] = {
                "contentPlaybackContext": {"signatureTimestamp": config.signature_timestamp}
            }

        request = urllib.request.Request(
            f"{API_URL}/player?prettyPrint=false",
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": profile.user_agent,
                "Origin": ORIGIN,
                "Referer": f"{ORIGIN}/",
                "X-YouTube-Client-Name": profile.id,
                "X-YouTube-Client-Version": version,
                **({"X-Goog-Visitor-Id": visitor_data} if visitor_data else {}),
            },
        )

        if authenticated:
            from .innertube import sapisid_hash

            request.add_header("Cookie", self.client.cookie)
            request.add_header("Authorization", sapisid_hash(self.client.cookie))
            request.add_header("X-Origin", ORIGIN)

        for attempt in range(2):
            try:
                with self.client._open(request, timeout=30) as response:
                    payload = json.load(response)
                status = payload.get("playabilityStatus") or {}
                if status.get("status") == "OK":
                    return payload
                diagnostics.attempts.append(
                    f"{profile.name}: "
                    f"{status.get('reason') or status.get('status') or 'não reproduzível'}"
                )
                return payload
            except urllib.error.HTTPError as exc:
                if exc.code not in (408, 429, 500, 502, 503, 504) or attempt == 1:
                    diagnostics.attempts.append(f"{profile.name}: HTTP {exc.code}")
                    return None
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                if attempt == 1:
                    diagnostics.attempts.append(f"{profile.name}: {exc}")
                    return None
            time.sleep(0.2 * (2**attempt))
        return None

    @staticmethod
    def _tracking_url(payload: dict[str, Any]) -> str | None:
        return (
            ((payload.get("playbackTracking") or {}).get("videostatsPlaybackUrl") or {}).get(
                "baseUrl"
            )
            or None
        )

    def _format_candidates(
        self,
        payload: dict[str, Any],
        profile: PlayerClientProfile,
        video_id: str,
    ) -> list[StreamCandidate]:
        streaming = payload.get("streamingData") or {}
        progressive_ids = {
            int(fmt["itag"])
            for fmt in (streaming.get("formats") or [])
            if fmt.get("itag") is not None
        }
        formats = [*(streaming.get("formats") or []), *(streaming.get("adaptiveFormats") or [])]
        result: list[StreamCandidate] = []
        tracking = self._tracking_url(payload)
        authenticated = profile.login_supported and self._authenticated()

        for fmt in formats:
            mime_type = str(fmt.get("mimeType") or "")
            if not mime_type.startswith(("audio/", "video/")):
                continue
            resolved = self.cipher_service.resolve_format_url(
                fmt,
                video_id,
                authenticated=authenticated,
            )
            if resolved is None:
                continue
            url = resolved.url
            duration = fmt.get("approxDurationMs")
            itag = int(fmt["itag"]) if fmt.get("itag") is not None else None
            headers = [
                ("User-Agent", profile.user_agent),
                ("Origin", "https://www.youtube.com"),
                ("Referer", "https://www.youtube.com/"),
            ]
            if authenticated and getattr(self.client, "cookie", ""):
                headers.append(("Cookie", self.client.cookie))
            result.append(
                StreamCandidate(
                    url=url,
                    client=profile.name,
                    mime_type=mime_type,
                    bitrate=int(fmt.get("bitrate", 0) or 0),
                    itag=itag,
                    duration_ms=int(duration) if duration else None,
                    width=int(fmt.get("width", 0) or 0),
                    height=int(fmt.get("height", 0) or 0),
                    fps=int(fmt.get("fps", 0) or 0),
                    muxed=itag in progressive_ids,
                    headers=tuple(headers),
                    expires_at=_stream_expiration(url),
                    playback_tracking_url=tracking,
                )
            )
        return result

    def _probe(self, candidate: StreamCandidate) -> bool:
        host = urllib.parse.urlsplit(candidate.url).hostname or ""
        if "googlevideo.com" not in host:
            return True

        headers = dict(candidate.headers)
        headers["Range"] = "bytes=0-1"
        request = urllib.request.Request(candidate.url, headers=headers, method="GET")
        try:
            with self.client._open(request, timeout=15) as response:
                status = getattr(response, "status", None) or response.getcode()
                content_type = str(response.headers.get("Content-Type", "")).lower()
                if status not in (200, 206):
                    return False
                if content_type.startswith(("text/", "application/json")):
                    return False
                response.read(2)
                return True
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
            return False

    def _payloads(self, video_id: str, diagnostics: ExtractionDiagnostics):
        try:
            self.client._bootstrap()
        except Exception as exc:
            LOGGER.debug("InnerTube bootstrap failed before extraction: %s", exc)

        for profile in PLAYER_CLIENTS:
            payload = self._request_player(video_id, profile, diagnostics)
            if not payload:
                continue
            status = payload.get("playabilityStatus") or {}
            if status.get("status") == "OK":
                yield profile, payload

    @staticmethod
    def _cached(cache_key: str, *, force: bool) -> StreamCandidate | None:
        if force:
            with _CACHE_LOCK:
                _STREAM_CACHE.pop(cache_key, None)
            return None
        with _CACHE_LOCK:
            candidate = _STREAM_CACHE.get(cache_key)
        if candidate and candidate.valid_at(int(time.time())):
            return candidate
        return None

    @staticmethod
    def _store(cache_key: str, candidate: StreamCandidate) -> StreamCandidate:
        with _CACHE_LOCK:
            _STREAM_CACHE[cache_key] = candidate
        return candidate

    def extract_audio(
        self,
        video_id: str,
        *,
        max_bitrate: int = 10_000_000,
        force: bool = False,
    ) -> StreamCandidate:
        cache_key = f"audio:{getattr(self.client, 'gl', 'US')}:{max_bitrate}:{video_id}"
        cached = self._cached(cache_key, force=force)
        if cached:
            return cached

        diagnostics = ExtractionDiagnostics(video_id)
        for profile, payload in self._payloads(video_id, diagnostics):
            candidates = [
                candidate
                for candidate in self._format_candidates(payload, profile, video_id)
                if candidate.is_audio
            ]
            if not candidates:
                diagnostics.rejected.append(f"{profile.name}: sem URL de áudio resolvida")
                continue
            within = [candidate for candidate in candidates if candidate.bitrate <= max_bitrate]
            pool = within or candidates
            ordered = sorted(
                pool,
                key=lambda candidate: (
                    candidate.bitrate,
                    _audio_codec_rank(candidate.mime_type),
                ),
                reverse=True,
            )
            for candidate in ordered:
                if self._probe(candidate):
                    return self._store(cache_key, candidate)
                diagnostics.rejected.append(
                    f"{profile.name}: itag {candidate.itag or '?'} rejeitado pelo CDN"
                )
        raise StreamExtractionError(
            f"Não foi possível obter um stream de áudio reproduzível. {diagnostics.details()}",
            diagnostics,
        )

    def extract_video(
        self,
        video_id: str,
        *,
        max_height: int = 720,
        progressive_only: bool = False,
        force: bool = False,
    ) -> StreamCandidate:
        max_height = max(144, int(max_height or 720))
        mode = "muxed" if progressive_only else "adaptive"
        cache_key = f"video:{getattr(self.client, 'gl', 'US')}:{max_height}:{mode}:{video_id}"
        cached = self._cached(cache_key, force=force)
        if cached:
            return cached

        diagnostics = ExtractionDiagnostics(video_id)
        for profile, payload in self._payloads(video_id, diagnostics):
            candidates = [
                candidate
                for candidate in self._format_candidates(payload, profile, video_id)
                if candidate.is_video and (candidate.muxed or not progressive_only)
            ]
            if not candidates:
                diagnostics.rejected.append(f"{profile.name}: sem URL de vídeo resolvida")
                continue
            within = [candidate for candidate in candidates if 0 < candidate.height <= max_height]
            pool = within or [candidate for candidate in candidates if candidate.height > 0]
            if not pool:
                continue
            ordered = sorted(
                pool,
                key=lambda candidate: (
                    min(candidate.height, max_height),
                    _video_codec_rank(candidate.mime_type),
                    candidate.fps,
                    candidate.bitrate,
                ),
                reverse=True,
            )
            for candidate in ordered:
                if self._probe(candidate):
                    return self._store(cache_key, candidate)
                diagnostics.rejected.append(
                    f"{profile.name}: itag {candidate.itag or '?'} rejeitado pelo CDN"
                )
        raise StreamExtractionError(
            f"Não foi possível obter um stream de vídeo reproduzível. {diagnostics.details()}",
            diagnostics,
        )
