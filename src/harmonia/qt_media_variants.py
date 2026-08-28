from __future__ import annotations

import logging

from .media_variants import IndependentVideoPlayback, is_independent_video_variant
from .qt_video import QtVideoController

LOGGER = logging.getLogger(__name__)


class OfficialVideoQtController(QtVideoController):
    """Qt video controller with YouTube Music-style independent MV semantics."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._independent_video_owns_audio = False
        self._independent_video_primary_uri = ""
        self._independent_video_primary_duration_ms = 0
        self._independent_video_primary_position_ms = 0

    def _clear_independent_video(self) -> None:
        self._independent_video_owns_audio = False
        self._independent_video_primary_uri = ""
        self._independent_video_primary_duration_ms = 0
        self._independent_video_primary_position_ms = 0

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
            self.playback._save_state(max(0, int(position_ms)))
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

    def _on_track_changed(self) -> None:
        self._clear_independent_video()
        super()._on_track_changed()
