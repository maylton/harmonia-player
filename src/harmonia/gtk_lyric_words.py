"""Karaoke-style lyrics in GTK: the active line lights up letter by letter.

Each synced line is a KaraokeLine, which draws its own Pango layout. While it
is the active line and its words are timed, it repaints every frame the way
Metrolist's LyricsLine draws WordLevelLyrics: each letter (grapheme) is drawn
on its own, filled from the left with a soft edge as the word reaches it; it
bumps as the fill crosses it and pushes the letters after it aside; a word
swells for a moment when it starts, hyphenated syllables grow and ripple, and
long held words glow. The letters still to come wait at FOCUSED_ALPHA and
brighten as their word is sung.

Drawing each letter by itself keeps every stroke on its own line: drawing the
whole layout clipped to a word let the clip reach the wrapped lines above and
below, which showed cut pieces of them.
"""

from __future__ import annotations

import time
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gsk, Gtk, Pango  # noqa: E402

from .gtk_expressive import FrameLoop, point, rect  # noqa: E402
from .lyrics_words import (  # noqa: E402
    FOCUSED_ALPHA,
    crescendo,
    hyphen_groups,
    letter_nudge,
    letter_progress,
    wave,
    word_glow,
    word_progress,
    word_spans,
    word_wobble,
)
from .models import LyricLine  # noqa: E402

EDGE_STEPS = 12  # Metrolist's gradient edge, in strips
EDGE_SHARE = 0.45  # of a letter's width
GLOW_RADIUS = 12.0
LETTER_SPACING = -0.5  # pixels, as Metrolist's letterSpacing
LINE_HEIGHT = 1.3  # times the font size


def _with_alpha(color, alpha: float):
    tinted = color.copy()
    tinted.alpha = color.alpha * alpha
    return tinted


def _joined_script(text: str) -> bool:
    """Right-to-left and Indic text join its glyphs: drawn letter by letter,
    it would show seams, so it lights up word by word instead."""
    for char in text:
        if unicodedata.bidirectional(char) in ("R", "AL") or "ऀ" <= char <= "෿":
            return True
    return False


@dataclass(slots=True)
class _Letter:
    text: str
    line: int
    x: float
    y: float  # where its own layout is drawn, baseline matched to the line's
    width: float
    height: float
    word: int  # index into the spans, -1 for spacing between words
    index: int  # place in its word, the space after it included
    length: int


