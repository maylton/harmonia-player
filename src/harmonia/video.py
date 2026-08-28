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
    stream_type: str = ""
    content_length: int | None = None
    init_range: tuple[int, int] | None = None
    index_range: tuple[int, int] | None = None
    expires_at: int | None = None
    request_headers: dict[str, str] | None = None

    def valid_at(self, timestamp: int, margin: int = 90) -> bool:
        return self.expires_at is None or timestamp + margin < self.expires_at


_VIDEO_ID_CACHE: dict[str, str] = {}
_VIDEO_STREAM_CACHE: dict[str, VideoStreamInfo] = {}
_VIDEO_CACHE_LOCK = threading.Lock()

_DURATION_SUFFIX = re.compile(r"\s*[·•]\s*(?:(?:\d+):)?\d{1,2}:\d{2}\s*$")
_DURATION_VALUE = re.compile(r"(?:(\d+):)?([0-5]?\d):([0-5]\d)\s*$")
_NON_ARTIST_SUBTITLE = re.compile(
    r"^(?:tocou|played|reproduziu|reproduzido|ouviu|ouvido)\b", re.IGNORECASE
)
_ARTIST_CONNECTORS = {"e", "and", "feat", "ft", "com"}
_NON_CANONICAL_VIDEO_MARKERS = {
    "ao vivo": 3.0,
    "audio": 2.0,
    "cover": 4.0,
    "demo": 4.0,
    "instrumental": 5.0,
    "karaoke": 5.0,
    "live": 3.0,
    "lyric": 4.0,
    "lyrics": 4.0,
    "preview": 4.0,
    "reaction": 5.0,
    "remix": 3.0,
    "reverb": 3.0,
    "slowed": 4.0,
    "snippet": 4.0,
    "sped up": 4.0,
    "visualizer": 1.0,
}
_NON_WORD = re.compile(r"[^a-z0-9]+")
_OTF_STREAM_TYPE = "FORMAT_STREAM_TYPE_OTF"


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    return _NON_WORD.sub(" ", value.casefold()).strip()


def _artist_hint(subtitle: str) -> str:
    value = _DURATION_SUFFIX.sub("", subtitle or "")
    if _NON_ARTIST_SUBTITLE.match(value.strip()):
        return ""
    return re.split(r"\s*[·•]\s*", value, maxsplit=1)[0].strip()


def _duration_hint(value: str) -> int | None:
    match = _DURATION_VALUE.search(value or "")
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return (int(hours or 0) * 60 + int(minutes)) * 60 + int(seconds)


