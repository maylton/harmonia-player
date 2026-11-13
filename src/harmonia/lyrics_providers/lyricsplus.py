"""LyricsPlus: lyrics timed word by word (Apple Music's), or by line (Musixmatch's).

A community API with several mirrors; each answers
``/v2/lyrics/get?title=&artist=&duration=<s>&album=`` with the lines in
milliseconds and, when timed by word, a ``syllabus`` of words that carry their
own spacing. Background vocals are left out of the highlighted words.
"""

from __future__ import annotations

import logging
import urllib.request
from collections.abc import Callable

from ..lyrics_words import line_text
from ..models import LibraryItem, LyricLine, LyricsDocument, LyricWord
from .common import clean_title, get_json, lyrics_metadata

LOGGER = logging.getLogger(__name__)


class LyricsPlusClient:
    NAME = "LyricsPlus"
    # Metrolist's mirrors; the one that last answered is asked first.
    SERVERS = (
        "https://lyricsplus.binimum.org",
        "https://lyricsplus.atomix.one",
        "https://lyricsplus.prjktla.my.id",
        "https://lyricsplus-seven.vercel.app",
    )
    TIMEOUT = 5  # seconds per mirror: a dead one held every track for 8
    _last_working: str | None = None

    def __init__(self, opener: Callable[..., object] = urllib.request.urlopen) -> None:
        self.opener = opener

    def lyrics(self, item: LibraryItem, duration_ms: int = 0) -> LyricsDocument | None:
        """The best document the mirrors have: timed by word if any has it."""
        artist, album = lyrics_metadata(item)
        if not artist:
            return None
        params = {"title": clean_title(item.title), "artist": artist}
        if duration_ms > 0:
            params["duration"] = str(round(duration_ms / 1000))
        if album:
            params["album"] = album
        fallback = None
        failures: list[Exception] = []
        last = LyricsPlusClient._last_working
        servers = sorted(self.SERVERS, key=lambda server: server != last)
        for server in servers:
            try:
                payload = get_json(
                    self.opener, f"{server}/v2/lyrics/get", params, timeout=self.TIMEOUT
                )
            except Exception as exc:  # one mirror down must not hide the others
                LOGGER.debug("LyricsPlus %s falhou", server, exc_info=True)
                failures.append(exc)
                continue
            LyricsPlusClient._last_working = server
            document = self.document(payload)
            if document is not None and is_word_synced(document):
                return document
            fallback = fallback or document
        if fallback is None and len(failures) == len(self.SERVERS):
            raise failures[0]
        return fallback

    @classmethod
    def document(cls, payload) -> LyricsDocument | None:
        if not isinstance(payload, dict):
            return None
        timed_by_word = str(payload.get("type") or "").lower() == "word"
        lines: list[LyricLine] = []
        for entry in payload.get("lyrics") or []:
            if not isinstance(entry, dict):
                continue
            words = _words(entry) if timed_by_word else ()
            text = line_text(words) if words else " ".join(str(entry.get("text") or "").split())
            if text:
                lines.append(LyricLine(_ms(entry.get("time")), text, words=words))
        if not lines:
            return None
        lines.sort(key=lambda line: line.start_ms)
        plain = "\n".join(line.text for line in lines)
        return LyricsDocument(plain, cls.NAME, lines)


def is_word_synced(document: LyricsDocument) -> bool:
    return any(line.words for line in document.synced)


def _words(entry: dict) -> tuple[LyricWord, ...]:
    words = []
    for syllable in entry.get("syllabus") or []:
        if not isinstance(syllable, dict) or syllable.get("isBackground"):
            continue
        text = str(syllable.get("text") or "")
        if not text.strip():
            continue
        start = _ms(syllable.get("time"))
        words.append(LyricWord(start, start + _ms(syllable.get("duration")), text))
    return tuple(words)


def _ms(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