class KaraokeLine(Gtk.Widget):
    """A wrapping lyric line that can light up letter by letter."""

    __gtype_name__ = "HarmoniaKaraokeLine"

    def __init__(self, line: LyricLine, *, centered: bool = False) -> None:
        super().__init__()
        self.add_css_class("lyrics-line-text")
        self.line = line
        if line.words:
            text, self._spans = word_spans(line)
        else:
            text, self._spans = line.text, []
        self._centered = centered
        self._joined = _joined_script(text)
        self._groups = hyphen_groups([word for _start, _end, word in self._spans])
        self._layout = self._new_layout(text)
        self._layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        if centered:
            self._layout.set_alignment(Pango.Alignment.CENTER)
        self._letters: list[_Letter] | None = None
        self._glyphs: dict[str, Pango.Layout] = {}
        self._position_ms: Callable[[], float] | None = None
        self._redraw = FrameLoop(self, lambda _elapsed: None)

    def _new_layout(self, text: str) -> Pango.Layout:
        layout = self.create_pango_layout(text)
        attributes = Pango.AttrList()
        attributes.insert(Pango.attr_letter_spacing_new(round(LETTER_SPACING * Pango.SCALE)))
        layout.set_attributes(attributes)
        return layout

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

    def do_css_changed(self, change) -> None:
        Gtk.Widget.do_css_changed(self, change)
        self._glyphs.clear()
        self._letters = None

    def do_get_request_mode(self) -> Gtk.SizeRequestMode:
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def _apply_line_height(self) -> None:
        """Lines LINE_HEIGHT times the font size apart, as Metrolist's lineHeight."""
        context = self._layout.get_context()
        font = context.get_font_description() or Pango.FontDescription()
        metrics = context.get_metrics(font, None)
        height = (metrics.get_ascent() + metrics.get_descent()) / Pango.SCALE
        size = font.get_size() / Pango.SCALE or height
        self._layout.set_line_spacing(LINE_HEIGHT * size / height if height else 0)

    def do_measure(self, orientation, for_size):
        self._layout.context_changed()
        self._apply_line_height()
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
        self._letters = None

    def _glyph(self, text: str) -> Pango.Layout:
        layout = self._glyphs.get(text)
        if layout is None:
            layout = self._glyphs[text] = self._new_layout(text)
        return layout

    def _letter_boxes(self) -> list[_Letter]:
        """Each grapheme of the line, where it sits and which word it belongs to."""
        if self._letters is not None:
            return self._letters
        text = self._layout.get_text()
        offsets = [0]
        for char in text:
            offsets.append(offsets[-1] + len(char.encode()))
        baselines = []
        lines = self._layout.get_iter()
        while True:
            baselines.append(lines.get_baseline() / Pango.SCALE)
            if not lines.next_line():
                break
        # Which word each character belongs to; the space after a word too.
        owner = [(-1, 0, 1)] * len(text)
        for word, (start, end, _timed) in enumerate(self._spans):
            length = end - start + (1 if end < len(text) and text[end] == " " else 0)
            for index in range(length):
                owner[start + index] = (word, index, length)
        attributes = self._layout.get_log_attrs()
        letters = []
        start = 0
        for end in range(1, len(text) + 1):
            if end < len(text) and not attributes[end].is_cursor_position:
                continue
            cluster = text[start:end]
            box = self._layout.index_to_pos(offsets[start])
            line, _x = self._layout.index_to_line_x(offsets[start], False)
            glyph = self._glyph(cluster)
            x0, x1 = sorted((box.x, box.x + box.width))
            word, index, length = owner[start]
            letters.append(
                _Letter(
                    cluster,
                    line,
                    x0 / Pango.SCALE,
                    baselines[min(line, len(baselines) - 1)] - glyph.get_baseline() / Pango.SCALE,
                    (x1 - x0) / Pango.SCALE,
                    glyph.get_pixel_size()[1],
                    word,
                    index,
                    length,
                )
            )
            start = end
        self._letters = letters
        return letters

    # --- Drawing ----------------------------------------------------------

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        color = self.get_color()
        if self._position_ms is None:
            snapshot.append_layout(self._layout, color)
            return
        position = self._position_ms()
        if self._joined:
            self._snapshot_words(snapshot, position, color)
            return
        letters = self._letter_boxes()
        words = [word for _start, _end, word in self._spans]
        progress = [word_progress(word, position) for word in words]
        wobble = [word_wobble(word, position) for word in words]
        scales = [self._scale(letter, words, progress, wobble, position) for letter in letters]
        # Grown letters push the rest of their line aside; centred lines
        # spread the push on both sides.
        pushes: dict[int, float] = {}
        for letter, (scale_x, _y) in zip(letters, scales, strict=True):
            pushes[letter.line] = pushes.get(letter.line, 0.0) + letter.width * (scale_x - 1)
        shift = {line: -total / 2 if self._centered else 0.0 for line, total in pushes.items()}
        wall = time.monotonic() * 1000
        for number, (letter, (scale_x, scale_y)) in enumerate(zip(letters, scales, strict=True)):
            self._snapshot_letter(
                snapshot, number, letter, scale_x, scale_y, shift[letter.line],
                words, progress, position, wall, color,
            )  # fmt: skip
            shift[letter.line] += letter.width * (scale_x - 1)

    def _scale(self, letter, words, progress, wobble, position) -> tuple[float, float]:
        if letter.word < 0:
            return 1.0, 1.0
        word = words[letter.word]
        lit = letter_progress(word, position, letter.index, letter.length)
        sung = position > word.end_ms
        nudge = 0.0 if sung else letter_nudge(progress[letter.word], lit)
        group = self._groups.get(letter.word)
        swell = crescendo(group, progress[letter.word], position) if group else 0.0
        return (
            1 + wobble[letter.word] * 0.025 + swell + nudge * 0.3,
            1 + wobble[letter.word] * 0.015 + swell + nudge,
        )

    def _snapshot_letter(
        self, snapshot, number, letter, scale_x, scale_y, shift, words, progress, position,
        wall, color,
    ) -> None:  # fmt: skip
        glyph = self._glyph(letter.text)
        if not letter.text.strip():
            return
        if letter.word < 0:
            snapshot.save()
            snapshot.translate(point(letter.x + shift, letter.y))
            snapshot.append_layout(glyph, _with_alpha(color, FOCUSED_ALPHA))
            snapshot.restore()
            return
        word = words[letter.word]
        sung = position > word.end_ms
        lit = letter_progress(word, position, letter.index, letter.length)
        done = progress[letter.word]
        group = self._groups.get(letter.word)
        ripple = wave(group, position, wall, number) if group else 0.0
        width, height = letter.width, letter.height
        snapshot.save()
        snapshot.translate(point(letter.x + shift, letter.y + ripple))
        # Grow from the letter's bottom centre, as Metrolist's pivot.
        snapshot.translate(point(width / 2, height))
        snapshot.scale(scale_x, scale_y)
        snapshot.translate(point(-width / 2, -height))
        glow = 0.0 if sung else word_glow(word, done)
        if glow > 0.01:
            shadow = Gsk.Shadow()
            shadow.color = _with_alpha(color, min(0.4, 0.35 * glow))
            shadow.dx = shadow.dy = 0
            shadow.radius = GLOW_RADIUS * glow
            snapshot.push_shadow([shadow])
        base = 1.0 if sung or lit > 0.99 else FOCUSED_ALPHA + (1 - FOCUSED_ALPHA) * done
        snapshot.append_layout(glyph, _with_alpha(color, base))
        if not sung and 0 < lit < 1:
            filled = width * lit
            edge = max(1.0, width * EDGE_SHARE)
            solid = max(0.0, filled - edge)
            if solid > 0:
                snapshot.push_clip(rect(0, 0, solid, height))
                snapshot.append_layout(glyph, color)
                snapshot.pop()
            for step in range(EDGE_STEPS):
                left = solid + step * edge / EDGE_STEPS
                right = min(filled, solid + (step + 1) * edge / EDGE_STEPS + 0.5)
                if right > left:
                    snapshot.push_clip(rect(left, 0, right - left, height))
                    snapshot.append_layout(glyph, _with_alpha(color, 1 - (step + 0.5) / EDGE_STEPS))
                    snapshot.pop()
        if glow > 0.01:
            snapshot.pop()
        snapshot.restore()

    def _snapshot_words(self, snapshot, position, color) -> None:
        """Joined scripts: the whole line, each word lit through its own boxes."""
        snapshot.append_layout(self._layout, _with_alpha(color, FOCUSED_ALPHA))
        text = self._layout.get_text()
        offsets = [0]
        for char in text:
            offsets.append(offsets[-1] + len(char.encode()))
        for start, end, word in self._spans:
            done = word_progress(word, position)
            if done <= 0:
                continue
            alpha = 1.0 if position > word.end_ms else FOCUSED_ALPHA + (1 - FOCUSED_ALPHA) * done
            for index in range(start, end):
                box = self._layout.index_to_pos(offsets[index])
                x0, x1 = sorted((box.x, box.x + box.width))
                snapshot.push_clip(
                    rect(x0 / Pango.SCALE, box.y / Pango.SCALE, (x1 - x0) / Pango.SCALE,
                         box.height / Pango.SCALE)
                )  # fmt: skip
                snapshot.append_layout(self._layout, _with_alpha(color, alpha))
                snapshot.pop()


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
