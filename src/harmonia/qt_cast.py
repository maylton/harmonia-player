"""UPnP/DLNA in the KDE frontend: finding renderers and playing through one.

While connected, this is the playback's remote transport
(QtIntegratedPlaybackController.set_remote_transport): it answers for the
playing state and position and receives play, pause, seek and stop.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import QTimer

from .cast import CastMediaHost, UpnpDiscovery, UpnpRenderer
from .i18n import _, ngettext
from .qt_integration_context import IntegrationContext, Job


class CastBridge:
    def __init__(self, context: IntegrationContext, changed: Callable[[], None]) -> None:
        self.context = context
        self.changed = changed
        self.renderer: UpnpRenderer | None = None
        self.device = None
        self.devices: list = []
        self.media = CastMediaHost()
        self._stream_uri = ""
        self._position_ms = 0
        self._started = 0.0
        self._playing = False

    @property
    def playback(self):
        return self.context.playback

    # Devices

    def scan(self) -> None:
        self.context.set_status(_("Procurando dispositivos UPnP/DLNA na rede local…"))
        self.context.run(
            Job(
                "cast-discovery",
                self._devices_found,
                None,
                _("Não foi possível procurar dispositivos"),
            ),
            UpnpDiscovery().discover,
        )

    def _devices_found(self, result) -> None:
        self.devices = list(result or [])
        self.changed()
        if not self.devices:
            self.context.set_status(_("Nenhum dispositivo UPnP/DLNA encontrado."))
            return
        count = len(self.devices)
        self.context.set_status(
            ngettext(
                "{count} dispositivo encontrado.", "{count} dispositivos encontrados.", count
            ).format(count=count)
        )

    def connect(self, index: int) -> None:
        if not 0 <= index < len(self.devices):
            return
        playback = self.playback
        if playback.current_item is None or not playback.current_stream_uri:
            self.context.set_status(_("Comece a reproduzir uma faixa antes de transmitir."))
            return
        device = self.devices[index]
        renderer = UpnpRenderer(device)
        position_ms, was_playing = playback.position, playback.playing
        uri, title = playback.current_stream_uri, playback.current_item.title
        try:
            cast_uri = self.media.uri_for(uri)
        except (OSError, ValueError) as exc:
            self.context.set_status(
                _("Não foi possível transmitir: {error}").format(error=exc), error=True
            )
            return
        # Stop GStreamer before the remote transport turns active, otherwise
        # the playback would already report the renderer's state.
        playback.player.stop()
        self.device, self.renderer = device, renderer
        self._stream_uri = uri
        self._position_ms = position_ms
        self._started = time.monotonic() - position_ms / 1000
        self._playing = was_playing
        self.changed()
        playback.playbackChanged.emit()

        def operation():
            renderer.play_uri(cast_uri, title)
            if position_ms > 1000:
                renderer.seek(position_ms)
            if not was_playing:
                renderer.pause()

        self.context.set_status(_("Conectando a {name}…").format(name=device.name))
        self.context.run(
            Job(
                "cast-connect",
                self._playback_started,
                self._cast_failed,
                _("Não foi possível transmitir"),
            ),
            operation,
        )

    def _playback_started(self, _result=None) -> None:
        self.changed()
        self.playback.playbackChanged.emit()
        if self.device:
            self.context.set_status(_("Reproduzindo em {name}.").format(name=self.device.name))

    def _cast_failed(self, _error: str) -> None:
        self.disconnect(resume=True)

    def disconnect(self, *, resume: bool) -> None:
        renderer = self.renderer
        if renderer is None:
            return
        position_ms = self.position_ms
        stream_uri = self._stream_uri or self.playback.current_stream_uri
        self.renderer = None
        self.device = None
        self._playing = False
        self._stream_uri = ""
        self.context.run(Job("cast-stop"), renderer.stop)
        self.media.close()
        self.changed()
        if resume and stream_uri and self.playback.current_item is not None:
            self.playback.player.play(stream_uri)
            QTimer.singleShot(500, lambda: self.playback.seek(position_ms))
            self.context.set_status(_("Reprodução devolvida a este computador."))
        self.playback.playbackChanged.emit()

    def close(self) -> None:
        renderer, self.renderer = self.renderer, None
        if renderer is not None:
            self.context.run(Job("cast-stop"), renderer.stop)
        self.media.close()

    # Remote transport

    @property
    def active(self) -> bool:
        return self.renderer is not None

    @property
    def playing(self) -> bool:
        return self._playing if self.active else self.playback.player.playing

    @property
    def position_ms(self) -> int:
        if not self.active:
            return self.playback.player.position_us // 1000
        if self._playing:
            return max(0, int((time.monotonic() - self._started) * 1000))
        return self._position_ms

    def start_stream(self, uri: str, item) -> bool:
        renderer = self.renderer
        if renderer is None:
            return False
        self._stream_uri = uri
        self._position_ms = 0
        self._started = time.monotonic()
        self._playing = True
        try:
            cast_uri = self.media.uri_for(uri)
        except (OSError, ValueError) as exc:
            self.context.set_status(
                _("Não foi possível transmitir: {error}").format(error=exc), error=True
            )
            self.disconnect(resume=False)
            return False
        self.context.run(
            Job(
                "cast-track",
                self._playback_started,
                self._cast_failed,
                _("Não foi possível trocar a faixa no dispositivo"),
            ),
            lambda: renderer.play_uri(cast_uri, item.title),
        )
        self.changed()
        return True

    def toggle(self) -> bool:
        renderer = self.renderer
        if renderer is None:
            return False
        if self._playing:
            self._position_ms = self.position_ms
            self._playing = False
            self.context.run(Job("cast-pause"), renderer.pause)
        else:
            self._started = time.monotonic() - self._position_ms / 1000
            self._playing = True
            self.context.run(Job("cast-play"), renderer.play)
        self.playback.playbackChanged.emit()
        return True

    def seek(self, position_ms: int) -> bool:
        renderer = self.renderer
        if renderer is None:
            return False
        self._position_ms = max(0, int(position_ms))
        if self._playing:
            self._started = time.monotonic() - self._position_ms / 1000
        target = self._position_ms
        self.context.run(Job("cast-seek"), lambda: renderer.seek(target))
        return True

    def stop(self) -> bool:
        if not self.active:
            return False
        self.disconnect(resume=False)
        return True
