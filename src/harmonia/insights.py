from __future__ import annotations

import re
import time
from dataclasses import dataclass

from .models import LibraryItem


@dataclass(frozen=True, slots=True)
class RankedMedia:
    item: LibraryItem
    plays: int
    listened_ms: int


@dataclass(frozen=True, slots=True)
class RankedArtist:
    name: str
    plays: int


@dataclass(frozen=True, slots=True)
class PlaybackInsights:
    year: int
    total_plays: int
    unique_tracks: int
    listened_ms: int
    top_tracks: tuple[RankedMedia, ...]
    top_artists: tuple[RankedArtist, ...]
    monthly_plays: tuple[int, ...]

    @property
    def listened_minutes(self) -> int:
        return self.listened_ms // 60_000


def artist_from_subtitle(subtitle: str) -> str:
    value = re.split(r"\s*[•·]\s*", subtitle or "", maxsplit=1)[0].strip()
    return value or "YouTube Music"


def current_year() -> int:
    return time.localtime().tm_year