def _candidate_score(item: LibraryItem, candidate: LibraryItem) -> float:
    wanted_title = _normalize(item.title)
    candidate_title = _normalize(candidate.title)
    wanted_artist = _normalize(_artist_hint(item.subtitle))
    candidate_subtitle = _normalize(candidate.subtitle)
    candidate_text = f"{candidate_title} {candidate_subtitle}".strip()

    score = SequenceMatcher(None, wanted_title, candidate_title).ratio() * 8.0
    if wanted_title and candidate_title == wanted_title:
        score += 7.0
    elif wanted_title and (wanted_title in candidate_title or candidate_title in wanted_title):
        score += 3.0

    if wanted_artist:
        artist_tokens = {
            token for token in wanted_artist.split() if token not in _ARTIST_CONNECTORS
        }
        candidate_tokens = set(candidate_text.split())
        if artist_tokens:
            artist_overlap = len(artist_tokens & candidate_tokens)
            score += 7.0 * artist_overlap / len(artist_tokens)
            # Search can return an unrelated upload with an exact generic
            # title. Keep it below a result that identifies the requested
            # artist in either its title or channel metadata.
            if artist_overlap == 0:
                score -= 8.0
        if wanted_artist in candidate_text:
            score += 3.0

    if "official music video" in candidate_text:
        score += 2.5
    elif "official" in candidate_title and "video" in candidate_title:
        score += 1.5
    if "videoclipe" in candidate_title or "music video" in candidate_title:
        score += 2.5
    for marker, penalty in _NON_CANONICAL_VIDEO_MARKERS.items():
        if marker in candidate_title:
            score -= penalty

    wanted_duration = _duration_hint(item.subtitle)
    candidate_duration = _duration_hint(candidate.subtitle)
    if wanted_duration is not None and candidate_duration is not None:
        score += max(0.0, 4.0 - abs(wanted_duration - candidate_duration) / 10.0)
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

    # YouTube Music already knows the exact official-video relationship for
    # many audio tracks. Prefer that server-provided OMV counterpart before
    # searching: a library item may not retain its artist metadata, and a
    # generic title can otherwise resolve to another artist's upload.
    counterpart_resolver = getattr(client, "video_counterpart", None)
    if callable(counterpart_resolver):
        with suppress(InnerTubeError):
            counterpart = counterpart_resolver(item.id)
        if counterpart:
            with _VIDEO_CACHE_LOCK:
                _VIDEO_ID_CACHE[cache_key] = counterpart
            return counterpart

    artist = _artist_hint(item.subtitle)
    query = " ".join(part for part in (item.title.strip(), artist) if part).strip()
    if not query:
        query = item.title.strip()
    groups = [client.search_category(query, "videos")]
    canonical_ranks: dict[str, int] = {}
    if artist:
        # The regular Videos shelf can hide an official clip behind a lyric
        # upload with the same visible title. Ask YouTube Music explicitly for
        # the canonical video and use the order of that shelf as a ranking
        # signal. The shelf can still contain lyric uploads, so only a
        # matching, unmarked result receives the preference.
        with suppress(InnerTubeError):
            canonical = client.search_category(f"{query} official music video", "videos")
            groups.append(canonical)
            for rank, candidate in enumerate(canonical.items):
                if candidate.id and candidate.id not in canonical_ranks:
                    canonical_ranks[candidate.id] = rank
    # Library subtitles can contain play-count metadata instead of the artist
    # (for example: "Tocou 251 mi vezes · 3:57"). If the first query does not
    # produce an exact title, retry with the title alone instead of allowing
    # that metadata to hide an otherwise valid official music video.
    if artist and not any(
        _normalize(candidate.title) == _normalize(item.title)
        for candidate in groups[0].items
        if candidate.id
    ):
        groups.append(client.search_category(item.title.strip(), "videos"))

    candidates: list[LibraryItem] = []
    seen: set[str] = set()
    for group in groups:
        for candidate in group.items:
            if candidate.id and candidate.id not in seen:
                seen.add(candidate.id)
                candidates.append(candidate)
    if not candidates:
        raise InnerTubeError(_("O YouTube Music não encontrou um vídeo para esta faixa."))

    def ranking_score(candidate: LibraryItem) -> float:
        score = _candidate_score(item, candidate)
        canonical_rank = canonical_ranks.get(candidate.id)
        if canonical_rank is not None and canonical_rank < 10:
            wanted_title = _normalize(item.title)
            candidate_title = _normalize(candidate.title)
            title_matches = wanted_title in candidate_title or candidate_title in wanted_title
            wanted_artist = _normalize(artist)
            candidate_tokens = set(f"{candidate_title} {_normalize(candidate.subtitle)}".split())
            artist_tokens = {
                token for token in wanted_artist.split() if token not in _ARTIST_CONNECTORS
            }
            artist_matches = not artist_tokens or bool(artist_tokens & candidate_tokens)
            has_non_canonical_marker = any(
                marker in candidate_title for marker in _NON_CANONICAL_VIDEO_MARKERS
            )
            if title_matches and artist_matches and not has_non_canonical_marker:
                score += 12.0 / (canonical_rank + 1)
        return score

    ranked = sorted(candidates, key=ranking_score, reverse=True)
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


def _stream_request_headers(profile: dict[str, Any]) -> dict[str, str]:
    """Headers that must travel with a media URL returned for one client profile."""
    headers = {
        "User-Agent": str(profile["user_agent"]),
        "Accept": "*/*",
    }
    if profile.get("name") == "WEB_REMIX":
        headers["Origin"] = ORIGIN
        headers["Referer"] = f"{ORIGIN}/"
    return headers


