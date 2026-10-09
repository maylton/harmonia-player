from __future__ import annotations

import logging
import threading

from gi.repository import GLib, Gst

from .i18n import _
from .media_variants import IndependentVideoPlayback, is_independent_video_variant
from .ui import deliver_to_main

LOGGER = logging.getLogger(__name__)


class GtkMediaVariantsMixin:
    """Independent official-video playback for the GTK media switch.

    When a song's official video differs from the track, the video brings its
    own audio; this layer wraps the video layer to swap the audio and back.
    """

    def _clear_independent_video(self) -> None:
        self._independent_video_owns_audio = False
        self._independent_video_primary_uri = ""
        self._independent_video_primary_duration_ms = 0
        self._independent_video_primary_position_us = 0

    def _set_media_transport_duration(self, duration_ms: int) -> None:
        duration_ms = max(0, int(duration_ms or 0))
        self.current_duration_ms = duration_ms
        formatted = self._format_time(duration_ms)
        self.duration_label.set_label(formatted)
        self.expanded_duration_label.set_label(formatted)
        self.progress.set_sensitive(duration_ms > 0)
        self.expanded_progress.set_sensitive(duration_ms > 0)
        if getattr(self, "current_item", None) is not None:
            self.mpris.update(self.current_item, duration_ms * 1000)

    def _restore_primary_audio_after_video(self, *, playing: bool | None = None) -> None:
        if not getattr(self, "_independent_video_owns_audio", False):
            return
        uri = getattr(self, "_independent_video_primary_uri", "")
        duration_ms = max(0, int(getattr(self, "_independent_video_primary_duration_ms", 0)))
        position_us = max(0, int(getattr(self, "_independent_video_primary_position_us", 0)))
        should_play = self._playback_is_playing() if playing is None else bool(playing)

        # Clear ownership before replacing the source to avoid recursive recovery.
        self._clear_independent_video()
        if uri:
            self.player.replace(uri, position_us=position_us, playing=should_play)
            self._set_media_transport_duration(duration_ms)
            self._save_playback_state(position_us // 1000)
            LOGGER.debug("Restored song audio at %d us", position_us)

    def _apply_independent_video(
        self,
        request_id: int,
        item_id: str,
        playback: IndependentVideoPlayback | None,
        error: str,
    ) -> bool:
        current = getattr(self, "current_item", None)
        if request_id != self._media_switch_request or current is None or current.id != item_id:
            return GLib.SOURCE_REMOVE
        if error or playback is None:
            return super()._apply_media_mode(request_id, item_id, None, error)

        primary_uri = str(getattr(self, "_media_primary_stream_uri", "") or "")
        if not primary_uri:
            return super()._apply_media_mode(
                request_id,
                item_id,
                None,
                _("Não foi possível preservar o áudio original da música."),
            )

        primary_position_us = max(0, int(self._playback_position_us()))
        primary_duration_ms = max(0, int(self.current_duration_ms or 0))
        should_play = self._playback_is_playing()

        self._independent_video_primary_uri = primary_uri
        self._independent_video_primary_duration_ms = primary_duration_ms
        self._independent_video_primary_position_us = primary_position_us
        self._independent_video_owns_audio = True
        self._save_playback_state(primary_position_us // 1000)

        video_duration_ms = max(
            0,
            int(playback.duration_ms or playback.video.duration_ms or primary_duration_ms),
        )
        LOGGER.debug(
            "Starting independent video %s: song=%d ms video=%d ms",
            playback.video.video_id,
            primary_duration_ms,
            video_duration_ms,
        )
        self.player.replace(playback.audio.url, position_us=0, playing=should_play)
        self._set_media_transport_duration(video_duration_ms)
        return super()._apply_media_mode(
            request_id,
            item_id,
            playback.video,
            "",
        )

    def _apply_media_mode(self, request_id: int, item_id: str, stream, error: str) -> bool:
        if error or stream is None:
            return super()._apply_media_mode(request_id, item_id, stream, error)

        current = getattr(self, "current_item", None)
        if current is None or current.id != item_id:
            return super()._apply_media_mode(request_id, item_id, stream, error)
        if not is_independent_video_variant(
            item_kind=current.kind,
            song_duration_ms=self.current_duration_ms,
            video_duration_ms=stream.duration_ms,
        ):
            return super()._apply_media_mode(request_id, item_id, stream, error)

        def worker() -> None:
            try:
                audio = self.youtube.resolve_stream(stream.video_id)
                playback = IndependentVideoPlayback(stream, audio)
                deliver_to_main(
                    self._apply_independent_video,
                    request_id,
                    item_id,
                    playback,
                    "",
                )
            except Exception as exc:
                deliver_to_main(
                    self._apply_independent_video,
                    request_id,
                    item_id,
                    None,
                    str(exc),
                )

        threading.Thread(
            target=worker,
            daemon=True,
            name="independent-video-audio",
        ).start()
        return GLib.SOURCE_REMOVE

    def _set_media_mode(self, mode: str, *, force: bool = False) -> None:
        normalized = "video" if mode == "video" else "audio"
        if normalized == "audio" and getattr(self, "_independent_video_owns_audio", False):
            should_play = self._playback_is_playing()
            super()._set_media_mode("audio", force=force)
            self._restore_primary_audio_after_video(playing=should_play)
            return
        super()._set_media_mode(mode, force=force)

    def _gtk_video_failed(self, detail: str) -> None:
        should_restore = getattr(self, "_independent_video_owns_audio", False)
        should_play = self._playback_is_playing()
        super()._gtk_video_failed(detail)
        if should_restore:
            self._restore_primary_audio_after_video(playing=should_play)

    def _on_gtk_video_message(self, bus, message) -> None:
        # The audio transport owns EOS for independent videos.
        if (
            getattr(self, "_independent_video_owns_audio", False)
            and message.type == Gst.MessageType.EOS
        ):
            LOGGER.debug("Ignoring visual EOS; independent video audio owns transport EOS")
            return
        super()._on_gtk_video_message(bus, message)

    def _player_error(self, error: str):
        if getattr(self, "_independent_video_owns_audio", False):
            self._gtk_video_failed(error)
            return False
        return super()._player_error(error)

    def _current_playback_state(self, position_ms: int | None = None):
        if getattr(self, "_independent_video_owns_audio", False):
            position_ms = max(
                0,
                int(getattr(self, "_independent_video_primary_position_us", 0)) // 1000,
            )
        return super()._current_playback_state(position_ms)

    def _start_stream(
        self,
        request_id: int,
        url: str,
        duration_ms: int | None,
        playback_tracking_url: str | None = None,
        loudness_db: float | None = None,
    ):
        if request_id == self._play_request:
            self._media_primary_stream_uri = url
        return super()._start_stream(
            request_id,
            url,
            duration_ms,
            playback_tracking_url,
            loudness_db,
        )

    def play_item(self, item) -> None:
        self._clear_independent_video()
        return super().play_item(item)

    def _stop_player(self) -> None:
        self._clear_independent_video()
        return super()._stop_player()
