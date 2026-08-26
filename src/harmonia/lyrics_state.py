"""Pure lyrics state rules shared by all presentation frontends."""

from __future__ import annotations

from bisect import bisect_right

from .models import LyricLine, LyricsDocument

LYRICS_PROVIDERS = ("auto", "lrclib", "youtube")
MIN_LYRICS_OFFSET_MS = -5000
MAX_LYRICS_OFFSET_MS = 5000


def normalize_lyrics_provider(value: str) -> str:
    provider = (value or "").strip().lower()
    return provider if provider in LYRICS_PROVIDERS else "auto"


def next_lyrics_provider(value: str) -> str:
    provider = normalize_lyrics_provider(value)
    return LYRICS_PROVIDERS[(LYRICS_PROVIDERS.index(provider) + 1) % len(LYRICS_PROVIDERS)]


def clamp_lyrics_offset(value: int) -> int:
    return max(MIN_LYRICS_OFFSET_MS, min(MAX_LYRICS_OFFSET_MS, int(value)))


def lyric_seek_target(start_ms: int, offset_ms: int) -> int:
    return max(0, int(start_ms) - int(offset_ms))


def active_lyric_index(
    lines: list[LyricLine],
    position_ms: int,
    offset_ms: int = 0,
) -> int:
    if not lines:
        return -1
    adjusted = max(0, int(position_ms) + int(offset_ms))
    return bisect_right([line.start_ms for line in lines], adjusted) - 1


def lyrics_copy_text(document: LyricsDocument) -> str:
    if document.synced and any(line.translation for line in document.synced):
        return "\n".join(
            f"{line.text}\n{line.translation}" if line.translation else line.text
            for line in document.synced
        )
    value = document.display_text
    if document.translation:
        value += "\n\n" + document.translation
    return value
