"""The expanded player: showing it, its artwork, lyrics and up-next tabs."""

from __future__ import annotations

import re
from html import escape

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib

from . import queue_view
from .gtk_video import AUDIO_FRAME
from .i18n import _
from .models import LibraryItem, LyricsDocument

# Full screen fades the header and the controls once the pointer rests this long.
FULLSCREEN_IDLE_SECONDS = 3
IDLE_CSS_CLASS = "expanded-idle"
# Share of the screen's height the artwork takes in full screen.
FULLSCREEN_COVER_SHARE = 0.55


class WindowExpandedPlayerMixin:
    def _show_expanded_player(self) -> None:
        if getattr(self, "current_item", None) is None:
            return
        self._refresh_expanded_player()
        self.expanded_stack.set_visible_child_name("music")
        self.player_bar.set_visible(False)
        self.expanded_revealer.set_reveal_child(True)
        self.expanded_revealer.set_can_target(True)
        GLib.idle_add(self._focus_expanded_close)

    def _focus_expanded_close(self) -> bool:
        # Not grab_focus() itself: its True would keep the idle source running.
        self.expanded_close_button.grab_focus()
        return GLib.SOURCE_REMOVE

    def _hide_expanded_player(self) -> None:
        if self.is_fullscreen():
            self.unfullscreen()
        self.expanded_revealer.set_reveal_child(False)
        self.player_bar.set_visible(True)

    def _expanded_key_pressed(self, _controller, keyval, _keycode, state) -> bool:
        revealed = self.expanded_revealer.get_reveal_child()
        modifiers = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK
        if self.is_fullscreen():
            self._wake_fullscreen_controls()
        if keyval == Gdk.KEY_Escape and self.is_fullscreen():
            self.unfullscreen()
            return True
        if keyval == Gdk.KEY_Escape and revealed:
            self._hide_expanded_player()
            return True
        # "F" only over the expanded player, which has nothing to type in.
        letter = keyval in (Gdk.KEY_f, Gdk.KEY_F) and revealed and not state & modifiers
        if keyval == Gdk.KEY_F11 or letter:
            self._toggle_fullscreen()
            return True
        return False

    def _toggle_fullscreen(self) -> None:
        """The expanded player over the whole screen, as YouTube Music's."""
        if self.is_fullscreen():
            self.unfullscreen()
            return
        self._show_expanded_player()
        if self.expanded_revealer.get_reveal_child():  # nothing plays otherwise
            self.fullscreen()

    def _fullscreen_changed(self) -> None:
        full = self.is_fullscreen()
        self.expanded_up_next_slot.set_visible(not full)
        button = self.expanded_fullscreen_button
        button.set_icon_name("view-restore-symbolic" if full else "view-fullscreen-symbolic")
        button.set_tooltip_text(_("Sair da tela cheia (F)") if full else _("Tela cheia (F)"))
        if hasattr(self, "_media_visual_frame"):
            self._sync_media_mode_ui()
        self._wake_fullscreen_controls()

    def _expanded_media_scale(self) -> float:
        """How much the artwork and the video grow in full screen."""
        surface = self.get_surface()
        monitor = self.get_display().get_monitor_at_surface(surface) if surface else None
        if not self.is_fullscreen() or monitor is None:
            return 1.0
        return max(1.0, monitor.get_geometry().height * FULLSCREEN_COVER_SHARE / AUDIO_FRAME[1])

    def _wake_fullscreen_controls(self) -> None:
        if getattr(self, "_fullscreen_idle_source", 0):
            GLib.source_remove(self._fullscreen_idle_source)
        self._fullscreen_idle_source = 0
        self.expanded_surface.remove_css_class(IDLE_CSS_CLASS)
        self.expanded_surface.set_cursor(None)
        if self.is_fullscreen():
            self._fullscreen_idle_source = GLib.timeout_add_seconds(
                FULLSCREEN_IDLE_SECONDS, self._rest_fullscreen_controls
            )

    def _rest_fullscreen_controls(self) -> bool:
        self._fullscreen_idle_source = 0
        self.expanded_surface.add_css_class(IDLE_CSS_CLASS)
        self.expanded_surface.set_cursor_from_name("none")
        return GLib.SOURCE_REMOVE

    def _expanded_page_changed(self, stack: Adw.ViewStack, _pspec) -> None:
        page = stack.get_visible_child_name()
        if page == "lyrics":
            self._load_current_lyrics()

    def _refresh_expanded_player(self) -> None:
        item = getattr(self, "current_item", None)
        if item is None:
            return
        self.expanded_title.set_label(item.title)
        self.expanded_explicit.set_visible(item.explicit)
        subtitle = re.sub(r"\s*[·•]\s*(?:(?:\d+):)?\d{1,2}:\d{2}\s*$", "", item.subtitle or "")
        self.expanded_subtitle.show_item(item, subtitle or "YouTube Music")
        self.expanded_cover.set_paintable(None)
        if item.thumbnail:
            # Reuse an already-cached thumbnail immediately, then replace it
            # with the dedicated high-resolution variant when available.
            self._load_artwork(item.thumbnail, self.expanded_cover)
            self._load_artwork(item.thumbnail, self.expanded_cover, size=1024)
        self._refresh_current_like_from_library()
        self._render_expanded_up_next()

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

    def _render_expanded_up_next(self) -> None:
        if not hasattr(self, "expanded_up_next"):
            return
        while child := self.expanded_up_next.get_first_child():
            self.expanded_up_next.remove(child)
        self.expanded_up_next.append(
            queue_view.up_next_content(
                self.queue,
                self.queue_index,
                self.related_items,
                self._queue_actions(select=self._select_expanded_queue_item),
                lambda item: self._square_cover(item, size=44, fixed=True),
            )
        )

    def _select_expanded_queue_item(self, position: int) -> None:
        self.queue_index = position
        self._render_queue()
        self.play_item(self.queue[position])
