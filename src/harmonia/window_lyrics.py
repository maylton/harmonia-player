"""Lyrics: loading them for the current track and building the popover view.

The active-line follower lives in window_lyrics_follow.py and the toolbar
(provider, translation, offset) in window_lyrics_tools.py.
"""

from __future__ import annotations

import logging
import threading
from html import escape

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from .i18n import _
from .models import (
    LibraryItem,
    LyricsDocument,
)
from .ui import (
    action_button,
)

LOGGER = logging.getLogger(__name__)


class WindowLyricsMixin:
    def _lyrics_toggled(self, button: Gtk.MenuButton, _pspec) -> None:
        if button.get_active():
            self._load_current_lyrics()

    def _set_lyrics_message(
        self, icon: str, title: str, description: str, retry: bool = False
    ) -> None:
        page = Adw.StatusPage(icon_name=icon, title=title, description=escape(description))
        page.set_size_request(410, 430)
        if retry:
            button = action_button(_("Tentar novamente"), role="accent")
            button.set_halign(Gtk.Align.CENTER)
            button.connect("clicked", lambda *_: self._load_current_lyrics(force=True))
            page.set_child(button)
        self.lyrics_popover.set_child(page)
        self._set_expanded_lyrics_message(icon, title, description)

    def _load_current_lyrics(self, force: bool = False) -> None:
        item = getattr(self, "current_item", None)
        if item is None:
            self._set_lyrics_message(
                "audio-input-microphone-symbolic",
                _("Letras"),
                _("Comece a reproduzir uma música para ver a letra."),
            )
            return

        # Opening the footer popover again must not rebuild its scroller.  Apart
        # from wasting work, replacing the adjustment resets it to its lower
        # bound just before the active-line animation starts.
        if (
            not force
            and self.current_lyrics_document is not None
            and self._lyrics_item_id == item.id
            and self._lyric_views
        ):
            self._follow_visible_lyric_views()
            return

        self._lyrics_request += 1
        request_id = self._lyrics_request
        if not force:
            cached = self.storage.load_lyrics_document(item.id, self.lyrics_provider)
            if cached:
                self._render_lyrics(item, cached)
                return

        self._set_lyrics_message("view-refresh-symbolic", _("Carregando letra…"), item.title)

        def worker():
            try:
                document = self.lyrics_resolver.fetch(
                    item, self.current_duration_ms, self.lyrics_provider
                )
                if document:
                    self.storage.save_lyrics_document(item.id, document)
                GLib.idle_add(self._lyrics_loaded, request_id, item.id, document, None)
            except Exception as exc:
                GLib.idle_add(self._lyrics_loaded, request_id, item.id, None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _lyrics_loaded(
        self,
        request_id: int,
        video_id: str,
        document: LyricsDocument | None,
        error: str | None,
    ):
        item = getattr(self, "current_item", None)
        if request_id != self._lyrics_request or item is None or item.id != video_id:
            return False
        if error:
            self._set_lyrics_message(
                "dialog-error-symbolic", _("Não foi possível carregar"), error, retry=True
            )
        elif not document:
            self._set_lyrics_message(
                "audio-input-microphone-symbolic",
                _("Letra indisponível"),
                _("Nenhum dos provedores encontrou uma letra para esta faixa."),
                retry=True,
            )
        else:
            self._render_lyrics(item, document)
        return False

    def _render_lyrics(self, item: LibraryItem, document: LyricsDocument) -> None:
        self._lyric_words().clear()
        self.current_lyrics_document = document
        self._lyrics_item_id = item.id
        for view in self._lyric_views:
            view["generation"] += 1
            view["follow_generation"] += 1
        self._lyric_views.clear()
        self._active_lyric_index = -1
        content = self._lyrics_surface(item, document, expanded=False)
        content.add_css_class("lyrics-popover")
        scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            min_content_width=410,
            min_content_height=380,
            max_content_height=520,
        )
        body = content.get_last_child()
        content.remove(body)
        scroll.set_child(body)
        if self._lyric_views and not self._lyric_views[0]["expanded"]:
            self._lyric_views[0]["scroll"] = scroll
        content.append(scroll)
        self.lyrics_popover.set_child(content)
        self._render_expanded_lyrics(item, document)
        self._update_synced_lyrics(self._playback_position_us() // 1000)

    def _lyrics_surface(
        self, item: LibraryItem, document: LyricsDocument, expanded: bool
    ) -> Gtk.Box:
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        header.add_css_class("lyrics-header")
        title = Gtk.Label(label=item.title, xalign=0, ellipsize=3, max_width_chars=48)
        title.add_css_class("expanded-lyrics-title" if expanded else "lyrics-title")
        header.append(title)
        mode = _("sincronizada") if document.is_synced else _("não sincronizada")
        subtitle = Gtk.Label(
            label=_("{provider} · Letra {mode}").format(provider=document.provider, mode=mode),
            xalign=0,
            ellipsize=3,
        )
        subtitle.add_css_class("expanded-lyrics-provider" if expanded else "lyrics-provider")
        header.append(subtitle)
        content.append(header)
        content.append(self._lyrics_actions(expanded))

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        body.add_css_class("synced-lyrics" if document.is_synced else "plain-lyrics")
        if document.is_synced:
            self._fill_synced_lyrics(body, document, expanded)
        else:
            original = Gtk.Label(
                label=document.display_text, xalign=0, yalign=0, wrap=True, selectable=True
            )
            original.set_max_width_chars(54)
            original.add_css_class("expanded-lyrics-text" if expanded else "lyrics-text")
            body.append(original)
            if document.translation:
                translated = Gtk.Label(
                    label=document.translation, xalign=0, yalign=0, wrap=True, selectable=True
                )
                translated.add_css_class("lyrics-plain-translation")
                body.append(translated)
        content.append(body)
        return content

    def _fill_synced_lyrics(self, body: Gtk.Box, document: LyricsDocument, expanded: bool) -> None:
        """One seekable row per line, registered as a view the follower scrolls."""
        if expanded:
            lead = Gtk.Box(height_request=180)
            lead.add_css_class("lyrics-breathing-space")
            body.append(lead)
        rows: list[Gtk.Button] = []
        texts: list[Gtk.Label] = []
        for line in document.synced:
            row = Gtk.Button()
            row.add_css_class("flat")
            row.add_css_class("lyrics-line")
            row.set_tooltip_text(_("Ir para {time}").format(time=self._format_time(line.start_ms)))
            row.connect("clicked", lambda _button, value=line.start_ms: self._seek_lyric(value))
            labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            original = Gtk.Label(label=line.text, xalign=0, wrap=True)
            original.add_css_class("lyrics-line-text")
            labels.append(original)
            texts.append(original)
            if line.translation:
                translated = Gtk.Label(label=line.translation, xalign=0, wrap=True)
                translated.add_css_class("lyrics-line-translation")
                labels.append(translated)
            row.set_child(labels)
            body.append(row)
            rows.append(row)
        if expanded:
            tail = Gtk.Box(height_request=240)
            tail.add_css_class("lyrics-breathing-space")
            body.append(tail)
        self._lyric_views.append(
            {
                "rows": rows,
                "texts": texts,
                "expanded": expanded,
                "body": body,
                "scroll": None,
                "animation": 0,
                "generation": 0,
                "follow_generation": 0,
            }
        )
