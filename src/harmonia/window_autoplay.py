"""Autoplay: when the queue runs out, YouTube Music's radio of the last track continues it."""

from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from .i18n import _
from .models import LibraryItem
from .playback_state import filter_new_recommendations, radio_seed_for_autoplay
from .ui import set_icon_selected


class WindowAutoplayMixin:
    """Fills ``related_items`` from the radio and plays them when the queue ends."""

    def _toggle_autoplay(self, button: Gtk.Button) -> None:
        self.autoplay_enabled = not self.autoplay_enabled
        self._waiting_for_autoplay = False
        if self.autoplay_enabled:
            set_icon_selected(button, True)
            button.set_tooltip_text(_("Reprodução automática ativada"))
            self.toast_overlay.add_toast(Adw.Toast(title=_("Reprodução automática ativada")))
            self._ensure_autoplay()
        else:
            self._autoplay_request += 1
            self._autoplay_loading = False
            set_icon_selected(button, False)
            button.set_tooltip_text(_("Reprodução automática desativada"))
            self.toast_overlay.add_toast(Adw.Toast(title=_("Reprodução automática desativada")))
        self._save_playback_state()

    def _ensure_autoplay(self, force: bool = False) -> None:
        if not self.autoplay_enabled or not self.queue or self._autoplay_loading:
            return
        if self.related_items:
            if self._waiting_for_autoplay:
                self._waiting_for_autoplay = False
                self._promote_related(self.related_items[0], play_next=False)
                self._play_next()
            return
        seed = radio_seed_for_autoplay(self.queue, self.queue_index, force=force)
        if seed is None:
            return
        self._autoplay_request += 1
        request_id = self._autoplay_request
        self._autoplay_loading = True

        def worker():
            try:
                recommendations = self.youtube.radio(seed.id)
                GLib.idle_add(self._autoplay_loaded, request_id, recommendations, None)
            except Exception as exc:
                GLib.idle_add(self._autoplay_loaded, request_id, None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _autoplay_loaded(
        self, request_id: int, recommendations: list[LibraryItem] | None, error: str | None
    ):
        if request_id != self._autoplay_request:
            return False
        self._autoplay_loading = False
        if error:
            if self._waiting_for_autoplay:
                self.toast_overlay.add_toast(
                    Adw.Toast(
                        title=_("Não foi possível continuar a rádio: {error}").format(error=error),
                        timeout=5,
                    )
                )
            self._waiting_for_autoplay = False
            return False
        self.related_items = filter_new_recommendations(self.queue, recommendations)
        self._render_queue()
        self._save_playback_state()
        if self._waiting_for_autoplay and self.related_items:
            self._waiting_for_autoplay = False
            self._promote_related(self.related_items[0], play_next=False)
            self._play_next()
        elif self._waiting_for_autoplay:
            self._waiting_for_autoplay = False
            self.toast_overlay.add_toast(
                Adw.Toast(title=_("A rádio não encontrou novas músicas"), timeout=4)
            )
        return False