def _probe_stream(url: str, headers: dict[str, str]) -> bool:
    """Reject Googlevideo URLs that the CDN already refuses before playback."""
    hostname = (urllib.parse.urlsplit(url).hostname or "").lower()
    if not hostname.endswith("googlevideo.com"):
        return True
    request_headers = dict(headers)
    request_headers["Range"] = "bytes=0-1"
    request = urllib.request.Request(url, headers=request_headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            status = getattr(response, "status", 200)
            return status in (200, 206) and bool(response.read(1))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return False


def _video_compatibility(fmt: dict[str, Any]) -> int:
    """Prefer widely decoded H.264 MP4 when quality is otherwise equal."""
    mime = str(fmt.get("mimeType") or "").lower()
    if "video/mp4" in mime and "avc1" in mime:
        return 2
    if "video/mp4" in mime:
        return 1
    return 0


def _byte_range(fmt: dict[str, Any], key: str) -> tuple[int, int] | None:
    value = fmt.get(key) or {}
    try:
        start = int(value["start"])
        end = int(value["end"])
    except (KeyError, TypeError, ValueError):
        return None
    return (start, end) if end >= start else None


def _is_otf_video(fmt: dict[str, Any]) -> bool:
    """OTF URLs are sequential fragment protocols, not random-access media files."""
    return str(fmt.get("type") or "") == _OTF_STREAM_TYPE or bool(fmt.get("targetDurationSec"))


def _video_random_access_score(fmt: dict[str, Any], muxed: bool) -> int:
    """Rank direct formats by how safely a media player can seek them.

    Progressive formats are ordinary files. For adaptive formats, the strongest
    signal is the normal YouTube combination of contentLength + initRange +
    indexRange. OTF formats deliberately score below usable direct streams.
    """
    if _is_otf_video(fmt):
        return -1
    if muxed:
        return 4
    content_length = fmt.get("contentLength")
    init_range = _byte_range(fmt, "initRange")
    index_range = _byte_range(fmt, "indexRange")
    if content_length and init_range and index_range:
        return 3
    if content_length and index_range:
        return 2
    if content_length:
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

    Callers with a dedicated visual layer can set ``allow_video_only`` and use
    YouTube's adaptiveFormats while keeping the normal audio player untouched.
    OTF adaptive streams are excluded because their ``sq=N`` fragment protocol
    is not a random-access file and therefore cannot support GStreamer seeking.
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
        adaptive_all = [
            fmt
            for fmt in (streaming.get("adaptiveFormats") or [])
            if str(fmt.get("mimeType", "")).startswith("video/")
            and fmt.get("url")
            and int(fmt.get("height", 0) or 0) > 0
        ]
        adaptive = [fmt for fmt in adaptive_all if not _is_otf_video(fmt)]
        candidates: list[tuple[dict[str, Any], bool]] = [(fmt, True) for fmt in progressive]
        if allow_video_only:
            candidates.extend((fmt, False) for fmt in adaptive)

        if status.get("status") != "OK":
            failures.append(
                f"{profile['name']}: "
                f"{status.get('reason') or status.get('status') or 'indisponível'}"
            )
            continue
        if not candidates:
            if allow_video_only and adaptive_all:
                failures.append(f"{profile['name']}: apenas vídeo OTF não-seekable")
            else:
                missing = (
                    "sem stream de vídeo direto" if allow_video_only else "sem vídeo progressivo"
                )
                failures.append(f"{profile['name']}: {missing}")
            continue

        # Random access matters more than nominal resolution for the Music/Video
        # switch: a 480p indexed MP4 can be synchronized; a 720p OTF/sequential
        # stream cannot. Within the best seekability class, maximize quality.
        best_access = max(_video_random_access_score(fmt, muxed) for fmt, muxed in candidates)
        access_pool = [
            pair
            for pair in candidates
            if _video_random_access_score(pair[0], pair[1]) == best_access
        ]
        within_quality = [
            pair for pair in access_pool if int(pair[0].get("height", 0) or 0) <= max_height
        ]
        pool = within_quality or access_pool
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
        request_headers = _stream_request_headers(profile)
        if not _probe_stream(url, request_headers):
            failures.append(f"{profile['name']}: CDN recusou o stream direto")
            continue

        duration = selected.get("approxDurationMs")
        content_length = selected.get("contentLength")
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
            stream_type=str(selected.get("type") or ""),
            content_length=int(content_length) if content_length else None,
            init_range=_byte_range(selected, "initRange"),
            index_range=_byte_range(selected, "indexRange"),
            expires_at=_stream_expiration(url),
            request_headers=request_headers,
        )
        with _VIDEO_CACHE_LOCK:
            _VIDEO_STREAM_CACHE[cache_key] = stream
        return stream

    raise InnerTubeError(
        _("Não foi possível obter o vídeo correspondente. {details}").format(
            details="; ".join(failures)
        )
    )
