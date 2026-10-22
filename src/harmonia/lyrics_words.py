"""Lyrics timed word by word: enhanced LRC tags and how far each word is sung.

Enhanced LRC times each word with an inline tag, as in
``[00:12.00]<00:12.00>Hello <00:12.50>world``. Every word keeps the text up to
the next tag, spaces included, so joining the words gives the line back.
"""

from __future__ import annotations

import re

from .models import LyricLine, LyricWord

_WORD_TAG = re.compile(
    r"<(?:(?P<hours>\d+):)?(?P<minutes>\d{1,3}):(?P<seconds>\d{2})(?:[.:](?P<fraction>\d{1,3}))?>"
)
# Opacity of the words still to be sung in the active line.
UPCOMING_ALPHA = 0.45


def tag_ms(match: re.Match) -> int:
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes"))
    seconds = int(match.group("seconds"))
    millis = int((match.group("fraction") or "0").ljust(3, "0")[:3])
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def parse_word_tags(text: str, line_start_ms: int, offset_ms: int = 0) -> tuple[str, tuple]:
    """The line's text without word tags, and its words; no tags gives no words."""
    matches = list(_WORD_TAG.finditer(text))
    if not matches:
        return text, ()
    words: list[LyricWord] = []
    leading = text[: matches[0].start()]
    if leading.strip():
        words.append(LyricWord(line_start_ms, tag_ms(matches[0]) + offset_ms, leading))
    for index, match in enumerate(matches):
        following = matches[index + 1] if index + 1 < len(matches) else None
        segment = text[match.end() : following.start() if following else len(text)]
        if not segment.strip():
            continue
        start = tag_ms(match) + offset_ms
        end = tag_ms(following) + offset_ms if following else start
        words.append(LyricWord(max(0, start), max(0, end), segment))
    return line_text(words), tuple(words)


def line_text(words) -> str:
    return " ".join("".join(word.text for word in words).split())


def word_spans(line: LyricLine) -> tuple[str, list[tuple[int, int, LyricWord]]]:
    """The text a timed line shows and where each word sits in it.

    Spans are character ranges without the word's own spacing, so the
    spaces between words are never lit.
    """
    full = "".join(word.text for word in line.words)
    lead = len(full) - len(full.lstrip())
    text = full.strip()
    spans = []
    offset = -lead
    for word in line.words:
        start = offset + len(word.text) - len(word.text.lstrip())
        end = offset + len(word.text.rstrip())
        offset += len(word.text)
        start, end = max(0, start), min(len(text), end)
        if end > start:
            spans.append((start, end, word))
    return text, spans


# A word timed to no time at all (an enhanced LRC line's last word) still
# lights up over a moment instead of all at once.
MIN_WORD_MS = 300


def word_progress(word: LyricWord, position_ms: float) -> float:
    """How much of the word is sung, 0 to 1, as Metrolist's sungFactor."""
    duration = max(word.end_ms - word.start_ms, MIN_WORD_MS)
    return min(1.0, max(0.0, (position_ms - word.start_ms) / duration))


def word_wobble(word: LyricWord, position_ms: float) -> float:
    """Metrolist's wobble: up to 1 in the first 125 ms of the word, gone by 750 ms."""
    since = position_ms - word.start_ms
    if not 0 <= since <= 750:
        return 0.0
    return since / 125 if since < 125 else max(0.0, 1 - (since - 125) / 625)


def word_glow(word: LyricWord, progress: float) -> float:
    """Metrolist's impact factor: long, drawn-out words glow while sung."""
    if not 0.001 < progress < 1:
        return 0.0
    duration = max(word.end_ms - word.start_ms, MIN_WORD_MS)
    per_letter = duration / max(1, len(word.text.strip()))
    fade = min(1.0, progress * 5) * min(1.0, (1 - progress) * 8)
    impact = min(1.0, max(0.0, (per_letter - 100) / 250)) * 0.6
    impact += min(1.0, max(0.0, (duration - 300) / 1500)) * 0.4
    return min(1.0, impact) * fade
