from __future__ import annotations

import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from .i18n import _
from .innertube import InnerTubeClient, InnerTubeError
from .models import LibraryItem
from .stream_extractor import InnerTubeStreamExtractor, StreamExtractionError


@dataclass(frozen=True, slots=True)
class VideoStreamInfo:
    """One direct YouTube video stream suitable for desktop playback."""

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
        candidates,
        key=lambda candidate: _candidate_score(item, candidate),
        reverse=True,
    )
    selected = ranked[0]
    if _candidate_score(item, selected) < 4.0:
        raise InnerTubeError(_("Nenhum vídeo correspondente foi encontrado para esta faixa."))

    with _VIDEO_CACHE_LOCK:
        _VIDEO_ID_CACHE[cache_key] = selected.id
    return selected.id


def resolve_video_stream(
    client: InnerTubeClient,
    item: LibraryItem,
    *,
    max_height: int = 720,
    force: bool = False,
    allow_video_only: bool = False,
) -> VideoStreamInfo:
    """Resolve a validated direct stream for the matching music video.

    All player-response/client fallback logic now lives in
    :mod:`harmonia.stream_extractor`, shared with audio extraction. GTK asks for
    progressive/muxed media; Qt can accept a separate video-only adaptive stream
    because its visual layer remains muted and synchronized to the main audio transport.
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

    try:
        candidate = InnerTubeStreamExtractor(client).extract_video(
            video_id,
            max_height=max_height,
            progressive_only=not allow_video_only,
            force=force,
        )
    except StreamExtractionError as exc:
        raise InnerTubeError(str(exc)) from exc

    stream = VideoStreamInfo(
        url=candidate.url,
        video_id=video_id,
        duration_ms=candidate.duration_ms,
        client=candidate.client,
        mime_type=candidate.mime_type,
        bitrate=candidate.bitrate,
        itag=candidate.itag,
        width=candidate.width,
        height=candidate.height,
        fps=candidate.fps,
        muxed=candidate.muxed,
        expires_at=candidate.expires_at,
    )
    with _VIDEO_CACHE_LOCK:
        _VIDEO_STREAM_CACHE[cache_key] = stream
    return stream
