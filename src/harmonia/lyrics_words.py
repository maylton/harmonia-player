"""Lyrics timed word by word: enhanced LRC tags and how far each word is sung.

Enhanced LRC times each word with an inline tag, as in
``[00:12.00]<00:12.00>Hello <00:12.50>world``. Every word keeps the text up to
the next tag, spaces included, so joining the words gives the line back.
"""

from __future__ import annotations

import math
import re

from .models import LyricLine, LyricWord

_WORD_TAG = re.compile(
    r"<(?:(?P<hours>\d+):)?(?P<minutes>\d{1,3}):(?P<seconds>\d{2})(?:[.:](?P<fraction>\d{1,3}))?>"
)
# Opacity of the active line's letters still to be sung (Metrolist's focusedAlpha);
# a word's letters brighten towards 1 as the word is sung.
FOCUSED_ALPHA = 0.3


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


def letter_progress(word: LyricWord, position_ms: float, index: int, length: int) -> float:
    """How lit the ``index``-th of a word's ``length`` letters is, 0 to 1 (charLp).

    The fill sweeps the word letter by letter: each letter takes its share of
    the word's time. The space after a word counts as its last letter.
    """
    duration = max(word.end_ms - word.start_ms, 100)
    sung = (position_ms - word.start_ms) / duration
    return min(1.0, max(0.0, (sung - index / length) * length))


def letter_nudge(progress: float, letter: float) -> float:
    """The bump a letter takes as the fill crosses it, while its word is sung."""
    if not 0 < progress < 1:
        return 0.0
    return 0.038 * math.sin(letter * math.pi) * math.exp(-3 * letter)


def hyphen_groups(words) -> dict[int, tuple[int, int, int, int]]:
    """Syllables joined by hyphens ("lo-", "ve"): word index -> (position,
    size, start_ms, end_ms) of its group, for words in groups of two or more."""
    groups: dict[int, tuple[int, int, int, int]] = {}
    current: list[int] = []
    for index, word in enumerate(words):
        current.append(index)
        if word.text.rstrip().endswith("-") and not word.text.endswith(" "):
            continue
        if len(current) > 1:
            start, end = words[current[0]].start_ms, words[current[-1]].end_ms
            for position, member in enumerate(current):
                groups[member] = (position, len(current), start, end)
        current = []
    return groups


def crescendo(group: tuple[int, int, int, int], progress: float, position_ms: float) -> float:
    """Metrolist's swell of a hyphenated word: each syllable a little larger,
    the last one springing up while sung and the group settling once done."""
    position, size, _start, end = group
    base = position * 0.012
    peak, decay, frequency = 0.06, 3.5, 5.0
    after = min(1.0, max(0.0, (position_ms - end) / 600))
    if after > 0:
        spring = (base + peak) * math.exp(-decay * after)
        return spring * math.cos(frequency * after * math.pi) * (1 - after)
    if position == size - 1:
        bounce = math.exp(-decay * progress) * math.cos(frequency * progress * math.pi)
        return base + peak * (1 - bounce * (1 - progress))
    return base + (0.02 * (1 - progress) if progress > 0 else 0.0)


def wave(
    group: tuple[int, int, int, int], position_ms: float, wall_ms: float, letter: int
) -> float:
    """The vertical ripple through a hyphenated word while it is sung, in pixels."""
    _position, _size, start, end = group
    fade = min(1.0, max(0.0, (position_ms - start) / 200))
    fade *= min(1.0, max(0.0, (end - position_ms) / 200))
    if fade <= 0.01:
        return 0.0
    return math.sin(wall_ms * 0.006 + letter * 0.4) * 3.24 * fade
