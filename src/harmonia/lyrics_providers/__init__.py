"""Lyrics services, one module each, independent from GTK and Qt."""

from .common import clean_title, lyrics_metadata
from .lrclib import LrcLibClient
from .lyricsplus import LyricsPlusClient, is_word_synced

__all__ = [
    "LrcLibClient",
    "LyricsPlusClient",
    "clean_title",
    "is_word_synced",
    "lyrics_metadata",
]
