"""Telling whether a search result is a given song: titles, artists and length.

Shared by the music-video lookup (video.py) and by the audio fallback for
age-restricted tracks (innertube/alternatives.py). Toolkit-free.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .models import LibraryItem

DURATION_SUFFIX = re.compile(r"\s*[·•]\s*(?:(?:\d+):)?\d{1,2}:\d{2}\s*$")
_DURATION_VALUE = re.compile(r"(?:(\d+):)?([0-5]?\d):([0-5]\d)(?!\d)")
_NON_ARTIST_SUBTITLE = re.compile(
    r"^(?:tocou|played|reproduziu|reproduzido|ouviu|ouvido)\b", re.IGNORECASE
)
ARTIST_CONNECTORS = {"e", "and", "feat", "ft", "com", "part", "x"}
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
# Never the same recording, whatever the title says.
_OTHER_RECORDING = (
    "ao vivo",
    "live",
    "cover",
    "karaoke",
    "instrumental",
    "remix",
    "slowed",
    "sped up",
    "reverb",
    "8d",
    "nightcore",
    "acapella",
    "coreografia",
    "choreography",
    "dance",
    "reaction",
    "tutorial",
)
_BRACKETS = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
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


def _core_title(title: str) -> str:
    """The title without "(part. X)", "[Official Video]" and similar."""
    return normalize(_BRACKETS.sub(" ", title or "")) or normalize(title)


def _artist_tokens(artists: str) -> set[str]:
    return {token for token in normalize(artists).split() if token not in ARTIST_CONNECTORS}


def same_recording(
    title: str,
    artists: str,
    duration_s: int | None,
    candidate: LibraryItem,
    *,
    tolerance_s: int = 2,
) -> bool:
    """Whether *candidate* is very likely the same recording of the song.

    Strict on purpose: it decides what plays in place of the track, so a
    live take, a cover or a dance video of the same song must not pass.
    """
    wanted, found = _core_title(title), _core_title(candidate.title)
    if not wanted or not found:
        return False
    if not (wanted == found or wanted in found or found in wanted) and (
        SequenceMatcher(None, wanted, found).ratio() < 0.85
    ):
        return False
    original = normalize(title)
    text = normalize(f"{candidate.title} {candidate.subtitle}")
    if any(f" {marker} " in f" {text} " and marker not in original for marker in _OTHER_RECORDING):
        return False
    wanted_artists = _artist_tokens(artists)
    credited = _artist_tokens(f"{artist_hint(candidate.subtitle)} {candidate.title}")
    if wanted_artists and len(wanted_artists & credited) < max(1, len(wanted_artists) // 2):
        return False
    found_duration = duration_hint(candidate.subtitle)
    if duration_s is None or found_duration is None:
        return False
    return abs(found_duration - duration_s) <= tolerance_s
