"""When playback fails: renew the stream once, then say why, with a report to copy."""

from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib

from .i18n import _
from .playback_report import playback_report


class WindowPlaybackRecoveryMixin:
    """A stream that fails is resolved again once (its URL may have expired)."""

    def _play_request_error(self, request_id: int, error: str, renewable: bool = True):
        if request_id != self._play_request:
            return False
        if not renewable:
            self._stream_ready = False
            self._show_play_failure(error)
            return False
        return self._player_error(error)

    def _player_error(self, error: str):
        self._stream_ready = False
        item = getattr(self, "current_item", None)
        if item is not None and self._stream_recovery_attempts < 1:
            self._stream_recovery_attempts += 1
            request_id = self._play_request
            self.play_button.set_sensitive(False)
            self.expanded_play_button.set_sensitive(False)
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=_("O stream falhou; renovando a conexão…"),
                    timeout=3,
                )
            )

            def recover() -> None:
                try:
                    self._deliver_stream(
                        request_id, self.youtube.resolve_stream(item.id, force=True)
                    )
                except Exception as exc:
                    GLib.idle_add(self._player_recovery_failed, request_id, str(exc))

            threading.Thread(target=recover, daemon=True, name="stream-recovery").start()
            return False
        self._show_play_failure(_("Não foi possível reproduzir: {error}").format(error=error))
        return False

    def _player_recovery_failed(self, request_id: int, error: str) -> bool:
        if request_id == self._play_request:
            self._show_play_failure(
                _("Não foi possível reproduzir mesmo após renovar o stream: {error}").format(
                    error=error
                )
            )
        return False

    def _show_play_failure(self, message: str) -> None:
        for button in (self.play_button, self.expanded_play_button):
            button.set_sensitive(True)
            button.set_icon_name("media-playback-start-symbolic")
        toast = Adw.Toast(title=message, timeout=8, button_label=_("Copiar relatório"))
        report = playback_report(message, getattr(self, "current_item", None))
        toast.connect("button-clicked", lambda *_: self._copy_playback_report(report))
        self.toast_overlay.add_toast(toast)

    def _copy_playback_report(self, report: str) -> None:
        display = Gdk.Display.get_default()
        if display is not None:
            display.get_clipboard().set(report)
            self.toast_overlay.add_toast(Adw.Toast(title=_("Relatório copiado"), timeout=2))
