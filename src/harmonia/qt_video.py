from __future__ import annotations

import ctypes
import ctypes.util
import logging
from contextlib import suppress

import gi
import shiboken6

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402
from PySide6.QtCore import Property, QObject, Signal, Slot  # noqa: E402

LOGGER = logging.getLogger(__name__)


def _capsule_pointer(capsule) -> int:
    """Return the native pointer stored in a CPython capsule."""
    get_name = ctypes.pythonapi.PyCapsule_GetName
    get_name.restype = ctypes.c_char_p
    get_name.argtypes = [ctypes.py_object]
    name = get_name(capsule)

    get_pointer = ctypes.pythonapi.PyCapsule_GetPointer
    get_pointer.restype = ctypes.c_void_p
    get_pointer.argtypes = [ctypes.py_object, ctypes.c_char_p]
    pointer = get_pointer(capsule, name)
    if not pointer:
        raise RuntimeError("Não foi possível obter o ponteiro nativo do objeto GStreamer")
    return int(pointer)


def _set_foreign_pointer_property(gobject, property_name: str, pointer: int) -> None:
    """Set a G_TYPE_POINTER property that PyGObject cannot marshal itself.

    qml6glsink's ``widget`` property is a raw QQuickItem* (gpointer), not a
    GObject. PyGObject intentionally cannot convert a PySide QObject wrapper
    or an integer address into that foreign pointer. Use the native GObject
    setter only for this boundary while retaining ownership in the Python/Qt
    wrappers on both sides.
    """
    capsule = getattr(gobject, "__gpointer__", None)
    if capsule is None:
        raise RuntimeError("O objeto GStreamer não expõe o ponteiro nativo")
    object_pointer = _capsule_pointer(capsule)

    library_name = ctypes.util.find_library("gobject-2.0") or "libgobject-2.0.so.0"
    gobject_library = ctypes.CDLL(library_name)
    g_object_set = gobject_library.g_object_set
    g_object_set.restype = None
    # g_object_set() is variadic. Declare only its fixed arguments and pass
    # explicitly typed pointer arguments for the varargs below.
    g_object_set.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    g_object_set(
        ctypes.c_void_p(object_pointer),
        property_name.encode("utf-8"),
        ctypes.c_void_p(pointer),
        ctypes.c_void_p(),
    )


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
        self._sink_error = ""
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

    def _track_eligible(self) -> bool:
        item = self.playback.current_item
        return bool(
            item is not None
            and item.id
            and not item.id.startswith("local:")
            and not getattr(self.playback, "remote_active", False)
        )

    @Property(bool, notify=availabilityChanged)
    def available(self) -> bool:
        """Whether the current track is eligible for a video lookup.

        This deliberately does not depend on qml6glsink already being attached.
        A music video can only be confirmed after the user requests Video, and
        the QML surface may be initialized later than the transport state.
        """
        return self._track_eligible()

    @Property(bool, notify=availabilityChanged)
    def outputReady(self) -> bool:
        return self._sink is not None

    @Property(str, notify=availabilityChanged)
    def outputError(self) -> str:
        return self._sink_error

    def _set_loading(self, value: bool) -> None:
        value = bool(value)
        if value == self._loading:
            return
        self._loading = value
        self.loadingChanged.emit()
        self.availabilityChanged.emit()

    def _discard_sink(self) -> None:
        if self._sink is None:
            return
        with suppress(Exception):
            self.playback.player.set_video_sink(None)
        with suppress(Exception):
            self._sink.set_state(Gst.State.NULL)
        self._sink = None

    def _ensure_sink(self) -> bool:
        if self._sink is not None:
            return True
        if self._surface is None:
            self._sink_error = "A superfície de vídeo Qt ainda não foi inicializada."
            self.availabilityChanged.emit()
            return False

        sink = Gst.ElementFactory.make("qml6glsink", "harmonia-qt-video")
        if sink is None:
            self._sink_error = "O plugin GStreamer qml6glsink não está disponível."
            self.availabilityChanged.emit()
            return False

        try:
            pointer = int(shiboken6.getCppPointer(self._surface)[0])
            if not pointer:
                raise RuntimeError("A superfície QQuickItem não possui ponteiro nativo")
            _set_foreign_pointer_property(sink, "widget", pointer)
            # The audio-only pipeline has no GL elements, so it is safe to
            # establish Qt's GstGLDisplay here, immediately before switching
            # to the video stream. Avoid touching the Qt scene graph while the
            # expanded player is merely being constructed in Music mode.
            result = sink.set_state(Gst.State.READY)
            if result == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError("qml6glsink recusou o estado READY")
            self.playback.player.set_video_sink(sink)
        except Exception as exc:
            LOGGER.exception("Could not attach qml6glsink to QQuickItem")
            with suppress(Exception):
                sink.set_state(Gst.State.NULL)
            self._sink_error = str(exc)
            self._sink = None
            self.availabilityChanged.emit()
            return False

        self._sink = sink
        self._sink_error = ""
        self.availabilityChanged.emit()
        return True

    @Slot(QObject)
    def registerSurface(self, surface: QObject) -> None:
        """Remember the QQuickItem without touching GStreamer yet.

        qml6glsink is prepared lazily on the first Video request. This keeps
        normal Music-mode rendering independent from the optional video path.
        """
        if self._surface is surface:
            return
        self._discard_sink()
        self._surface = surface
        self._sink_error = ""
        self.availabilityChanged.emit()

    @Slot()
    def refreshAvailability(self) -> None:
        # Availability describes whether the current track can be looked up.
        # Do not initialize qml6glsink just because the dialog became visible.
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
        if mode == "video":
            if not self.available:
                self.backend._set_status(
                    "O vídeo não está disponível para esta faixa neste dispositivo."
                )
                self.availabilityChanged.emit()
                return
            if not self._ensure_sink():
                detail = self._sink_error or "saída de vídeo indisponível"
                self.backend._set_status(f"Não foi possível preparar a saída de vídeo: {detail}")
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
                detail = error or "nenhum vídeo correspondente foi encontrado"
                self.backend._set_status(f"Não foi possível abrir o vídeo: {detail}")
            else:
                self.backend._set_status(f"Não foi possível voltar para a música: {error}")
            return

        if mode == "video" and not self._ensure_sink():
            self._mode = previous_mode
            self.modeChanged.emit()
            detail = self._sink_error or "saída de vídeo indisponível"
            self.backend._set_status(f"Não foi possível preparar a saída de vídeo: {detail}")
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
        self._discard_sink()
