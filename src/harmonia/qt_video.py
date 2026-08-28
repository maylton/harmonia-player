from __future__ import annotations

import ctypes
import ctypes.util
import logging
import time
from contextlib import suppress

import gi
import shiboken6

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # noqa: E402
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot  # noqa: E402

LOGGER = logging.getLogger(__name__)


def create_qml6_video_sink():
    """Load qml6 before QML so it can register GstGLQt6VideoItem."""
    Gst.init(None)
    return Gst.ElementFactory.make("qml6glsink", "harmonia-qt-video")


def _capsule_pointer(capsule) -> int:
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
    """Set qml6glsink's raw QQuickItem* property across PyGObject/PySide."""
    capsule = getattr(gobject, "__gpointer__", None)
    if capsule is None:
        raise RuntimeError("O objeto GStreamer não expõe o ponteiro nativo")
    object_pointer = _capsule_pointer(capsule)

    library_name = ctypes.util.find_library("gobject-2.0") or "libgobject-2.0.so.0"
    gobject_library = ctypes.CDLL(library_name)
    g_object_set = gobject_library.g_object_set
    g_object_set.restype = None
    g_object_set.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    g_object_set(
        ctypes.c_void_p(object_pointer),
        property_name.encode("utf-8"),
        ctypes.c_void_p(pointer),
        ctypes.c_void_p(),
    )


