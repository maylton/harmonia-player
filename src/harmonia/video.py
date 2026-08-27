from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from contextlib import suppress
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from .i18n import _
from .innertube import (
    API_URL,
    ORIGIN,
    PLAYER_CLIENTS,
    InnerTubeClient,
    InnerTubeError,
    sapisid_hash,
)
from .models import LibraryItem


@dataclass(frozen=True, slots=True)
class VideoStreamInfo:
    """One direct YouTube video stream suitable for GStreamer playback."""

    url: str
    video_id: str
    duration_ms: int | None
    client: str
    mime_type: str = ""
    bitrate: int = 0
    itag: int | None = None
    width: int = 0
    height: int = 0
    fps: int = 0
    muxed: bool = True
    expires_at: int | None = None

    def valid_at(self, timestamp: int, margin: int = 90) -> bool:
        return self.expires_at is None or timestamp + margin < self.expires_at


_VIDEO_ID_CACHE: dict[str, str] = {}
_VIDEO_STREAM_CACHE: dict[str, VideoStreamInfo] = {}
_VIDEO_CACHE_LOCK = threading.Lock()

_DURATION_SUFFIX = re.compile(r"\s*[·•]\s*(?:(?:\d+):)?\d{1,2}:\d{2}\s*$")
_NON_WORD = re.compile(r"[^a-z0-9]+")


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    return _NON_WORD.sub(" ", value.casefold()).strip()


def _artist_hint(subtitle: str) -> str:
    value = _DURATION_SUFFIX.sub("", subtitle or "")
    return re.split(r"\s*[·•]\s*", value, maxsplit=1)[0].strip()


def _candidate_score(item: LibraryItem, candidate: LibraryItem) -> float:
    wanted_title = _normalize(item.title)
    candidate_title = _normalize(candidate.title)
    wanted_artist = _normalize(_artist_hint(item.subtitle))
    candidate_subtitle = _normalize(candidate.subtitle)

    score = SequenceMatcher(None, wanted_title, candidate_title).ratio() * 8.0
    if wanted_title and candidate_title == wanted_title:
        score += 7.0
    elif wanted_title and (wanted_title in candidate_title or candidate_title in wanted_title):
        score += 3.0

    if wanted_artist:
        artist_tokens = set(wanted_artist.split())
        subtitle_tokens = set(candidate_subtitle.split())
        if artist_tokens:
            score += 5.0 * len(artist_tokens & subtitle_tokens) / len(artist_tokens)
        if wanted_artist in candidate_subtitle:
            score += 3.0

    normalized = f"{candidate_title} {candidate_subtitle}"
    if "official video" in normalized or "official music video" in normalized:
        score += 1.5
    if any(token in normalized for token in ("lyrics", "lyric video", "karaoke", "reaction")):
        score -= 1.25
    return score


def find_video_variant(client: InnerTubeClient, item: LibraryItem, *, force: bool = False) -> str:
    """Resolve the YouTube Music video that best represents *item*."""
    if not item.id or item.id.startswith("local:"):
        raise InnerTubeError(_("Esta faixa local não possui um vídeo do YouTube associado."))
    if item.kind == "videos":
        return item.id

    cache_key = item.id
    if not force:
        with _VIDEO_CACHE_LOCK:
            cached = _VIDEO_ID_CACHE.get(cache_key)
        if cached:
            return cached

    artist = _artist_hint(item.subtitle)
    query = " ".join(part for part in (item.title.strip(), artist) if part).strip()
    if not query:
        query = item.title.strip()
    group = client.search_category(query, "videos")
    candidates = [candidate for candidate in group.items if candidate.id]
    if not candidates:
        raise InnerTubeError(_("O YouTube Music não encontrou um vídeo para esta faixa."))

    ranked = sorted(
        candidates, key=lambda candidate: _candidate_score(item, candidate), reverse=True
    )
    selected = ranked[0]
    if _candidate_score(item, selected) < 4.0:
        raise InnerTubeError(_("Nenhum vídeo correspondente foi encontrado para esta faixa."))

    with _VIDEO_CACHE_LOCK:
        _VIDEO_ID_CACHE[cache_key] = selected.id
    return selected.id


def _stream_expiration(url: str) -> int | None:
    values = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("expire")
    try:
        return int(values[0]) if values else None
    except (TypeError, ValueError):
        return None


