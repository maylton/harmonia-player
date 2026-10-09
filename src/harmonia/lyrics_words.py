"""Lyrics timed word by word: enhanced LRC tags and the sung part of a line.

Enhanced LRC times each word with an inline tag, as in
``[00:12.00]<00:12.00>Hello <00:12.50>world``. Every word keeps the text up to
the next tag, spaces included, so joining the words gives the line back.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from html import escape

from .models import LyricLine, LyricWord

_WORD_TAG = re.compile(
    r"<(?:(?P<hours>\d+):)?(?P<minutes>\d{1,3}):(?P<seconds>\d{2})(?:[.:](?P<fraction>\d{1,3}))?>"
)
# Opacity of the words still to be sung in the active line.
UPCOMING_ALPHA = "45%"


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


def sung_word_count(line: LyricLine, position_ms: int) -> int:
    """How many words of the line have started at ``position_ms``."""
    return bisect_right([word.start_ms for word in line.words], position_ms)


def word_markup(line: LyricLine, sung: int) -> str:
    """Pango markup of the line with the words still to come dimmed."""
    full = "".join(word.text for word in line.words)
    boundary = len("".join(word.text for word in line.words[:sung]))
    start = len(full) - len(full.lstrip())
    end = len(full.rstrip())
    boundary = max(start, min(boundary, end))
    sung_part, upcoming = full[start:boundary], full[boundary:end]
    markup = escape(sung_part, quote=False)
    if upcoming:
        markup += f'<span alpha="{UPCOMING_ALPHA}">{escape(upcoming, quote=False)}</span>'
    return markup
