"""Casting to UPnP/DLNA renderers, and the playback transport while casting."""

from __future__ import annotations

import time

import gi

gi.require_version("Adw", "1")
from gi.repository import Adw, GLib

from .cast import UpnpDiscovery, UpnpRenderer
from .i18n import _


class WindowCastMixin:
    def _scan_cast_devices(self, row: Adw.ActionRow) -> None:
        row.set_subtitle(_("Procurando na rede local…"))

        def completed(devices, error):
            if error:
                row.set_subtitle(
                    _("Não foi possível procurar dispositivos: {error}").format(error=error)
                )
                return False
            if not devices:
                row.set_subtitle(_("Nenhum dispositivo encontrado"))
                return False
            dialog = Adw.AlertDialog(
                heading=_("Escolha um dispositivo"),
                body=_("A faixa atual será transferida para o dispositivo selecionado."),
            )
            dialog.add_response("cancel", _("Cancelar"))
            for index, device in enumerate(devices):
                dialog.add_response(f"device-{index}", device.name)

            def selected(_dialog, response: str):
                if response.startswith("device-"):
                    self._connect_cast(devices[int(response.removeprefix("device-"))])

            dialog.connect("response", selected)
            dialog.present(self)
            row.set_subtitle(_("{count} dispositivo(s) encontrado(s)").format(count=len(devices)))
            return False

        self._optional_worker("cast-discovery", UpnpDiscovery().discover, completed)

    def _connect_cast(self, device) -> None:
        if not self._current_stream_url or getattr(self, "current_item", None) is None:
            self.toast_overlay.add_toast(
                Adw.Toast(title=_("Comece a reproduzir uma faixa antes de transmitir"))
            )
            return
        try:
            cast_uri = self.cast_media.uri_for(self._current_stream_url)
        except (OSError, ValueError) as exc:
            self.toast_overlay.add_toast(
                Adw.Toast(title=_("Não foi possível transmitir: {error}").format(error=exc))
            )
            return
        self.cast_device = device
        renderer = UpnpRenderer(device)
        self.cast_renderer = renderer
        self._cast_position_ms = self.player.position_us // 1000
        self._cast_started = time.monotonic() - self._cast_position_ms / 1000
        self._cast_playing = True
        self.player.stop()
        self._optional_worker(
            "cast-start",
            lambda: renderer.play_uri(cast_uri, self.current_item.title),
            self._cast_started_done,
        )

    def _cast_started_done(self, _result, error):
        if error:
            self._disconnect_cast(resume=True)
            self.toast_overlay.add_toast(
                Adw.Toast(title=_("Não foi possível transmitir: {error}").format(error=error))
            )
        else:
            self._player_state(True, remote=True)
            self.toast_overlay.add_toast(
                Adw.Toast(title=_("Reproduzindo em {device}").format(device=self.cast_device.name))
            )
            if self.main_view == "settings":
                self.show_settings()
        return False

    def _disconnect_cast(self, *, resume: bool = True) -> None:
        renderer = self.cast_renderer
        position_ms = self._playback_position_us() // 1000
        if renderer:
            self._optional_worker("cast-stop", renderer.stop)
        self.cast_renderer = None
        self.cast_device = None
        self._cast_playing = False
        self.cast_media.close()
        if resume and self._current_stream_url:
            self.player.play(self._current_stream_url)
            GLib.timeout_add(500, self._apply_pending_seek, self._play_request, position_ms)
        if getattr(self, "main_view", "") == "settings":
            self.show_settings()

    def _optional_start_stream(self, url: str) -> bool:
        self._current_stream_url = url
        if not self.cast_renderer:
            return False
        self._cast_position_ms = 0
        self._cast_started = time.monotonic()
        self._cast_playing = True
        item = self.current_item
        renderer = self.cast_renderer
        try:
            cast_uri = self.cast_media.uri_for(url)
        except (OSError, ValueError) as exc:
            self.toast_overlay.add_toast(
                Adw.Toast(title=_("Não foi possível transmitir: {error}").format(error=exc))
            )
            self._disconnect_cast(resume=False)
            return False
        self._optional_worker(
            "cast-track",
            lambda: renderer.play_uri(cast_uri, item.title),
            self._cast_started_done,
        )
        return True

    def _optional_toggle_player(self) -> bool:
        if not self.cast_renderer:
            return False
        if self._cast_playing:
            self._cast_position_ms = self._playback_position_us() // 1000
            self._cast_playing = False
            self._optional_worker("cast-pause", self.cast_renderer.pause)
        else:
            self._cast_started = time.monotonic() - self._cast_position_ms / 1000
            self._cast_playing = True
            self._optional_worker("cast-play", self.cast_renderer.play)
        self._player_state(self._cast_playing, remote=True)
        return True

    def _seek_playback(self, position_us: int) -> bool:
        if not self.cast_renderer:
            return self.player.seek(position_us)
        self._cast_position_ms = max(0, position_us // 1000)
        if self._cast_playing:
            self._cast_started = time.monotonic() - self._cast_position_ms / 1000
        self._optional_worker("cast-seek", lambda: self.cast_renderer.seek(self._cast_position_ms))
        return True

    def _playback_position_us(self) -> int:
        if not self.cast_renderer:
            return self.player.position_us
        if self._cast_playing:
            return max(0, int((time.monotonic() - self._cast_started) * 1_000_000))
        return self._cast_position_ms * 1000

    def _playback_is_playing(self) -> bool:
        return self._cast_playing if self.cast_renderer else self.player.playing

    def _optional_ignore_local_state(self) -> bool:
        return self.cast_renderer is not None

    def _optional_stop(self) -> None:
        if self.cast_renderer:
            renderer = self.cast_renderer
            self.cast_renderer = None
            self.cast_device = None
            self._cast_playing = False
            self._optional_worker("cast-stop", renderer.stop)
        self._current_stream_url = ""
        self.cast_media.close()
