"""The lyrics toolbar: provider, translation, copying and timing offset."""

from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk

from .i18n import _
from .lyrics_state import (
    clamp_lyrics_offset,
    lyric_seek_target,
    lyrics_copy_text,
    next_lyrics_provider,
    remove_translation,
    with_translations,
)
from .ui import style_action, style_icon_button


class WindowLyricsToolsMixin:
    def _lyrics_actions(self, expanded: bool) -> Gtk.Widget:
        bar = Adw.WrapBox(
            orientation=Gtk.Orientation.HORIZONTAL,
            child_spacing=4,
            line_spacing=4,
            natural_line_length=620 if expanded else 400,
            wrap_policy=Adw.WrapPolicy.NATURAL,
        )
        bar.add_css_class("lyrics-actions")
        provider_names = {
            "auto": _("Automática"),
            "lyricsplus": "LyricsPlus",
            "lrclib": "LRCLIB",
            "youtube": "YouTube",
        }
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
        if not self.lyrics_offset_ms:
            return _("Sincronia 0 ms")
        return f"{self.lyrics_offset_ms:+d} ms"

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
        if remove_translation(document):
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
                    title=_("Não foi possível traduzir: {error}").format(
                        error=error or _("resposta vazia")
                    ),
                    timeout=5,
                )
            )
            return False
        if document.synced:
            document.synced = with_translations(document.synced, result)
        else:
            document.translation = "\n".join(result)
        document.translation_language = "pt"
        self.storage.save_lyrics_document(item.id, document)
        self._render_lyrics(item, document)
        self.toast_overlay.add_toast(Adw.Toast(title=_("Letra traduzida"), timeout=2))
        return False
