from __future__ import annotations

import logging
from contextlib import suppress

import gi
import shiboken6

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402
from PySide6.QtCore import Property, QObject, Signal, Slot  # noqa: E402

LOGGER = logging.getLogger(__name__)


class QtVideoController(QObject):
    """Qt/QML bridge for switching the shared GStreamer player to video.

    The logical track never changes. The controller resolves the alternate URI
    in the backend executor and asks NativePlayer.replace() to retain position
    and play/pause state, leaving queue/history/MPRIS/scrobble generation alone.
    """

    modeChanged = Signal()
    loadingChanged = Signal()
    availabilityChanged = Signal()
    _resolved = Signal(int, object, str)

    def __init__(self, backend, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.backend = backend
        self.playback = backend.playback
        self._mode = "audio"
        self._loading = False
        self._request = 0
        self._pending: dict[int, tuple[str, str, int, bool, str]] = {}
        self._surface = None
        self._sink = None
        self._original_player_error = self.playback.player.on_error
        self.playback.player.on_error = self._on_player_error

        self._resolved.connect(self._apply_resolved)
        self.backend.nowPlayingChanged.connect(self._on_track_changed)

    @Property(str, notify=modeChanged)
    def mode(self) -> str:
        return self._mode

    @Property(bool, notify=loadingChanged)
    def loading(self) -> bool:
        return self._loading

    @Property(bool, notify=availabilityChanged)
    def available(self) -> bool:
        item = self.playback.current_item
        return bool(
            self._sink is not None
            and item is not None
            and item.id
            and not item.id.startswith("local:")
            and not getattr(self.playback, "remote_active", False)
        )

    def _set_loading(self, value: bool) -> None:
        value = bool(value)
        if value == self._loading:
            return
        self._loading = value
        self.loadingChanged.emit()
        self.availabilityChanged.emit()

    @Slot(QObject)
    def registerSurface(self, surface: QObject) -> None:
        """Bind qml6glsink to the QQuickItem owned by VideoSurface.qml."""
        if self._surface is surface and self._sink is not None:
            return
        if self._sink is not None:
            with suppress(Exception):
                self._sink.set_state(Gst.State.NULL)
            self.playback.player.set_video_sink(None)
            self._sink = None

        sink = Gst.ElementFactory.make("qml6glsink", "harmonia-qt-video")
        if sink is None:
            self.backend._set_status(
                "O plugin GStreamer qml6glsink não está disponível; o modo de vídeo foi desativado."
            )
            self._surface = surface
            self.availabilityChanged.emit()
            return

        try:
            pointer = int(shiboken6.getCppPointer(surface)[0])
            sink.set_property("widget", pointer)
            # qml6glsink should establish Qt's GstGLDisplay before the rest of
            # the GL pipeline reaches READY/PAUSED.
            sink.set_state(Gst.State.READY)
            self.playback.player.set_video_sink(sink)
        except Exception as exc:
            LOGGER.exception("Could not attach qml6glsink to QQuickItem")
            with suppress(Exception):
                sink.set_state(Gst.State.NULL)
            self.backend._set_status(f"Não foi possível preparar a saída de vídeo: {exc}")
            self._surface = surface
            self._sink = None
            self.availabilityChanged.emit()
            return

        self._surface = surface
        self._sink = sink
        self.availabilityChanged.emit()

    @Slot()
    def refreshAvailability(self) -> None:
        self.availabilityChanged.emit()

    @Slot(str)
    def setMode(self, mode: str) -> None:
        self._set_mode(mode, force=False)

    def _set_mode(self, mode: str, *, force: bool = False) -> None:
        mode = "video" if mode == "video" else "audio"
        item = self.playback.current_item
        if item is None or not self.playback._stream_ready:
            return
        if mode == self._mode and not force:
            return
        if mode == "video" and not self.available:
            self.backend._set_status("O vídeo não está disponível para esta faixa neste dispositivo.")
            self.availabilityChanged.emit()
            return

        self._request += 1
        request_id = self._request
        previous_mode = self._mode
        position_ms = max(0, int(self.playback.position))
        was_playing = bool(self.playback.playing)
        self._pending[request_id] = (
            item.id,
            mode,
            position_ms,
            was_playing,
            previous_mode,
        )
        self._set_loading(True)

        def worker() -> None:
            try:
                if mode == "video":
                    stream = self.backend.youtube.resolve_video(item, max_height=720, force=force)
                else:
                    stream = self.backend.youtube.resolve_stream(item.id, force=force)
                self._resolved.emit(request_id, stream, "")
            except Exception as exc:
                LOGGER.exception("Qt media-mode resolve failed")
                self._resolved.emit(request_id, None, str(exc))

        self.backend._executor.submit(worker)

    @Slot(int, object, str)
    def _apply_resolved(self, request_id: int, stream, error: str) -> None:
        pending = self._pending.pop(request_id, None)
        if pending is None or request_id != self._request:
            return
        item_id, mode, position_ms, was_playing, previous_mode = pending
        current = self.playback.current_item
        if current is None or current.id != item_id:
            self._set_loading(False)
            return

        self._set_loading(False)
        if error or stream is None:
            self._mode = previous_mode
            self.modeChanged.emit()
            if mode == "video":
                self.backend._set_status(f"Não foi possível abrir o vídeo: {error}")
            else:
                self.backend._set_status(f"Não foi possível voltar para a música: {error}")
            return

        self._mode = mode
        if getattr(stream, "duration_ms", None):
            self.playback._duration_ms = max(0, int(stream.duration_ms))
        if hasattr(self.playback, "_current_stream_uri"):
            self.playback._current_stream_uri = stream.url
        self.playback.player.replace(stream.url, position_ms * 1000, playing=was_playing)
        self.modeChanged.emit()
        self.playback.durationChanged.emit()
        self.playback.positionChanged.emit()
        self.playback.playbackChanged.emit()
        self.backend._set_status("")

    def _on_track_changed(self) -> None:
        self._request += 1
        self._pending.clear()
        self._set_loading(False)
        if self._mode != "audio":
            self._mode = "audio"
            self.modeChanged.emit()
        self.availabilityChanged.emit()

    def _on_player_error(self, error: str):
        if self._mode == "video" and self.playback.current_item is not None:
            self.backend._set_status("O vídeo falhou; voltando para a música…")
            self._set_mode("audio", force=True)
            return False
        if self._original_player_error:
            return self._original_player_error(error)
        return False

    @Slot()
    def shutdown(self) -> None:
        self._request += 1
        self._pending.clear()
        self.playback.player.on_error = self._original_player_error
        if self._sink is not None:
            with suppress(Exception):
                self._sink.set_state(Gst.State.NULL)
            self._sink = None
