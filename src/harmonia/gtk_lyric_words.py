"""Karaoke-style lyrics in GTK: the active line lights up word by word.

The window's progress tick (500 ms) is too coarse for words, so this keeps a
short timer of its own while the active line is timed by word, and only
repaints when another word starts and a label showing the line is on screen.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from .lyrics_words import sung_word_count, word_markup  # noqa: E402
from .models import LyricLine  # noqa: E402

TICK_MS = 60


class LyricWordHighlighter:
    def __init__(self, position_ms: Callable[[], int]) -> None:
        """``position_ms`` is the playback position with the lyrics offset applied."""
        self._position_ms = position_ms
        self._line: LyricLine | None = None
        self._labels: list[Gtk.Label] = []
        self._sung = -1
        self._source = 0

    def follow(self, line: LyricLine | None, labels: Iterable[Gtk.Label]) -> None:
        """Highlight ``line``, shown by ``labels`` (one per lyrics view)."""
        self.clear()
        if line is None or not line.words:
            return
        self._line = line
        self._labels = list(labels)
        self._paint()
        if not self._source:
            self._source = GLib.timeout_add(TICK_MS, self._tick)

    def clear(self) -> None:
        """Put the previous line back to plain text and stop following it."""
        if self._line is not None:
            for label in self._labels:
                label.set_text(self._line.text)
        self._line = None
        self._labels = []
        self._sung = -1

    def _tick(self) -> bool:
        if self._line is None:
            self._source = 0
            return GLib.SOURCE_REMOVE
        self._paint()
        return GLib.SOURCE_CONTINUE

    def _paint(self) -> None:
        line = self._line
        shown = [label for label in self._labels if label.get_mapped()]
        if line is None or not shown:
            return
        sung = sung_word_count(line, self._position_ms())
        if sung == self._sung:
            return
        self._sung = sung
        markup = word_markup(line, sung)
        for label in shown:
            label.set_markup(markup)
