"""Lyrics services, one module each, independent from GTK and Qt."""

from .betterlyrics import BetterLyricsClient
from .common import clean_title, duration_from_subtitle, lyrics_metadata
from .lrclib import LrcLibClient
from .lyricsplus import LyricsPlusClient, is_word_synced

__all__ = [
    "BetterLyricsClient",
    "LrcLibClient",
    "LyricsPlusClient",
    "clean_title",
    "duration_from_subtitle",
    "is_word_synced",
    "lyrics_metadata",
]
