"""The expanded player: showing it, its artwork, lyrics and up-next tabs."""

from __future__ import annotations

import re
from html import escape

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib

from . import queue_view
from .models import LibraryItem, LyricsDocument


class WindowExpandedPlayerMixin:
    def _show_expanded_player(self) -> None:
        if getattr(self, "current_item", None) is None:
            return
        self._refresh_expanded_player()
        self.expanded_stack.set_visible_child_name("music")
        self.player_bar.set_visible(False)
        self.expanded_revealer.set_reveal_child(True)
        self.expanded_revealer.set_can_target(True)
        GLib.idle_add(self.expanded_close_button.grab_focus)

    def _hide_expanded_player(self) -> None:
        self.expanded_revealer.set_reveal_child(False)
        self.player_bar.set_visible(True)

    def _expanded_key_pressed(self, _controller, keyval, _keycode, _state) -> bool:
        if keyval == Gdk.KEY_Escape and self.expanded_revealer.get_reveal_child():
            self._hide_expanded_player()
            return True
        return False

    def _expanded_page_changed(self, stack: Adw.ViewStack, _pspec) -> None:
        page = stack.get_visible_child_name()
        if page == "lyrics":
            self._load_current_lyrics()
        elif page == "related":
            self._render_expanded_related()

    def _refresh_expanded_player(self) -> None:
        item = getattr(self, "current_item", None)
        if item is None:
            return
        self.expanded_title.set_label(item.title)
        self.expanded_explicit.set_visible(item.explicit)
        subtitle = re.sub(r"\s*[·•]\s*(?:(?:\d+):)?\d{1,2}:\d{2}\s*$", "", item.subtitle or "")
        self.expanded_subtitle.show_item(item, subtitle or "YouTube Music")
        if item.thumbnail:
            self.expanded_cover.set_paintable(None)
            self.expanded_backdrop_base.set_paintable(None)
            self.expanded_backdrop.set_paintable(None)
            # Reuse an already-cached thumbnail immediately, then replace it
            # with the dedicated high-resolution variant when available.
            self._load_artwork(item.thumbnail, self.expanded_cover)
            self._load_artwork(item.thumbnail, self.expanded_cover, size=1024)
            self._load_artwork(item.thumbnail, self.expanded_backdrop_base, size=1280)
            self._load_artwork(item.thumbnail, self.expanded_backdrop, size=1280)
            self._load_artwork(item.thumbnail, self.ambient_background, size=1280)
        else:
            self.expanded_cover.set_paintable(None)
            self.expanded_backdrop_base.set_paintable(None)
            self.expanded_backdrop.set_paintable(None)
            self.ambient_background.set_paintable(None)
        self._refresh_current_like_from_library()
        self._render_expanded_related()

    def _set_expanded_lyrics_message(self, icon: str, title: str, description: str) -> None:
        if not hasattr(self, "expanded_lyrics_container"):
            return
        while child := self.expanded_lyrics_container.get_first_child():
            self.expanded_lyrics_container.remove(child)
        # The description is Pango markup; callers pass plain text such as a
        # track title, which may hold a bare "&".
        status = Adw.StatusPage(icon_name=icon, title=title, description=escape(description))
        status.set_vexpand(True)
        self.expanded_lyrics_container.append(status)

    def _render_expanded_lyrics(self, item: LibraryItem, document: LyricsDocument) -> None:
        while child := self.expanded_lyrics_container.get_first_child():
            self.expanded_lyrics_container.remove(child)
        clamp = Adw.Clamp(maximum_size=760, tightening_threshold=620)
        box = self._lyrics_surface(item, document, expanded=True)
        if self._lyric_views and self._lyric_views[-1]["expanded"]:
            self._lyric_views[-1]["scroll"] = self.expanded_lyrics_scroll
        clamp.set_child(box)
        self.expanded_lyrics_container.append(clamp)

    def _render_expanded_related(self) -> None:
        if not hasattr(self, "expanded_related_container"):
            return
        while child := self.expanded_related_container.get_first_child():
            self.expanded_related_container.remove(child)
        self.expanded_related_container.append(
            queue_view.expanded_content(
                self.queue,
                self.queue_index,
                self.related_items,
                self._queue_actions(select=self._select_expanded_queue_item),
            )
        )

    def _select_expanded_queue_item(self, position: int) -> None:
        self.queue_index = position
        self._render_queue()
        self.play_item(self.queue[position])
