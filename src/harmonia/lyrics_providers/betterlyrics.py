"""BetterLyrics: Apple Music's lyrics, timed by word, as TTML (Metrolist's first provider).

``/getLyrics?s=<title>&a=<artists>&d=<seconds>&al=<album>`` answers JSON with
a ``ttml`` document. Without an API key it only answers queries already in its
cache, which Metrolist's users fill: the query is built as Metrolist builds
it (title without brackets, every artist joined by ", ", duration in seconds),
and a miss (401, 404) is simply no lyrics here.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable

from ..lyrics_words import line_text
from ..models import LibraryItem, LyricLine, LyricsDocument, LyricWord
from .common import get_json, lyrics_metadata

TTML = "{http://www.w3.org/ns/ttml}"
TTM = "{http://www.w3.org/ns/ttml#metadata}"


class BetterLyricsClient:
    API = "https://lyrics-api.boidu.dev/getLyrics"
    NAME = "BetterLyrics"

    def __init__(self, opener: Callable[..., object] = urllib.request.urlopen) -> None:
        self.opener = opener

    def lyrics(self, item: LibraryItem, duration_ms: int = 0) -> LyricsDocument | None:
        artists = query_artists(item)
        if not artists or duration_ms <= 0:
            return None  # the cache is keyed with the duration
        params = {"s": search_title(item.title), "a": artists, "d": str(round(duration_ms / 1000))}
        _artist, album = lyrics_metadata(item)
        if album:
            params["al"] = album
        try:
            payload = get_json(self.opener, self.API, params, timeout=6)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 404):  # not in its cache, or not found
                return None
            raise
        ttml = payload.get("ttml") if isinstance(payload, dict) else None
        return parse_ttml(ttml) if ttml else None


def search_title(title: str) -> str:
    """Metrolist's cleanTitleForSearch: everything in brackets goes."""
    return re.sub(r"\s*[(\[].*?[)\]]", "", title).strip()


def query_artists(item: LibraryItem) -> str:
    names = [name for kind, name, _id in item.links if kind == "artist" and name]
    return ", ".join(names) if names else lyrics_metadata(item)[0]


def _seconds(value: str | None) -> float | None:
    """TTML clock values: "12.5", "1:02.5", "1:00:02.5" or "12.5s"."""
    if not value:
        return None
    value = value.strip().rstrip("s")
    try:
        parts = [float(part) for part in value.split(":")]
    except ValueError:
        return None
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def _ms(value: str | None) -> int | None:
    seconds = _seconds(value)
    return None if seconds is None else max(0, round(seconds * 1000))


def _spans(element: ET.Element) -> tuple[list[LyricWord], list[ET.Element]]:
    """A line's timed words (each with the spacing after it), and its
    background-vocal spans, which become lines of their own."""
    words: list[LyricWord] = []
    background: list[ET.Element] = []
    for child in element:
        if child.tag != f"{TTML}span":
            continue
        if child.get(f"{TTM}role") == "x-bg":
            background.append(child)
        else:
            start, end = _ms(child.get("begin")), _ms(child.get("end"))
            text = "".join(child.itertext())
            if start is not None and text.strip():
                words.append(LyricWord(start, end if end is not None else start, text))
        if child.tail and words:
            last = words[-1]
            words[-1] = LyricWord(last.start_ms, last.end_ms, last.text + child.tail)
    return words, background


def _line(element: ET.Element, start: int | None) -> LyricLine | None:
    words, _background = _spans(element)
    if words:
        text = line_text(words)
        start = words[0].start_ms if start is None else start
        return LyricLine(start, text, words=tuple(words)) if text else None
    text = " ".join("".join(element.itertext()).split())
    return LyricLine(start, text) if text and start is not None else None


def parse_ttml(ttml: str) -> LyricsDocument | None:
    try:
        root = ET.fromstring(ttml)
    except ET.ParseError:
        return None
    lines: list[LyricLine] = []
    for paragraph in root.iter(f"{TTML}p"):
        line = _line(paragraph, _ms(paragraph.get("begin")))
        if line is not None:
            lines.append(line)
        # Background vocals, in parentheses, as a line of their own.
        for span in _spans(paragraph)[1]:
            extra = _line(span, _ms(span.get("begin")))
            if extra is not None:
                lines.append(extra)
    if not lines:
        return None
    lines.sort(key=lambda line: line.start_ms)
    return LyricsDocument("\n".join(line.text for line in lines), BetterLyricsClient.NAME, lines)
