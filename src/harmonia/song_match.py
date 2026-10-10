"""Reading search results for the music-video lookup (video.py): titles,
artists and length. Toolkit-free.
"""

from __future__ import annotations

import re
import unicodedata

DURATION_SUFFIX = re.compile(r"\s*[·•]\s*(?:(?:\d+):)?\d{1,2}:\d{2}\s*$")
_DURATION_VALUE = re.compile(r"(?:(\d+):)?([0-5]?\d):([0-5]\d)(?!\d)")
_NON_ARTIST_SUBTITLE = re.compile(
    r"^(?:tocou|played|reproduziu|reproduzido|ouviu|ouvido)\b", re.IGNORECASE
)
ARTIST_CONNECTORS = {"e", "and", "feat", "ft", "com"}
# Words that mark another performance or edit of a song, with how strongly the
# video lookup penalises them.
NON_CANONICAL_MARKERS = {
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


def normalize(value: str) -> str:
    """Lower case, no accents, words separated by single spaces."""
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    return _NON_WORD.sub(" ", value.casefold()).strip()


def artist_hint(subtitle: str) -> str:
    """The artists at the start of a result's subtitle, if it starts with them."""
    value = DURATION_SUFFIX.sub("", subtitle or "")
    if _NON_ARTIST_SUBTITLE.match(value.strip()):
        return ""
    return re.split(r"\s*[·•]\s*", value, maxsplit=1)[0].strip()


def duration_hint(value: str) -> int | None:
    """Seconds of the last m:ss (or h:mm:ss) in a subtitle."""
    matches = list(_DURATION_VALUE.finditer(value or ""))
    if not matches:
        return None
    hours, minutes, seconds = matches[-1].groups()
    return (int(hours or 0) * 60 + int(minutes)) * 60 + int(seconds)
