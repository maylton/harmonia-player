from __future__ import annotations

from .qt_playback import QtPlaybackController


class QtIntegratedPlaybackController(QtPlaybackController):
    """Qt playback controller with an optional remote transport.

    Local playback remains the shared NativePlayer/GStreamer path.  A Qt-only
    integration controller can temporarily become the transport for UPnP/DLNA
    without adding toolkit or network-device concerns to the shared player.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._remote_transport = None
        self._current_stream_uri = ""

    def set_remote_transport(self, transport) -> None:
        self._remote_transport = transport

    @property
    def remote_active(self) -> bool:
        transport = self._remote_transport
        return bool(transport is not None and transport.active)

    @property
    def current_stream_uri(self) -> str:
        return self._current_stream_uri

    @property
    def playing(self) -> bool:
        if self.remote_active:
            return bool(self._remote_transport.playing)
        return super().playing

    @property
    def position(self) -> int:
        if not self._stream_ready:
            return max(0, self._restored_position_ms)
        if self.remote_active:
            return max(0, int(self._remote_transport.position_ms))
        return super().position

    def _play_uri(self, uri: str) -> None:
        self._current_stream_uri = uri
        if self.remote_active and self._remote_transport.start_stream(uri, self.current_item):
            return
        super()._play_uri(uri)

    def toggle_playback(self) -> None:
        if self.current_item is None:
            return
        if not self._stream_ready:
            self.resolve_current()
            return
        if self.remote_active and self._remote_transport.toggle():
            self.playbackChanged.emit()
            return
        self.player.toggle()

    def stop(self) -> None:
        if self.remote_active:
            self._remote_transport.stop()
        self._current_stream_uri = ""
        super().stop()

    def seek(self, position_ms: int) -> None:
        target = max(0, min(int(position_ms), self.duration or int(position_ms)))
        if self.remote_active:
            if self._remote_transport.seek(target):
                self._restored_position_ms = 0
                self.positionChanged.emit()
                self._save_state(target)
            return
        super().seek(target)

    def load_shared_state(self, queue, index: int, position_ms: int) -> None:
        """Load one Listen Together state without duplicating queue rules in QML."""
        if not queue or not 0 <= index < len(queue):
            return
        self.related_items = []
        self.waiting_for_autoplay = False
        self._radio_request += 1
        self._set_autoplay_loading(False)
        self.queue = list(queue)
        self.set_current(index, resolve=False)
        self._restored_position_ms = max(0, int(position_ms))
        self.resolve_current()

    def _on_player_state(self, playing: bool) -> bool:
        # Stopping the local playbin while handing a stream to a renderer can
        # emit a late local state notification.  Do not let it override the
        # remote state exposed to QML/MPRIS.
        if self.remote_active:
            return False
        return super()._on_player_state(playing)

    def shutdown(self) -> None:
        if self.remote_active:
            self._remote_transport.stop()
        super().shutdown()
