from __future__ import annotations

import logging
from contextlib import suppress

import shiboken6
from gi.repository import Gst

from .media_variants import IndependentVideoPlayback, is_independent_video_variant
from .qt_video import QtVideoController, _set_foreign_pointer_property

LOGGER = logging.getLogger(__name__)


class OfficialVideoQtController(QtVideoController):
    """Qt video controller with YouTube Music-style independent MV semantics."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._qt_glsinkbin = None
        self._qt_video_output = None
        self._independent_video_owns_audio = False
        self._independent_video_primary_uri = ""
        self._independent_video_primary_duration_ms = 0
        self._independent_video_primary_position_ms = 0
        self._primary_save_state = self.playback._save_state
        self._primary_player_error = self.playback.player.on_error
        self.playback._save_state = self._save_playback_state
        self.playback.player.on_error = self._on_primary_player_error

    def _prepare_sink(self) -> bool:
        """Prime Qt's GL display and bridge decoded frames into qml6glsink.

        qml6glsink accepts GLMemory only. Putting it behind glsinkbin gives
        playbin a SystemMemory/DMABuf-capable sink while glsinkbin performs the
        GL upload/conversion. Bringing qml6glsink to READY first also lets it
        propagate Qt Quick's GstGLDisplay before any other GL element starts.
        """
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
            return False

        glsinkbin = None
        try:
            LOGGER.info("Qt GL sink preparation starting")
            pointer = int(shiboken6.getCppPointer(self._surface)[0])
            if not pointer:
                raise RuntimeError("A superfície GstGLQt6VideoItem não possui ponteiro nativo")
            _set_foreign_pointer_property(self._sink, "widget", pointer)

            # qml6glsink must establish Qt Quick's GL display before decodebin
            # or any upload/conversion element creates its own GstGLDisplay.
            sink_state = self._sink.set_state(Gst.State.READY)
            if sink_state == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError("qml6glsink não conseguiu inicializar o contexto OpenGL do Qt")
            LOGGER.info("qml6glsink READY")

            video_output = self._sink
            glsinkbin = Gst.ElementFactory.make("glsinkbin", "harmonia-qt-video-bin")
            if glsinkbin is not None:
                glsinkbin.set_property("sink", self._sink)
                video_output = glsinkbin
                LOGGER.info("Qt video output using glsinkbin -> qml6glsink")
                bin_state = glsinkbin.set_state(Gst.State.READY)
                if bin_state == Gst.StateChangeReturn.FAILURE:
                    raise RuntimeError("glsinkbin não conseguiu inicializar")
                LOGGER.info("glsinkbin READY")
            else:
                LOGGER.warning(
                    "glsinkbin unavailable; falling back to direct qml6glsink negotiation"
                )

            self._video_player.set_property("video-sink", video_output)
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
            if glsinkbin is not None:
                with suppress(Exception):
                    glsinkbin.set_state(Gst.State.NULL)
            with suppress(Exception):
                self._sink.set_state(Gst.State.NULL)
            self._qt_glsinkbin = None
            self._qt_video_output = None
            self._sink_error = str(exc)
            self._sink_prepared = False
            self.availabilityChanged.emit()
            self._schedule_sink_prepare_retry()
            return False

        self._qt_glsinkbin = glsinkbin
        self._qt_video_output = video_output
        self._sink_prepared = True
        self._sink_error = ""
        self.availabilityChanged.emit()
        LOGGER.info("Qt video layer ready")
        return True

    def _clear_independent_video(self) -> None:
        self._independent_video_owns_audio = False
        self._independent_video_primary_uri = ""
        self._independent_video_primary_duration_ms = 0
        self._independent_video_primary_position_ms = 0

    def _save_playback_state(self, position_ms: int | None = None) -> None:
        if self._independent_video_owns_audio:
            position_ms = self._independent_video_primary_position_ms
        self._primary_save_state(position_ms)

    def _set_playback_duration(self, duration_ms: int) -> None:
        self.playback._duration_ms = max(0, int(duration_ms or 0))
        self.playback.durationChanged.emit()
        self.playback.positionChanged.emit()
        self.playback.playbackChanged.emit()

    def _restore_primary_audio(self, *, playing: bool | None = None) -> None:
        if not self._independent_video_owns_audio:
            return
        uri = self._independent_video_primary_uri
        duration_ms = self._independent_video_primary_duration_ms
        position_ms = self._independent_video_primary_position_ms
        should_play = self.playback.playing if playing is None else bool(playing)

        self._clear_independent_video()
        if uri:
            self.playback.player.replace(
                uri,
                position_us=max(0, int(position_ms)) * 1000,
                playing=should_play,
            )
            self._set_playback_duration(duration_ms)
            self._primary_save_state(max(0, int(position_ms)))
            LOGGER.info(
                "Qt restored song audio after independent video at %d ms",
                position_ms,
            )

    def _set_mode(self, mode: str, *, force: bool = False) -> None:
        normalized = "video" if mode == "video" else "audio"
        if normalized == "audio" and self._independent_video_owns_audio:
            should_play = self.playback.playing
            super()._set_mode("audio", force=force)
            self._restore_primary_audio(playing=should_play)
            return
        super()._set_mode(mode, force=force)

    def _apply_resolved(self, request_id: int, stream, error: str) -> None:
        if error or stream is None:
            super()._apply_resolved(request_id, stream, error)
            return

        if isinstance(stream, IndependentVideoPlayback):
            self._apply_independent_video(request_id, stream)
            return

        pending = self._pending.get(request_id)
        current = self.playback.current_item
        if (
            pending is None
            or request_id != self._request
            or current is None
            or current.id != pending[0]
            or not is_independent_video_variant(
                item_kind=current.kind,
                song_duration_ms=self.playback.duration,
                video_duration_ms=stream.duration_ms,
            )
        ):
            super()._apply_resolved(request_id, stream, error)
            return

        # Keep the pending request alive while the video's own audio stream is
        # resolved. Reuse the existing cross-thread Qt signal for the result so
        # all GStreamer/UI mutation still happens on the Qt main thread.
        def worker() -> None:
            try:
                audio = self.backend.youtube.resolve_stream(stream.video_id)
                self._resolved.emit(request_id, IndependentVideoPlayback(stream, audio), "")
            except Exception as exc:
                LOGGER.exception("Qt independent video audio resolve failed")
                self._resolved.emit(request_id, None, str(exc))

        self.backend._executor.submit(worker)

    def _apply_independent_video(
        self,
        request_id: int,
        playback_info: IndependentVideoPlayback,
    ) -> None:
        pending = self._pending.pop(request_id, None)
        if pending is None or request_id != self._request:
            return
        item_id, _previous_mode = pending
        current = self.playback.current_item
        if current is None or current.id != item_id:
            self._set_loading(False)
            return

        primary_uri = str(getattr(self.playback, "current_stream_uri", "") or "")
        if not primary_uri:
            self._set_loading(False)
            self.backend._set_status("Não foi possível preservar o áudio original da música.")
            return

        primary_duration_ms = max(0, int(self.playback.duration or 0))
        primary_position_ms = max(0, int(self.playback.position or 0))
        should_play = self.playback.playing
        video_duration_ms = max(
            0,
            int(
                playback_info.duration_ms
                or playback_info.video.duration_ms
                or primary_duration_ms
            ),
        )

        self._independent_video_primary_uri = primary_uri
        self._independent_video_primary_duration_ms = primary_duration_ms
        self._independent_video_primary_position_ms = primary_position_ms
        self._independent_video_owns_audio = True
        self._primary_save_state(primary_position_ms)

        LOGGER.info(
            "Qt independent music video %s: song=%d ms video=%d ms; restarting with video audio",
            playback_info.video.video_id,
            primary_duration_ms,
            video_duration_ms,
        )
        self.playback.player.replace(
            playback_info.audio.url,
            position_us=0,
            playing=should_play,
        )
        self._set_playback_duration(video_duration_ms)

        self._mode = "video"
        self.modeChanged.emit()
        self._start_video_layer(playback_info.video)

    def _video_failed(self, detail: str) -> None:
        should_restore = self._independent_video_owns_audio
        should_play = self.playback.playing
        super()._video_failed(detail)
        if should_restore:
            self._restore_primary_audio(playing=should_play)

    def _on_video_message(self, bus, message) -> None:
        if self._independent_video_owns_audio and message.type == Gst.MessageType.EOS:
            LOGGER.debug("Ignoring visual EOS; independent video audio owns transport EOS")
            return
        super()._on_video_message(bus, message)

    def _on_primary_player_error(self, error: str):
        if self._independent_video_owns_audio:
            self._video_failed(error)
            return False
        if self._primary_player_error is not None:
            return self._primary_player_error(error)
        return False

    def _on_track_changed(self) -> None:
        self._clear_independent_video()
        super()._on_track_changed()

    def shutdown(self) -> None:
        if self.playback.player.on_error == self._on_primary_player_error:
            self.playback.player.on_error = self._primary_player_error
        if self.playback._save_state == self._save_playback_state:
            self.playback._save_state = self._primary_save_state
        super().shutdown()
        self._qt_glsinkbin = None
        self._qt_video_output = None
