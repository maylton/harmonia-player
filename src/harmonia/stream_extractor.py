from __future__ import annotations

import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .cipher import YouTubeCipherService
from .player_config import PlayerConfigResolver
from .player_director import PlayerClientDirector
from .stream_transport import (
    register_stream_transport,
    stream_transport_blocked,
)

LOGGER = logging.getLogger(__name__)
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
    is_embedded: bool = False
    context: tuple[tuple[str, Any], ...] = ()

    def context_values(self) -> dict[str, Any]:
        values = dict(self.context)
        if self.is_embedded:
            values.setdefault("thirdPartyEmbedUrl", "https://www.reddit.com/")
        return values


# Current playback identities mirrored from InnerTubeX's 2026 client inventory.
# SABR-only identities are deliberately omitted: Metrolist's own playback entry
# point currently requests allowSabr=false, and Harmonia/GStreamer consumes the
# same direct/bounded-range transports used by that path.
PLAYER_CLIENTS: tuple[PlayerClientProfile, ...] = (
    PlayerClientProfile(
        id="101",
        name="VISIONOS",
        version="1.02",
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_7_3) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Safari/605.1.15"
        ),
        use_music_player_endpoint=True,
        context=(
            ("osName", "visionOS"),
            ("osVersion", "26.5.23O471"),
            ("deviceMake", "Apple"),
            ("deviceModel", "RealityDevice17,1"),
        ),
    ),
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
        id="28",
        name="ANDROID_VR_1_43_32",
        version="1.43.32",
        user_agent=(
            "com.google.android.apps.youtube.vr.oculus/1.43.32 "
            "(Linux; U; Android 12; en_US; Quest 3; Build/SQ3A.220605.009.A1; "
            "Cronet/107.0.5284.2)"
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
    PlayerClientProfile(
        id="28",
        name="ANDROID_VR_1_61_48",
        version="1.61.48",
        user_agent=(
            "com.google.android.apps.youtube.vr.oculus/1.61.48 "
            "(Linux; U; Android 12; en_US; Quest 3; Build/SQ3A.220605.009.A1; "
            "Cronet/132.0.6808.3)"
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
    PlayerClientProfile(
        id="28",
        name="ANDROID_VR_1_65_10",
        version="1.65.10",
        user_agent=(
            "com.google.android.apps.youtube.vr.oculus/1.65.10 "
            "(Linux; U; Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip"
        ),
        include_user_agent_in_context=True,
        use_music_player_endpoint=True,
        context=(
            ("osName", "Android"),
            ("osVersion", "12L"),
            ("deviceMake", "Oculus"),
            ("deviceModel", "Quest 3"),
            ("androidSdkVersion", "32"),
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
        id="7",
        name="TVHTML5",
        version="7.20260707.07.00",
        user_agent=(
            "Mozilla/5.0 (ChromiumStylePlatform) Cobalt/25.lts.30.1034943-gold "
            "(unlike Gecko), Unknown_TV_Unknown_0/Unknown (Unknown, Unknown)"
        ),
        login_supported=True,
        use_signature_timestamp=True,
        use_web_potoken=True,
        include_user_agent_in_context=True,
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
        id="75",
        name="TVHTML5_SIMPLY",
        version="1.0",
        user_agent=(
            "Mozilla/5.0 (ChromiumStylePlatform) Cobalt/25.lts.30.1034943-gold "
            "(unlike Gecko), Unknown_TV_Unknown_0/Unknown (Unknown, Unknown)"
        ),
        use_signature_timestamp=True,
        use_web_potoken=True,
        require_potoken=True,
        use_music_player_endpoint=True,
    ),
    PlayerClientProfile(
        id="85",
        name="TVHTML5_SIMPLY_EMBEDDED_PLAYER",
        version="2.0",
        user_agent=(
            "Mozilla/5.0 (ChromiumStylePlatform) Cobalt/25.lts.30.1034943-gold "
            "(unlike Gecko), Unknown_TV_Unknown_0/Unknown (Unknown, Unknown)"
        ),
        use_signature_timestamp=True,
        use_web_potoken=True,
        require_potoken=True,
        is_embedded=True,
    ),
    PlayerClientProfile(
        id="5",
        name="IOS",
        version="21.26.4",
        user_agent=(
            "com.google.ios.youtube/21.26.4 "
            "(iPhone16,2; U; CPU iOS 18_3_2 like Mac OS X;)"
        ),
        include_user_agent_in_context=True,
        context=(
            ("osName", "iPhone"),
            ("osVersion", "18.3.2.22D82"),
            ("deviceMake", "Apple"),
            ("deviceModel", "iPhone16,2"),
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
    content_length: int | None = None

    @property
    def codecs(self) -> str:
        mime = self.mime_type.lower()
        marker = "codecs="
        if marker not in mime:
            return ""
        codecs = mime.split(marker, 1)[1].strip()
        return (
            codecs[1:].split('"', 1)[0]
            if codecs.startswith('"')
            else codecs.split(";", 1)[0]
        )

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


def _set_query_parameter(url: str, key: str, value: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = [(name, current) for name, current in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True) if name != key]
    query.append((key, value))
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment)
    )


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
        return _set_query_parameter(url, parameter, signature)
    return None if values.get("s") else url


def _video_codec_rank(mime_type: str) -> int:
    # H.264 is deliberately preferred on desktop: it has the broadest software
    # and hardware decoder coverage across the GNOME/KDE Flatpak runtimes and
    # avoids the GL negotiation failures observed with some VP9/AV1 paths.
    mime = mime_type.lower()
    if "avc1" in mime or "h264" in mime:
        return 4
    if "vp9" in mime or "vp09" in mime:
        return 3
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

    The extractor owns the same responsibilities InnerTubeX centralizes for
    Metrolist playback: client fallback/health, live player configuration,
    signature+n transforms, BotGuard PoTokens, format scoring, URL probing,
    bounded-range transport metadata, caching and diagnostics.
    """

    def __init__(self, client):
        self.client = client
        self.config_resolver = PlayerConfigResolver(client)
        self.cipher_service = YouTubeCipherService(client, config_resolver=self.config_resolver)
        self.director = PlayerClientDirector(client, self.config_resolver)

    @staticmethod
    def _tracking_url(payload: dict[str, Any]) -> str | None:
        return (
            ((payload.get("playbackTracking") or {}).get("videostatsPlaybackUrl") or {}).get(
                "baseUrl"
            )
            or None
        )

    def _authenticated(self) -> bool:
        try:
            return bool(self.client.authenticated)
        except Exception:
            return False

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
        streaming_pot = str(payload.get("_harmoniaStreamingPoToken") or "")

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
            if streaming_pot:
                url = _set_query_parameter(url, "pot", streaming_pot)
            duration = fmt.get("approxDurationMs")
            content_length = fmt.get("contentLength")
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
                    content_length=int(content_length) if content_length else None,
                )
            )
        return result

    def _probe(self, candidate: StreamCandidate) -> bool:
        if stream_transport_blocked(candidate.url):
            return False
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

    def _payloads(
        self,
        video_id: str,
        diagnostics: ExtractionDiagnostics,
        *,
        want_video: bool,
    ):
        yield from self.director.payloads(
            video_id,
            PLAYER_CLIENTS,
            diagnostics,
            want_video=want_video,
        )

    @staticmethod
    def _cached(cache_key: str, *, force: bool) -> StreamCandidate | None:
        if force:
            with _CACHE_LOCK:
                _STREAM_CACHE.pop(cache_key, None)
            return None
        with _CACHE_LOCK:
            candidate = _STREAM_CACHE.get(cache_key)
        if (
            candidate
            and candidate.valid_at(int(time.time()))
            and not stream_transport_blocked(candidate.url)
        ):
            register_stream_transport(
                candidate.url,
                candidate.headers,
                expires_at=candidate.expires_at,
            )
            return candidate
        return None

    @staticmethod
    def _store(cache_key: str, candidate: StreamCandidate) -> StreamCandidate:
        register_stream_transport(
            candidate.url,
            candidate.headers,
            expires_at=candidate.expires_at,
        )
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
        if not video_id:
            raise StreamExtractionError("A faixa não contém um identificador reproduzível.")
        cache_key = f"audio:{getattr(self.client, 'gl', 'US')}:{max_bitrate}:{video_id}"
        cached = self._cached(cache_key, force=force)
        if cached:
            return cached

        diagnostics = ExtractionDiagnostics(video_id)
        for profile, payload in self._payloads(video_id, diagnostics, want_video=False):
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
                reason = (
                    "falhou anteriormente no player"
                    if stream_transport_blocked(candidate.url)
                    else "rejeitado pelo CDN"
                )
                diagnostics.rejected.append(
                    f"{profile.name}: itag {candidate.itag or '?'} {reason}"
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
        if not video_id:
            raise StreamExtractionError("O vídeo não contém um identificador reproduzível.")
        max_height = max(144, int(max_height or 720))
        mode = "muxed" if progressive_only else "adaptive"
        cache_key = f"video:{getattr(self.client, 'gl', 'US')}:{max_height}:{mode}:{video_id}"
        cached = self._cached(cache_key, force=force)
        if cached:
            return cached

        diagnostics = ExtractionDiagnostics(video_id)
        for profile, payload in self._payloads(video_id, diagnostics, want_video=True):
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
                diagnostics.rejected.append(f"{profile.name}: formatos de vídeo sem resolução")
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
                reason = (
                    "falhou anteriormente no player"
                    if stream_transport_blocked(candidate.url)
                    else "rejeitado pelo CDN"
                )
                diagnostics.rejected.append(
                    f"{profile.name}: itag {candidate.itag or '?'} {reason}"
                )
        raise StreamExtractionError(
            f"Não foi possível obter um stream de vídeo reproduzível. {diagnostics.details()}",
            diagnostics,
        )
