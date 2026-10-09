"""Synced lyrics: highlight the active line and scroll it into view."""

from __future__ import annotations

import time

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from .gtk_lyric_words import LyricWordHighlighter
from .lyrics_state import active_lyric_index
from .ui import set_css_class


class WindowLyricsFollowMixin:
    def _lyric_words(self) -> LyricWordHighlighter:
        highlighter = getattr(self, "_word_highlighter", None)
        if highlighter is None:
            highlighter = self._word_highlighter = LyricWordHighlighter(
                lambda: self._playback_position_us() // 1000 + self.lyrics_offset_ms
            )
        return highlighter

    def _update_synced_lyrics(self, position_ms: int, *, allow_backward: bool = False) -> None:
        document = self.current_lyrics_document
        if not document or not document.synced:
            return
        active = active_lyric_index(
            document.synced,
            position_ms,
            self.lyrics_offset_ms,
            floor_at_zero=False,
        )
        # GStreamer can briefly report an older/zero position while a network
        # stream is buffering. Lyrics naturally move forward during playback,
        # so accepting that transient value would animate the footer back to
        # the beginning. Real user seeks opt in to backwards movement.
        if (
            not allow_backward
            and self._active_lyric_index >= 0
            and active < self._active_lyric_index
        ):
            return
        if active == self._active_lyric_index:
            return
        self._active_lyric_index = active
        self._lyric_words().follow(
            document.synced[active] if active >= 0 else None,
            [view["texts"][active] for view in self._lyric_views if active < len(view["texts"])],
        )
        for view in self._lyric_views:
            for index, row in enumerate(view["rows"]):
                set_css_class(row, "lyrics-line-active", index == active)
            if active >= 0 and self._lyric_view_visible(view):
                self._queue_lyric_follow(view, active)

    def _lyric_view_visible(self, view: dict) -> bool:
        """The expanded player's lyrics tab, or the footer popover, is open."""
        if view["expanded"]:
            return (
                self.expanded_revealer.get_reveal_child()
                and self.expanded_stack.get_visible_child_name() == "lyrics"
            )
        return self.lyrics_button.get_active()

    def _follow_visible_lyric_views(self) -> None:
        """Resume following without replacing either lyrics scroller."""
        if self._active_lyric_index < 0:
            self._update_synced_lyrics(self._playback_position_us() // 1000)
            return
        for view in self._lyric_views:
            if self._lyric_view_visible(view):
                self._queue_lyric_follow(view, self._active_lyric_index)

    def _queue_lyric_follow(self, view: dict, index: int) -> None:
        """Keep only the newest allocation-time scroll request for a view."""
        view["follow_generation"] += 1
        generation = view["follow_generation"]
        GLib.idle_add(self._follow_lyric_line, view, index, generation)

    @staticmethod
    def _lyric_scroll_destination(
        row_top: float,
        row_height: float,
        viewport_height: float,
        lower: float,
        upper: float,
        *,
        expanded: bool,
    ) -> float:
        """Place expanded lyrics centrally and footer lyrics slightly above center."""
        anchor = 0.50 if expanded else 0.42
        target = row_top + row_height / 2 - viewport_height * anchor
        return max(lower, min(target, max(lower, upper - viewport_height)))

    def _follow_lyric_line(
        self, view: dict, index: int, follow_generation: int | None = None
    ) -> bool:
        if follow_generation is not None and follow_generation != view["follow_generation"]:
            return GLib.SOURCE_REMOVE
        scroll = view.get("scroll")
        if scroll is None or index >= len(view["rows"]):
            return GLib.SOURCE_REMOVE
        scroll_content = scroll.get_child()
        if scroll_content is None:
            return GLib.SOURCE_REMOVE
        ok, bounds = view["rows"][index].compute_bounds(scroll_content)
        adjustment = scroll.get_vadjustment()
        if not ok or adjustment.get_page_size() <= 1:
            return GLib.SOURCE_REMOVE
        # GTK reports bounds after the scrolled-window transform, therefore Y
        # is relative to the visible viewport once the adjustment is non-zero.
        # Convert it back to a stable content coordinate before calculating the
        # next destination; otherwise consecutive lines oscillate toward zero.
        row_top = bounds.get_y() + adjustment.get_value()
        destination = self._lyric_scroll_destination(
            row_top,
            bounds.get_height(),
            adjustment.get_page_size(),
            adjustment.get_lower(),
            adjustment.get_upper(),
            expanded=view["expanded"],
        )
        self._animate_lyric_scroll(view, adjustment, destination)
        return GLib.SOURCE_REMOVE

    def _animate_lyric_scroll(
        self,
        view: dict,
        adjustment: Gtk.Adjustment,
        destination: float,
        duration_ms: int = 420,
    ) -> None:
        """Animate the adjustment without stealing keyboard focus from the player."""
        view["generation"] += 1
        generation = view["generation"]
        start = adjustment.get_value()
        distance = destination - start
        if abs(distance) < 1:
            return
        started = time.monotonic()

        def tick() -> bool:
            if generation != view["generation"]:
                return GLib.SOURCE_REMOVE
            progress = min(1.0, (time.monotonic() - started) * 1000 / duration_ms)
            eased = 1 - (1 - progress) ** 3
            adjustment.set_value(start + distance * eased)
            return GLib.SOURCE_CONTINUE if progress < 1 else GLib.SOURCE_REMOVE

        view["animation"] = GLib.timeout_add(16, tick)