def _player_payload(
    client: InnerTubeClient, video_id: str, profile: dict[str, Any]
) -> dict[str, Any] | None:
    version = client.client_version if profile.get("live_version") else profile["version"]
    yt_client = {
        "clientName": profile["name"],
        "clientVersion": version,
        "userAgent": profile["user_agent"],
        "hl": client.hl,
        "gl": client.gl,
        **profile.get("context", {}),
        **({"visitorData": client.visitor_data} if client.visitor_data else {}),
    }
    body = {
        "context": {"client": yt_client, "user": {}},
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
            "User-Agent": profile["user_agent"],
            "X-YouTube-Client-Name": profile["id"],
            "X-YouTube-Client-Version": version,
            **({"X-Goog-Visitor-Id": client.visitor_data} if client.visitor_data else {}),
            **(
                {
                    "Cookie": client.cookie,
                    "Authorization": sapisid_hash(client.cookie),
                    "Origin": ORIGIN,
                    "X-Origin": ORIGIN,
                }
                if profile.get("authenticated") and client.authenticated
                else {}
            ),
        },
    )
    for attempt in range(2):
        try:
            with client._open(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code not in (408, 429, 500, 502, 503, 504) or attempt == 1:
                return None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt == 1:
                return None
        time.sleep(0.2 * (2**attempt))
    return None


def _video_compatibility(fmt: dict[str, Any]) -> int:
    """Prefer widely decoded H.264 MP4 when quality is otherwise equal."""
    mime = str(fmt.get("mimeType") or "").lower()
    if "video/mp4" in mime and "avc1" in mime:
        return 2
    if "video/mp4" in mime:
        return 1
    return 0


def resolve_video_stream(
    client: InnerTubeClient,
    item: LibraryItem,
    *,
    max_height: int = 720,
    force: bool = False,
    allow_video_only: bool = False,
) -> VideoStreamInfo:
    """Resolve a direct stream for the matching music video.

    GTK's current single-playbin implementation keeps ``allow_video_only``
    disabled and therefore receives only muxed audio+video formats. The Qt
    frontend owns a dedicated muted video layer, so it can also consume
    ``adaptiveFormats`` video-only streams and keep the main audio transport
    untouched.
    """
    video_id = find_video_variant(client, item, force=force)
    max_height = max(144, int(max_height or 720))
    mode_key = "adaptive" if allow_video_only else "muxed"
    cache_key = f"{client.gl}:{max_height}:{mode_key}:{video_id}"
    if not force:
        with _VIDEO_CACHE_LOCK:
            cached = _VIDEO_STREAM_CACHE.get(cache_key)
        if cached and cached.valid_at(int(time.time())):
            return cached
    else:
        with _VIDEO_CACHE_LOCK:
            _VIDEO_STREAM_CACHE.pop(cache_key, None)

    failures: list[str] = []
    with suppress(InnerTubeError):
        client._bootstrap()

    for profile in PLAYER_CLIENTS:
        payload = _player_payload(client, video_id, profile)
        if not payload:
            failures.append(f"{profile['name']}: sem resposta")
            continue
        status = payload.get("playabilityStatus") or {}
        streaming = payload.get("streamingData") or {}
        progressive = [
            fmt
            for fmt in (streaming.get("formats") or [])
            if str(fmt.get("mimeType", "")).startswith("video/")
            and fmt.get("url")
            and int(fmt.get("height", 0) or 0) > 0
        ]
        adaptive = [
            fmt
            for fmt in (streaming.get("adaptiveFormats") or [])
            if str(fmt.get("mimeType", "")).startswith("video/")
            and fmt.get("url")
            and int(fmt.get("height", 0) or 0) > 0
        ]
        candidates: list[tuple[dict[str, Any], bool]] = [
            (fmt, True) for fmt in progressive
        ]
        if allow_video_only:
            candidates.extend((fmt, False) for fmt in adaptive)

        if status.get("status") != "OK" or not candidates:
            missing = "sem stream de vídeo direto" if allow_video_only else "sem vídeo progressivo"
            failures.append(
                f"{profile['name']}: {status.get('reason') or status.get('status') or missing}"
            )
            continue

        within_quality = [
            pair for pair in candidates if int(pair[0].get("height", 0) or 0) <= max_height
        ]
        pool = within_quality or candidates
        if within_quality:
            selected, muxed = max(
                pool,
                key=lambda pair: (
                    int(pair[0].get("height", 0) or 0),
                    _video_compatibility(pair[0]),
                    int(pair[0].get("fps", 0) or 0),
                    int(pair[0].get("bitrate", 0) or 0),
                ),
            )
        else:
            selected, muxed = min(pool, key=lambda pair: int(pair[0].get("height", 0) or 0))

        url = str(selected["url"])
        duration = selected.get("approxDurationMs")
        stream = VideoStreamInfo(
            url=url,
            video_id=video_id,
            duration_ms=int(duration) if duration else None,
            client=str(profile["name"]),
            mime_type=str(selected.get("mimeType") or ""),
            bitrate=int(selected.get("bitrate", 0) or 0),
            itag=int(selected["itag"]) if selected.get("itag") is not None else None,
            width=int(selected.get("width", 0) or 0),
            height=int(selected.get("height", 0) or 0),
            fps=int(selected.get("fps", 0) or 0),
            muxed=muxed,
            expires_at=_stream_expiration(url),
        )
        with _VIDEO_CACHE_LOCK:
            _VIDEO_STREAM_CACHE[cache_key] = stream
        return stream

    raise InnerTubeError(
        _("Não foi possível obter o vídeo correspondente. {details}").format(
            details="; ".join(failures)
        )
    )