class QtVideoController(QObject):
    """Qt video layer synchronized to the shared audio transport.

    The main NativePlayer remains the only logical/audio player, so queue,
    history, MPRIS, scrobbling and audio processing never change when the user
    selects Video. A second muted GStreamer playbin owns only the visual stream
    and follows the main transport's position and play/pause state.
    """

    modeChanged = Signal()
    loadingChanged = Signal()
    availabilityChanged = Signal()
    _resolved = Signal(int, object, str)
    _prepare_sink_requested = Signal()

    def __init__(self, backend, sink=None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.backend = backend
        self.playback = backend.playback
        self._mode = "audio"
        self._loading = False
        self._request = 0
        self._video_generation = 0
        self._video_last_sync_seek = 0.0
        self._pending: dict[int, tuple[str, str]] = {}
        self._surface = None
        self._surface_window = None
        self._scene_graph_window = None
        self._surface_visibility_signal = None
        self._sink_prepare_attempts = 0
        self._sink_prepare_retry_pending = False
        self._sink = sink
        self._sink_prepared = False
        self._sink_error = (
            "" if sink is not None else "O plugin GStreamer qml6glsink não está disponível."
        )

        self._video_player = Gst.ElementFactory.make("playbin", "harmonia-video-layer")
        self._fake_audio_sink = Gst.ElementFactory.make("fakesink", "harmonia-video-muted-audio")
        if self._fake_audio_sink is not None:
            self._fake_audio_sink.set_property("sync", True)
        if self._video_player is None:
            self._sink_error = "O GStreamer playbin para vídeo não está disponível."

        self._video_bus = self._video_player.get_bus() if self._video_player is not None else None
        if self._video_bus is not None:
            self._video_bus.add_signal_watch()
            self._video_bus.connect("message", self._on_video_message)

        self._resolved.connect(self._apply_resolved)
        # sceneGraphInitialized is emitted from Qt Quick's render thread on
        # some render-loop implementations. Emitting this signal from that
        # callback queues the actual GStreamer/Qt object mutation back to this
        # controller's (main) thread.
        self._prepare_sink_requested.connect(self._prepare_sink_when_ready)
        self.backend.nowPlayingChanged.connect(self._on_track_changed)

        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(200)
        self._sync_timer.timeout.connect(self._sync_video_transport)
        self._sync_timer.start()

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
        return self._track_eligible()

    @Property(bool, notify=availabilityChanged)
    def outputReady(self) -> bool:
        return self._sink_prepared

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

    def _prepare_sink(self) -> bool:
        if self._sink_prepared:
            return True
        if self._sink is None:
            self._sink_error = "O plugin GStreamer qml6glsink não está disponível."
            self.availabilityChanged.emit()
            return False
        if self._video_player is None:
            self._sink_error = "O GStreamer playbin para vídeo não está disponível."
            self.availabilityChanged.emit()
            return False
        if self._surface is None:
            self._sink_error = "A superfície de vídeo Qt ainda não foi inicializada."
            self.availabilityChanged.emit()
            return False
        if not self._surface_window or not self._scene_graph_ready(self._surface_window):
            return False
        if not self._surface_is_visible():
            # ExpandedPlayer creates VideoSurface while its Dialog is closed.
            # qml6glsink cannot bind a render target that is not in the visible
            # scene graph yet; registerSurface therefore only stores the item
            # until the dialog makes it visible.
            return False

        LOGGER.info("Qt GL sink preparation starting")

        try:
            pointer = int(shiboken6.getCppPointer(self._surface)[0])
            if not pointer:
                raise RuntimeError("A superfície GstGLQt6VideoItem não possui ponteiro nativo")
            _set_foreign_pointer_property(self._sink, "widget", pointer)
            self._video_player.set_property("video-sink", self._sink)
            if self._fake_audio_sink is not None:
                self._video_player.set_property("audio-sink", self._fake_audio_sink)
            result = self._video_player.set_state(Gst.State.READY)
            if result == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError("A camada de vídeo recusou o estado READY")
            LOGGER.info("playbin READY")
        except Exception as exc:
            self._log_sink_prepare_failure(exc)
            with suppress(Exception):
                self._video_player.set_state(Gst.State.NULL)
            self._sink_error = str(exc)
            self._sink_prepared = False
            self.availabilityChanged.emit()
            self._schedule_sink_prepare_retry()
            return False

        self._sink_prepared = True
        self._sink_error = ""
        self.availabilityChanged.emit()
        LOGGER.info("Qt video layer ready")
        return True

    @Slot(QObject)
    def registerSurface(self, surface: QObject) -> None:
        if self._surface is not surface:
            if self._surface_visibility_signal is not None:
                with suppress(Exception):
                    self._surface_visibility_signal.disconnect(
                        self._on_surface_visibility_changed
                    )
            self._surface = surface
            self._surface_window = None
            self._sink_prepare_attempts = 0
            self._sink_prepare_retry_pending = False
            self._surface_visibility_signal = surface.visibleChanged
            self._sink_error = ""
            with suppress(Exception):
                surface.windowChanged.connect(self._on_surface_window_changed)
                surface.visibleChanged.connect(self._on_surface_visibility_changed)
        LOGGER.info("Qt video surface registered")
        self._on_surface_window_changed(self._surface.window())
        self._on_surface_visibility_changed()

    @staticmethod
    def _scene_graph_ready(window) -> bool:
        checker = getattr(window, "isSceneGraphInitialized", None)
        return bool(checker()) if callable(checker) else False

    def _on_surface_window_changed(self, window) -> None:
        if self._surface_window is window and window is not None:
            self._request_sink_prepare()
            return
        if self._scene_graph_window is not None:
            with suppress(Exception):
                self._scene_graph_window.sceneGraphInitialized.disconnect(
                    self._on_scene_graph_initialized
                )
        self._surface_window = window
        self._scene_graph_window = window
        if window is None:
            LOGGER.info("Qt video surface is not associated with a QQuickWindow yet")
            return

        LOGGER.info(
            "Qt video QQuickWindow available: graphicsApi=%s rendererGraphicsApi=%s sceneGraphInitialized=%s",
            self._graphics_api_name(window),
            self._renderer_graphics_api_name(window),
            self._scene_graph_ready(window),
        )
        with suppress(Exception):
            window.sceneGraphInitialized.connect(self._on_scene_graph_initialized)
        if self._scene_graph_ready(window):
            self._request_sink_prepare()

    def _on_scene_graph_initialized(self) -> None:
        LOGGER.info("Qt scene graph initialized")
        self._request_sink_prepare()

    def _on_surface_visibility_changed(self) -> None:
        if self._surface is not None:
            self._request_sink_prepare()

    def _surface_is_visible(self) -> bool:
        if self._surface is None:
            return False
        checker = getattr(self._surface, "isVisible", None)
        return bool(checker()) if callable(checker) else bool(self._surface.visible)

    def _schedule_sink_prepare_retry(self) -> None:
        if self._sink_prepare_retry_pending or self._sink_prepare_attempts >= 10:
            return
        self._sink_prepare_retry_pending = True

        def retry() -> None:
            self._sink_prepare_retry_pending = False
            if self._sink_prepared:
                return
            self._request_sink_prepare()

        QTimer.singleShot(100, retry)

    def _log_sink_prepare_failure(self, error: Exception) -> None:
        if self._sink_prepare_attempts >= 10:
            LOGGER.error(
                "Could not prepare Qt video layer after %d attempts: %s",
                self._sink_prepare_attempts,
                error,
            )
        else:
            LOGGER.warning(
                "Qt GL sink preparation attempt %d failed; retrying: %s",
                self._sink_prepare_attempts,
                error,
            )

    def _request_sink_prepare(self) -> None:
        self._prepare_sink_requested.emit()

    @staticmethod
    def _graphics_api_name(window) -> str:
        try:
            return str(window.graphicsApi())
        except Exception:
            return "unknown"

    @staticmethod
    def _renderer_graphics_api_name(window) -> str:
        try:
            renderer = window.rendererInterface()
            return str(renderer.graphicsApi()) if renderer is not None else "none"
        except Exception:
            return "unknown"

    @Slot()
    def _prepare_sink_when_ready(self) -> None:
        if self._sink_prepared or self._surface is None or self._surface_window is None:
            return
        if not self._scene_graph_ready(self._surface_window):
            return
        if not self._surface_is_visible():
            return
        self._sink_prepare_attempts += 1
        self._prepare_sink()

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

        if mode == "audio":
            if self._mode == "audio" and not self._loading:
                return
            self._request += 1
            self._pending.clear()
            self._set_loading(False)
            self._stop_video_layer()
            if self._mode != "audio":
                self._mode = "audio"
                self.modeChanged.emit()
            self.backend._set_status("")
            return

        if self._mode == "video" and not force:
            return
        if not self.available:
            self.backend._set_status(
                "O vídeo não está disponível para esta faixa neste dispositivo."
            )
            self.availabilityChanged.emit()
            return
        if not self._sink_prepared:
            detail = self._sink_error or "saída de vídeo indisponível"
            self.backend._set_status(f"Não foi possível preparar a saída de vídeo: {detail}")
            return

        self._request += 1
        request_id = self._request
        self._pending[request_id] = (item.id, self._mode)
        self._set_loading(True)
        self.backend._set_status("")
        LOGGER.info("Resolving video variant for %s", item.id)

        def worker() -> None:
            try:
                stream = self.backend.youtube.resolve_video(
                    item,
                    max_height=720,
                    force=force,
                    allow_video_only=True,
                )
                self._resolved.emit(request_id, stream, "")
            except Exception as exc:
                LOGGER.exception("Qt video resolve failed")
                self._resolved.emit(request_id, None, str(exc))

        self.backend._executor.submit(worker)

    @Slot(int, object, str)
    def _apply_resolved(self, request_id: int, stream, error: str) -> None:
        pending = self._pending.pop(request_id, None)
        if pending is None or request_id != self._request:
            return
        item_id, previous_mode = pending
        current = self.playback.current_item
        if current is None or current.id != item_id:
            self._set_loading(False)
            return

        if error or stream is None:
            self._set_loading(False)
            if self._mode != previous_mode:
                self._mode = previous_mode
                self.modeChanged.emit()
            detail = error or "nenhum vídeo correspondente foi encontrado"
            self.backend._set_status(f"Não foi possível abrir o vídeo: {detail}")
            return

        LOGGER.info(
            "Resolved video %s: %sp itag=%s muxed=%s client=%s",
            stream.video_id,
            stream.height,
            stream.itag,
            stream.muxed,
            stream.client,
        )
        self._mode = "video"
        self.modeChanged.emit()
        self._start_video_layer(stream)

    def _start_video_layer(self, stream) -> None:
        if self._video_player is None:
            self._video_failed("A camada de vídeo do GStreamer não está disponível.")
            return

        self._video_generation += 1
        generation = self._video_generation
        self._video_last_sync_seek = 0.0
        try:
            self._video_player.set_state(Gst.State.READY)
            source_uri = self.playback.player._source_uri(
                stream.url,
                stream.request_headers,
            )
            self._video_player.set_property("uri", source_uri)
            result = self._video_player.set_state(Gst.State.PAUSED)
            if result == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError("A camada de vídeo não conseguiu iniciar o preroll")
        except Exception as exc:
            self._video_failed(str(exc))
            return

        GLib.timeout_add(40, self._finish_video_preroll, generation, 0)

    def _finish_video_preroll(self, generation: int, attempt: int) -> bool:
        if generation != self._video_generation or self._mode != "video":
            return GLib.SOURCE_REMOVE
        if self._video_player is None:
            return GLib.SOURCE_REMOVE

        result, state, _pending = self._video_player.get_state(0)
        if result == Gst.StateChangeReturn.FAILURE:
            self._video_failed("O GStreamer falhou ao preparar os frames do vídeo.")
            return GLib.SOURCE_REMOVE
        if state not in (Gst.State.PAUSED, Gst.State.PLAYING):
            if attempt < 100:
                GLib.timeout_add(40, self._finish_video_preroll, generation, attempt + 1)
            else:
                self._video_failed("O vídeo demorou demais para iniciar.")
            return GLib.SOURCE_REMOVE

        target_ms = max(0, int(self.playback.position))
        if target_ms <= 250:
            self._complete_video_start(generation)
            return GLib.SOURCE_REMOVE

        if not self._seek_video_position(target_ms, accurate=True):
            self._video_failed("O fluxo de vídeo não ficou disponível para sincronização.")
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(60, self._finish_video_seek, generation, target_ms, 0)
        return GLib.SOURCE_REMOVE

    def _seek_video_position(self, target_ms: int, *, accurate: bool = True) -> bool:
        if self._video_player is None:
            return False

        target_ms = max(0, int(target_ms))
        flags = Gst.SeekFlags.FLUSH | (
            Gst.SeekFlags.ACCURATE if accurate else Gst.SeekFlags.KEY_UNIT
        )
        accepted = bool(
            self._video_player.seek_simple(
                Gst.Format.TIME,
                flags,
                target_ms * 1_000_000,
            )
        )
        mode = "accurate" if accurate else "key-unit"
        if not accepted and accurate:
            accepted = bool(
                self._video_player.seek_simple(
                    Gst.Format.TIME,
                    Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                    target_ms * 1_000_000,
                )
            )
            mode = "key-unit-fallback"
        if accepted:
            self._video_last_sync_seek = time.monotonic()
        LOGGER.debug(
            "Qt video seek target=%d ms mode=%s accepted=%s",
            target_ms,
            mode,
            accepted,
        )
        return accepted

    def _finish_video_seek(self, generation: int, target_ms: int, attempt: int) -> bool:
        if generation != self._video_generation or self._mode != "video":
            return GLib.SOURCE_REMOVE
        if self._video_player is None:
            return GLib.SOURCE_REMOVE

        result, _state, _pending = self._video_player.get_state(0)
        if result == Gst.StateChangeReturn.FAILURE:
            self._video_failed("O GStreamer falhou durante a sincronização do vídeo.")
            return GLib.SOURCE_REMOVE

        ok, video_ns = self._video_player.query_position(Gst.Format.TIME)
        video_ms = max(0, int(video_ns // 1_000_000)) if ok else -1
        audio_ms = max(0, int(self.playback.position))
        drift_ms = audio_ms - video_ms if video_ms >= 0 else -1

        if ok and abs(drift_ms) <= 1000:
            LOGGER.info(
                "Qt video initial sync settled: audio=%d ms video=%d ms drift=%d ms",
                audio_ms,
                video_ms,
                drift_ms,
            )
            self._complete_video_start(generation)
            return GLib.SOURCE_REMOVE

        if attempt in (15, 35, 55):
            retry_target = audio_ms
            if self._seek_video_position(retry_target, accurate=True):
                target_ms = retry_target

        if attempt < 75:
            GLib.timeout_add(
                60,
                self._finish_video_seek,
                generation,
                target_ms,
                attempt + 1,
            )
            return GLib.SOURCE_REMOVE

        LOGGER.warning(
            "Qt video sync did not settle: requested=%d ms audio=%d ms video=%d ms",
            target_ms,
            audio_ms,
            video_ms,
        )
        self._video_failed("Não foi possível sincronizar o vídeo com a música.")
        return GLib.SOURCE_REMOVE

    def _complete_video_start(self, generation: int) -> None:
        if generation != self._video_generation or self._mode != "video":
            return
        if self._video_player is None:
            return

        self._video_player.set_state(
            Gst.State.PLAYING if self.playback.playing else Gst.State.PAUSED
        )
        self._set_loading(False)
        self.backend._set_status("")
        audio_ms = max(0, int(self.playback.position))
        ok, video_ns = self._video_player.query_position(Gst.Format.TIME)
        video_ms = max(0, int(video_ns // 1_000_000)) if ok else -1
        LOGGER.info(
            "Qt video layer visible: audio=%d ms video=%d ms drift=%d ms",
            audio_ms,
            video_ms,
            audio_ms - video_ms if video_ms >= 0 else -1,
        )

    def _sync_video_transport(self) -> None:
        if self._mode != "video" or self._loading or self._video_player is None:
            return

        _result, state, _pending = self._video_player.get_state(0)
        desired = Gst.State.PLAYING if self.playback.playing else Gst.State.PAUSED
        if state in (Gst.State.PLAYING, Gst.State.PAUSED) and state != desired:
            self._video_player.set_state(desired)

        ok, video_ns = self._video_player.query_position(Gst.Format.TIME)
        if not ok:
            return
        audio_ms = max(0, int(self.playback.position))
        video_ms = max(0, int(video_ns // 1_000_000))
        drift_ms = audio_ms - video_ms
        if abs(drift_ms) > 500 and time.monotonic() - self._video_last_sync_seek >= 1.0:
            LOGGER.info(
                "Qt video drift correction: audio=%d ms video=%d ms drift=%d ms",
                audio_ms,
                video_ms,
                drift_ms,
            )
            self._seek_video_position(audio_ms, accurate=True)

    def _stop_video_layer(self) -> None:
        self._video_generation += 1
        self._video_last_sync_seek = 0.0
        if self._video_player is not None:
            with suppress(Exception):
                self._video_player.set_state(Gst.State.READY)

    def _video_failed(self, detail: str) -> None:
        LOGGER.error("Qt video layer failed: %s", detail)
        self._video_generation += 1
        self._video_last_sync_seek = 0.0
        if self._video_player is not None:
            with suppress(Exception):
                self._video_player.set_state(Gst.State.READY)
        self._set_loading(False)
        if self._mode != "audio":
            self._mode = "audio"
            self.modeChanged.emit()
        self.backend._set_status(f"Não foi possível exibir o vídeo: {detail}")

    def _on_video_message(self, _bus, message) -> None:
        if message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            if self._mode != "video":
                # READY/NULL transitions can deliver a late error from the
                # previous URI. It is not a playback failure after the user
                # has already returned to Music, so keep it out of normal logs.
                LOGGER.debug("Ignoring inactive Qt video error: %s", error)
                return
            try:
                source = message.src.get_path_string() if message.src is not None else "unknown"
            except Exception:
                source = "unknown"
            LOGGER.error(
                "Qt video GStreamer error from %s: %s (%s)",
                source,
                error,
                debug or "sem debug",
            )
            if self._mode == "video":
                self._video_failed(str(error))
        elif message.type == Gst.MessageType.EOS and self._mode == "video":
            self._video_failed("O vídeo terminou antes da faixa de áudio.")

    def _on_track_changed(self) -> None:
        self._request += 1
        self._pending.clear()
        self._set_loading(False)
        self._stop_video_layer()
        if self._mode != "audio":
            self._mode = "audio"
            self.modeChanged.emit()
        self.availabilityChanged.emit()

    @Slot()
    def shutdown(self) -> None:
        self._request += 1
        self._pending.clear()
        self._sync_timer.stop()
        self._video_generation += 1
        if self._video_bus is not None:
            with suppress(Exception):
                self._video_bus.remove_signal_watch()
        if self._video_player is not None:
            with suppress(Exception):
                self._video_player.set_state(Gst.State.NULL)
        self._sink_prepared = False
        self._sink = None
        self._video_player = None
