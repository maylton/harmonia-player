"""The LRC lyrics format: line timestamps, metadata, offset and enhanced word tags."""

from __future__ import annotations

import re

from .lyrics_words import parse_word_tags
from .models import LyricLine

_TIMESTAMP = re.compile(
    r"\[(?:(?P<hours>\d+):)?(?P<minutes>\d{1,3}):(?P<seconds>\d{2})(?:[.:](?P<fraction>\d{1,3}))?\]"
)
_METADATA = re.compile(r"^\[(?:ar|al|ti|by|re|ve|length|la):.*\]$", re.IGNORECASE)
_OFFSET = re.compile(r"^\[offset:([+-]?\d+)\]$", re.IGNORECASE)


def parse_lrc(value: str) -> list[LyricLine]:
    """Parse common LRC/enhanced-LRC timestamps and apply the embedded offset."""
    offset_ms = 0
    parsed: list[LyricLine] = []
    for raw_line in (value or "").replace("\r\n", "\n").splitlines():
        line = raw_line.strip()
        offset = _OFFSET.match(line)
        if offset:
            offset_ms = int(offset.group(1))
            continue
        if _METADATA.match(line):
            continue
        matches = list(_TIMESTAMP.finditer(line))
        if not matches:
            continue
        text = _TIMESTAMP.sub("", line).strip()
        for match in matches:
            hours = int(match.group("hours") or 0)
            minutes = int(match.group("minutes"))
            seconds = int(match.group("seconds"))
            fraction = match.group("fraction") or "0"
            millis = int(fraction.ljust(3, "0")[:3])
            start_ms = max(0, ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis + offset_ms)
            # Word tags are absolute, so a line repeated at several times
            # keeps them only at its first.
            shown, words = parse_word_tags(text, start_ms, offset_ms)
            if match is not matches[0]:
                words = ()
            parsed.append(LyricLine(start_ms, shown.strip() or "♪", words=words))
    # Several providers emit duplicate timestamp/text pairs.
    unique = {(line.start_ms, line.text): line for line in parsed}
    return sorted(unique.values(), key=lambda entry: entry.start_ms)
