"""Karaoke-style lyrics in GTK: the active line lights up word by word.

Each synced line is a KaraokeLine, which draws its own Pango layout. While
it is the active line and its words are timed, it repaints every frame the
way Metrolist (after Apple Music) draws WordLevelLyrics: each word fills
from the left with a soft edge as it is sung, rises a little and stays up,
pulses when it starts, and long held words glow in the line's colour. The
words still to come wait at UPCOMING_ALPHA.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gsk, Gtk, Pango  # noqa: E402

from .gtk_expressive import FrameLoop, point, rect  # noqa: E402
from .lyrics_words import (  # noqa: E402
    UPCOMING_ALPHA,
    word_glow,
    word_progress,
    word_spans,
    word_wobble,
)
from .models import LyricLine  # noqa: E402

LIFT_PX = 2.0  # how far a sung word rises
EDGE_STEPS = 12  # Metrolist's gradient edge, in strips
GLOW_RADIUS = 12.0
CLIP_PAD = 8.0  # room above and below a word for its lift, pulse and glow


def _with_alpha(color, alpha: float):
    tinted = color.copy()
    tinted.alpha = color.alpha * alpha
    return tinted


class KaraokeLine(Gtk.Widget):
    """A wrapping lyric line that can light up word by word."""

    __gtype_name__ = "HarmoniaKaraokeLine"

    def __init__(self, line: LyricLine) -> None:
        super().__init__()
        self.add_css_class("lyrics-line-text")
        self.line = line
        if line.words:
            text, self._spans = word_spans(line)
        else:
            text, self._spans = line.text, []
        self._layout = self.create_pango_layout(text)
        self._layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        self._segments: list[list[tuple[float, float, float, float]]] | None = None
        self._position_ms: Callable[[], float] | None = None
        self._redraw = FrameLoop(self, lambda _elapsed: None)

    # --- Activity ---------------------------------------------------------

    def activate(self, position_ms: Callable[[], float]) -> None:
        """Light the words up following ``position_ms`` until deactivate()."""
        if self._spans:
            self._position_ms = position_ms
            self._redraw.set_running(True)

    def deactivate(self) -> None:
        self._position_ms = None
        self._redraw.set_running(False)
        self.queue_draw()

    # --- Layout -----------------------------------------------------------

    def do_get_request_mode(self) -> Gtk.SizeRequestMode:
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_measure(self, orientation, for_size):
        self._layout.context_changed()
        if orientation == Gtk.Orientation.HORIZONTAL:
            self._layout.set_width(1)  # one word per line: the widest word
            minimum = self._layout.get_pixel_size()[0]
            self._layout.set_width(-1)
            return minimum, self._layout.get_pixel_size()[0], -1, -1
        self._layout.set_width(for_size * Pango.SCALE if for_size > 0 else -1)
        height = self._layout.get_pixel_size()[1]
        return height, height, -1, -1

    def do_size_allocate(self, width: int, _height: int, _baseline: int) -> None:
        self._layout.set_width(width * Pango.SCALE)
        self._segments = None

    def _word_segments(self) -> list[list[tuple[float, float, float, float]]]:
        """Each word's rectangles (x0, y0, x1, y1), one per line it covers."""
        if self._segments is not None:
            return self._segments
        text = self._layout.get_text()
        offsets = [0]
        for char in text:
            offsets.append(offsets[-1] + len(char.encode()))
        segments = []
        for start, end, _word in self._spans:
            lines: dict[int, list[float]] = {}
            for index in range(start, end):
                rect = self._layout.index_to_pos(offsets[index])
                x0, x1 = sorted((rect.x, rect.x + rect.width))
                box = lines.setdefault(rect.y, [x0, rect.y, x1, rect.y + rect.height])
                box[0], box[2] = min(box[0], x0), max(box[2], x1)
            segments.append(
                [tuple(value / Pango.SCALE for value in box) for _y, box in sorted(lines.items())]
            )
        self._segments = segments
        return segments

    # --- Drawing ----------------------------------------------------------

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        color = self.get_color()
        if self._position_ms is None:
            snapshot.append_layout(self._layout, color)
            return
        position = self._position_ms()
        upcoming = _with_alpha(color, UPCOMING_ALPHA)
        for (_start, _end, word), segments in zip(self._spans, self._word_segments(), strict=True):
            progress = word_progress(word, position)
            wobble = word_wobble(word, position)
            # Rises as it starts and stays up for the rest of the line.
            lift = LIFT_PX * min(1.0, max(0.0, (position - word.start_ms) / 200))
            glow = word_glow(word, progress)
            total = sum(x1 - x0 for x0, _y0, x1, _y1 in segments) or 1
            filled = total * progress
            for x0, y0, x1, y1 in segments:
                width = x1 - x0
                lit = min(width, max(0.0, filled))
                filled -= width
                self._snapshot_segment(
                    snapshot, (x0, y0, x1, y1), lit, lift, wobble, glow, color, upcoming
                )

    def _snapshot_segment(self, snapshot, box, lit, lift, wobble, glow, color, upcoming):
        x0, y0, x1, y1 = box
        width = x1 - x0
        snapshot.save()
        # Grow from the bottom centre, as Metrolist's pivot.
        center = (x0 + x1) / 2
        snapshot.translate(point(center, y1 - lift))
        snapshot.scale(1 + wobble * 0.025, 1 + wobble * 0.015)
        snapshot.translate(point(-center, -y1))
        top, height = y0 - CLIP_PAD, y1 - y0 + 2 * CLIP_PAD
        # Solid up to a soft edge that fades into the dimmed rest.
        edge = min(lit, width * 0.45) if lit < width else 0.0
        if lit < width:
            snapshot.push_clip(rect(x0 + lit - edge, top, width - lit + edge, height))
            snapshot.append_layout(self._layout, upcoming)
            snapshot.pop()
        if lit > 0:
            if glow > 0.01:
                shadow = Gsk.Shadow()
                shadow.color = _with_alpha(color, min(0.4, 0.35 * glow))
                shadow.dx = shadow.dy = 0
                shadow.radius = GLOW_RADIUS * glow
                snapshot.push_shadow([shadow])
            snapshot.push_clip(rect(x0, top, lit - edge, height))
            snapshot.append_layout(self._layout, color)
            snapshot.pop()
            for step in range(EDGE_STEPS if edge else 0):
                left = x0 + lit - edge + step * edge / EDGE_STEPS
                snapshot.push_clip(rect(left, top, edge / EDGE_STEPS + 0.5, height))
                snapshot.append_layout(
                    self._layout, _with_alpha(color, 1 - (step + 0.5) / EDGE_STEPS)
                )
                snapshot.pop()
            if glow > 0.01:
                snapshot.pop()
        snapshot.restore()


class LyricWordHighlighter:
    def __init__(self, position_ms: Callable[[], int]) -> None:
        """``position_ms`` is the playback position with the lyrics offset applied."""
        self._position_ms = position_ms
        self._lines: list[KaraokeLine] = []

    def follow(self, line: LyricLine | None, lines: Iterable[KaraokeLine]) -> None:
        """Light up ``line``, shown by ``lines`` (one per lyrics view)."""
        self.clear()
        if line is None or not line.words:
            return
        self._lines = list(lines)
        for widget in self._lines:
            widget.activate(self._position_ms)

    def clear(self) -> None:
        """Put the previous line back to plain text."""
        for widget in self._lines:
            widget.deactivate()
        self._lines = []
