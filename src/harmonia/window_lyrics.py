from __future__ import annotations

import logging
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk

from .i18n import _
from .lyrics_state import (
    active_lyric_index,
    clamp_lyrics_offset,
    lyric_seek_target,
    lyrics_copy_text,
    next_lyrics_provider,
)
from .models import (
    LibraryItem,
    LyricLine,
    LyricsDocument,
)
from .ui import (
    action_button,
    style_action,
    style_icon_button,
)

LOGGER = logging.getLogger(__name__)


class WindowLyricsMixin:
    def _lyrics_toggled(self, button: Gtk.MenuButton, _pspec) -> None:
        if button.get_active():
            self._load_current_lyrics()

    def _set_lyrics_message(
        self, icon: str, title: str, description: str, retry: bool = False
    ) -> None:
        page = Adw.StatusPage(icon_name=icon, title=title, description=description)
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
            if expanded:
                lead = Gtk.Box(height_request=180)
                lead.add_css_class("lyrics-breathing-space")
                body.append(lead)
            rows: list[Gtk.Button] = []
            for line in document.synced:
                row = Gtk.Button()
                row.add_css_class("flat")
                row.add_css_class("lyrics-line")
                row.set_tooltip_text(
                    _("Ir para {time}").format(time=self._format_time(line.start_ms))
                )
                row.connect("clicked", lambda _button, value=line.start_ms: self._seek_lyric(value))
                labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                original = Gtk.Label(label=line.text, xalign=0, wrap=True)
                original.add_css_class("lyrics-line-text")
                labels.append(original)
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
                    "expanded": expanded,
                    "body": body,
                    "scroll": None,
                    "animation": 0,
                    "generation": 0,
                    "follow_generation": 0,
                }
            )
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

    def _lyrics_actions(self, expanded: bool) -> Gtk.Widget:
        bar = Adw.WrapBox(
            orientation=Gtk.Orientation.HORIZONTAL,
            child_spacing=4,
            line_spacing=4,
            natural_line_length=620 if expanded else 400,
            wrap_policy=Adw.WrapPolicy.NATURAL,
        )
        bar.add_css_class("lyrics-actions")
        provider_names = {"auto": _("Automática"), "lrclib": "LRCLIB", "youtube": "YouTube"}
        provider = Gtk.Button(
            label=_("Fonte: {provider}").format(
                provider=provider_names.get(self.lyrics_provider, _("Automática"))
            ),
            tooltip_text=_("Alternar provedor de letras"),
        )
        style_action(provider, "secondary")
        provider.connect("clicked", lambda *_: self._cycle_lyrics_provider())
        bar.append(provider)
        translate = Gtk.Button(
            icon_name="accessories-dictionary-symbolic", tooltip_text=_("Traduzir para português")
        )
        style_icon_button(translate, "sm")
        translate.connect("clicked", lambda *_: self._translate_current_lyrics())
        bar.append(translate)
        copy = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text=_("Copiar letra"))
        style_icon_button(copy, "sm")
        copy.connect("clicked", lambda *_: self._copy_current_lyrics())
        bar.append(copy)
        earlier = Gtk.Button(
            icon_name="list-remove-symbolic", tooltip_text=_("Adiantar letra em 250 ms")
        )
        style_icon_button(earlier, "sm")
        earlier.connect("clicked", lambda *_: self._change_lyrics_offset(-250))
        bar.append(earlier)
        offset = Gtk.Button(label=self._offset_label(), tooltip_text=_("Zerar ajuste de tempo"))
        style_action(offset, "secondary")
        offset.add_css_class("lyrics-offset")
        offset.connect("clicked", lambda *_: self._set_lyrics_offset(0))
        bar.append(offset)
        later = Gtk.Button(icon_name="list-add-symbolic", tooltip_text=_("Atrasar letra em 250 ms"))
        style_icon_button(later, "sm")
        later.connect("clicked", lambda *_: self._change_lyrics_offset(250))
        bar.append(later)
        return bar

    def _cycle_lyrics_provider(self) -> None:
        self.lyrics_provider = next_lyrics_provider(self.lyrics_provider)
        self.storage.set_setting("lyrics_provider", self.lyrics_provider)
        self._load_current_lyrics(force=False)

    def _offset_label(self) -> str:
        return "Sincronia 0 ms" if not self.lyrics_offset_ms else f"{self.lyrics_offset_ms:+d} ms"

    def _change_lyrics_offset(self, delta: int) -> None:
        self._set_lyrics_offset(clamp_lyrics_offset(self.lyrics_offset_ms + delta))

    def _set_lyrics_offset(self, value: int) -> None:
        self.lyrics_offset_ms = value
        self.storage.set_setting("lyrics_offset_ms", str(value))
        item = getattr(self, "current_item", None)
        if item and self.current_lyrics_document:
            self._render_lyrics(item, self.current_lyrics_document)

    def _seek_lyric(self, start_ms: int) -> None:
        position_ms = lyric_seek_target(start_ms, self.lyrics_offset_ms)
        if self.player.seek(position_ms * 1000):
            self._update_synced_lyrics(position_ms, allow_backward=True)

    def _copy_current_lyrics(self) -> None:
        document = self.current_lyrics_document
        display = Gdk.Display.get_default()
        if not document or not display:
            return
        display.get_clipboard().set(lyrics_copy_text(document))
        self.toast_overlay.add_toast(Adw.Toast(title=_("Letra copiada"), timeout=2))

    def _translate_current_lyrics(self) -> None:
        item = getattr(self, "current_item", None)
        document = self.current_lyrics_document
        if not item or not document:
            return
        if document.translation_language == "pt" and (
            document.translation or any(line.translation for line in document.synced)
        ):
            document.translation = ""
            document.translation_language = ""
            document.synced = [LyricLine(line.start_ms, line.text) for line in document.synced]
            self.storage.save_lyrics_document(item.id, document)
            self._render_lyrics(item, document)
            return
        self.toast_overlay.add_toast(Adw.Toast(title=_("Traduzindo letra…"), timeout=2))
        request_id = self._lyrics_request
        lines = [line.text for line in document.synced] or document.display_text.splitlines()

        def worker():
            try:
                result = self.translation_client.translate(lines, "pt")
                GLib.idle_add(self._lyrics_translated, request_id, item.id, result, None)
            except Exception as exc:
                GLib.idle_add(self._lyrics_translated, request_id, item.id, None, str(exc))

        threading.Thread(target=worker, daemon=True, name="lyrics-translation").start()

    def _lyrics_translated(self, request_id, video_id, result, error):
        item = getattr(self, "current_item", None)
        document = self.current_lyrics_document
        if request_id != self._lyrics_request or not item or item.id != video_id or not document:
            return False
        if error or not result or not any(result):
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=_("Falha ao traduzir: {error}").format(
                        error=error or _("resposta vazia")
                    ),
                    timeout=5,
                )
            )
            return False
        if document.synced:
            document.synced = [
                LyricLine(line.start_ms, line.text, result[index] if index < len(result) else "")
                for index, line in enumerate(document.synced)
            ]
        else:
            document.translation = "\n".join(result)
        document.translation_language = "pt"
        self.storage.save_lyrics_document(item.id, document)
        self._render_lyrics(item, document)
        self.toast_overlay.add_toast(Adw.Toast(title=_("Letra traduzida"), timeout=2))
        return False

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
        for view in self._lyric_views:
            for index, row in enumerate(view["rows"]):
                if index == active:
                    row.add_css_class("lyrics-line-active")
                else:
                    row.remove_css_class("lyrics-line-active")
            if active >= 0:
                should_follow = (
                    view["expanded"]
                    and self.expanded_revealer.get_reveal_child()
                    and self.expanded_stack.get_visible_child_name() == "lyrics"
                ) or (not view["expanded"] and self.lyrics_button.get_active())
                if should_follow:
                    self._queue_lyric_follow(view, active)

    def _follow_visible_lyric_views(self) -> None:
        """Resume following without replacing either lyrics scroller."""
        if self._active_lyric_index < 0:
            self._update_synced_lyrics(self._playback_position_us() // 1000)
            return
        for view in self._lyric_views:
            visible = (
                view["expanded"]
                and self.expanded_revealer.get_reveal_child()
                and self.expanded_stack.get_visible_child_name() == "lyrics"
            ) or (not view["expanded"] and self.lyrics_button.get_active())
            if visible:
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
