from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

LOGGER = logging.getLogger(__name__)

ORIGIN = "https://music.youtube.com"
API_URL = f"{ORIGIN}/youtubei/v1"
WEB_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) "
    "Gecko/20100101 Firefox/140.0"
)


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


# The catalog deliberately mirrors the capabilities of current InnerTubeX
# clients without coupling Harmonia to Kotlin/JVM. Profiles that require token
# minting are present for diagnostics but are not automatic until the Python
# token provider is implemented.
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
        if codecs.startswith('"'):
            codecs = codecs[1:].split('"', 1)[0]
        else:
            codecs = codecs.split(";", 1)[0]
        return codecs

    @property
    def is_audio(self) -> bool:
        return self.mime_type.lower().startswith("audio/")

    @property
    def is_video(self) -> bool:
        return self.mime_type.lower().startswith("video/")


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
    """Return a directly usable URL when the response does not require JS deciphering."""
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

    # Some responses carry an already-deciphered signature. If only encrypted
    # `s` exists, the future cipher provider must transform it using player JS.
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
    if values.get("s"):
        return None
    return url


def _video_codec_rank(mime_type: str) -> int:
    mime = mime_type.lower()
    # Open codecs are normally present in the desktop runtimes. H.264 may rely
    # on an extra codec extension and AV1 remains the most expensive fallback.
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

    The architecture follows the same separation used by Metrolist/InnerTubeX:
    a client catalog, ordered fallback, format scoring, URL probing, diagnostics,
    and explicit extension points for cipher and PoToken work. It remains native
    Python so both GTK and Qt frontends share exactly the same extraction layer.
    """

    def __init__(self, client):
        self.client = client

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

        version = self._profile_version(profile)
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
        visitor_data = getattr(self.client, "visitor_data", None)
        if visitor_data:
            client_context["visitorData"] = visitor_data

        user_context: dict[str, Any] = {}
        data_sync_id = getattr(self.client, "data_sync_id", None)
        if profile.login_supported and data_sync_id:
            user_context["onBehalfOfUser"] = data_sync_id

        body: dict[str, Any] = {
            "context": {"client": client_context, "user": user_context},
            "videoId": video_id,
            "contentCheckOk": True,
            "racyCheckOk": True,
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

        if profile.login_supported and self._authenticated():
            # Import lazily to keep this module independent from innertube.py at
            # import time and avoid a circular dependency.
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
            (((payload.get("playbackTracking") or {}).get("videostatsPlaybackUrl") or {}).get("baseUrl"))
            or None
        )

    def _format_candidates(
        self,
        payload: dict[str, Any],
        profile: PlayerClientProfile,
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

        for fmt in formats:
            mime_type = str(fmt.get("mimeType") or "")
            if not mime_type.startswith(("audio/", "video/")):
                continue
            url = _cipher_url(fmt)
            if not url:
                continue
            duration = fmt.get("approxDurationMs")
            itag = int(fmt["itag"]) if fmt.get("itag") is not None else None
            headers = (
                ("User-Agent", profile.user_agent),
                ("Origin", "https://www.youtube.com"),
                ("Referer", "https://www.youtube.com/"),
            )
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
                    headers=headers,
                    expires_at=_stream_expiration(url),
                    playback_tracking_url=tracking,
                )
            )
        return result

    def _probe(self, candidate: StreamCandidate) -> bool:
        host = urllib.parse.urlsplit(candidate.url).hostname or ""
        # Synthetic/test URLs and non-GVS endpoints are accepted without an
        # extra round trip. GVS URLs are probed because token/cipher failures
        # otherwise surface much later inside the media pipeline.
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
            if status.get("status") != "OK":
                continue
            yield profile, payload

    def extract_audio(
        self,
        video_id: str,
        *,
        max_bitrate: int = 10_000_000,
    ) -> StreamCandidate:
        diagnostics = ExtractionDiagnostics(video_id)
        for profile, payload in self._payloads(video_id, diagnostics):
            candidates = [
                candidate
                for candidate in self._format_candidates(payload, profile)
                if candidate.is_audio
            ]
            if not candidates:
                diagnostics.rejected.append(f"{profile.name}: sem URL de áudio direta")
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
                    return candidate
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
    ) -> StreamCandidate:
        diagnostics = ExtractionDiagnostics(video_id)
        max_height = max(144, int(max_height or 720))
        for profile, payload in self._payloads(video_id, diagnostics):
            candidates = [
                candidate
                for candidate in self._format_candidates(payload, profile)
                if candidate.is_video and (candidate.muxed or not progressive_only)
            ]
            if not candidates:
                diagnostics.rejected.append(f"{profile.name}: sem URL de vídeo direta")
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
                    return candidate
                diagnostics.rejected.append(
                    f"{profile.name}: itag {candidate.itag or '?'} rejeitado pelo CDN"
                )
        raise StreamExtractionError(
            f"Não foi possível obter um stream de vídeo reproduzível. {diagnostics.details()}",
            diagnostics,
        )
