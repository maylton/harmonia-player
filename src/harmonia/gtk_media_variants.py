from __future__ import annotations

import logging
import threading

from gi.repository import GLib, Gst

from .media_variants import IndependentVideoPlayback, is_independent_video_variant

LOGGER = logging.getLogger(__name__)


def install_gtk_media_variants(window_class) -> None:
    """Extend the GTK Music/Video switch with independent videoclip playback.

    The base GTK video layer keeps the song audio running when Song and Video
    share one timeline. If the resolved video's duration is meaningfully
    different, this wrapper resolves audio from the video's own video ID,
    restarts that media at 0:00, and restores the original song/position when
    the user returns to Music.
    """
    if getattr(window_class, "_harmonia_media_variants_installed", False):
        return
    window_class._harmonia_media_variants_installed = True

    original_apply_media_mode = window_class._apply_media_mode
    original_set_media_mode = window_class._set_media_mode
    original_video_failed = window_class._gtk_video_failed
    original_video_message = window_class._on_gtk_video_message
    original_player_error = window_class._player_error
    original_current_playback_state = window_class._current_playback_state
    original_start_stream = window_class._start_stream
    original_play_item = window_class.play_item
    original_stop = window_class._stop_player

    def clear_independent_video(self) -> None:
        self._independent_video_owns_audio = False
        self._independent_video_primary_uri = ""
        self._independent_video_primary_duration_ms = 0
        self._independent_video_primary_position_us = 0

    def set_transport_duration(self, duration_ms: int) -> None:
        duration_ms = max(0, int(duration_ms or 0))
        self.current_duration_ms = duration_ms
        formatted = self._format_time(duration_ms)
        self.duration_label.set_label(formatted)
        self.expanded_duration_label.set_label(formatted)
        self.progress.set_sensitive(duration_ms > 0)
        self.expanded_progress.set_sensitive(duration_ms > 0)
        if getattr(self, "current_item", None) is not None:
            self.mpris.update(self.current_item, duration_ms * 1000)

    def restore_primary_audio(self, *, playing: bool | None = None) -> None:
        if not getattr(self, "_independent_video_owns_audio", False):
            return
        uri = getattr(self, "_independent_video_primary_uri", "")
        duration_ms = max(0, int(getattr(self, "_independent_video_primary_duration_ms", 0)))
        position_us = max(0, int(getattr(self, "_independent_video_primary_position_us", 0)))
        should_play = self._playback_is_playing() if playing is None else bool(playing)

        # Clear first so a source-level failure while restoring cannot recurse
        # through the visual-layer failure path.
        clear_independent_video(self)
        if uri:
            self.player.replace(uri, position_us=position_us, playing=should_play)
            set_transport_duration(self, duration_ms)
            self._save_playback_state(position_us // 1000)
            LOGGER.info(
                "GTK restored song audio after independent video at %d us",
                position_us,
            )

    def apply_independent_video(
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
            return original_apply_media_mode(self, request_id, item_id, None, error)

        primary_uri = str(getattr(self, "_media_primary_stream_uri", "") or "")
        if not primary_uri:
            return original_apply_media_mode(
                self,
                request_id,
                item_id,
                None,
                "Não foi possível preservar o áudio original da música.",
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
        LOGGER.info(
            "GTK independent music video %s: song=%d ms video=%d ms; restarting with video audio",
            playback.video.video_id,
            primary_duration_ms,
            video_duration_ms,
        )
        self.player.replace(playback.audio.url, position_us=0, playing=should_play)
        set_transport_duration(self, video_duration_ms)

        # The existing visual layer now sees the video's audio clock near 0:00,
        # so its normal initial-sync and drift-correction code remains valid.
        return original_apply_media_mode(
            self,
            request_id,
            item_id,
            playback.video,
            "",
        )

    def apply_media_mode(self, request_id: int, item_id: str, stream, error: str) -> bool:
        if error or stream is None:
            return original_apply_media_mode(self, request_id, item_id, stream, error)

        current = getattr(self, "current_item", None)
        if current is None or current.id != item_id:
            return original_apply_media_mode(self, request_id, item_id, stream, error)
        if not is_independent_video_variant(
            item_kind=current.kind,
            song_duration_ms=self.current_duration_ms,
            video_duration_ms=stream.duration_ms,
        ):
            return original_apply_media_mode(self, request_id, item_id, stream, error)

        def worker() -> None:
            try:
                audio = self.youtube.resolve_stream(stream.video_id)
                playback = IndependentVideoPlayback(stream, audio)
                GLib.idle_add(
                    self._apply_independent_video,
                    request_id,
                    item_id,
                    playback,
                    "",
                )
            except Exception as exc:
                GLib.idle_add(
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

    def set_media_mode(self, mode: str, *, force: bool = False) -> None:
        normalized = "video" if mode == "video" else "audio"
        if normalized == "audio" and getattr(self, "_independent_video_owns_audio", False):
            should_play = self._playback_is_playing()
            original_set_media_mode(self, "audio", force=force)
            restore_primary_audio(self, playing=should_play)
            return
        original_set_media_mode(self, mode, force=force)

    def gtk_video_failed(self, detail: str) -> None:
        should_restore = getattr(self, "_independent_video_owns_audio", False)
        should_play = self._playback_is_playing()
        original_video_failed(self, detail)
        if should_restore:
            restore_primary_audio(self, playing=should_play)

    def on_gtk_video_message(self, bus, message) -> None:
        # In independent-video mode the primary playbin owns the video's audio
        # and therefore also owns end-of-stream. The visual-only playbin may post
        # EOS a few frames earlier; do not mistake that harmless race for a
        # failed video and restore the song prematurely.
        if (
            getattr(self, "_independent_video_owns_audio", False)
            and message.type == Gst.MessageType.EOS
        ):
            LOGGER.debug("Ignoring visual EOS; independent video audio owns transport EOS")
            return
        original_video_message(self, bus, message)

    def player_error(self, error: str):
        if getattr(self, "_independent_video_owns_audio", False):
            gtk_video_failed(self, error)
            return False
        return original_player_error(self, error)

    def current_playback_state(self, position_ms: int | None = None):
        if getattr(self, "_independent_video_owns_audio", False):
            position_ms = max(
                0,
                int(getattr(self, "_independent_video_primary_position_us", 0)) // 1000,
            )
        return original_current_playback_state(self, position_ms)

    def wrapped_start_stream(
        self,
        request_id: int,
        url: str,
        duration_ms: int | None,
        playback_tracking_url: str | None = None,
    ):
        if request_id == self._play_request:
            self._media_primary_stream_uri = url
        return original_start_stream(
            self,
            request_id,
            url,
            duration_ms,
            playback_tracking_url,
        )

    def wrapped_play_item(self, item) -> None:
        clear_independent_video(self)
        return original_play_item(self, item)

    def wrapped_stop(self) -> None:
        clear_independent_video(self)
        return original_stop(self)

    window_class._clear_independent_video = clear_independent_video
    window_class._set_media_transport_duration = set_transport_duration
    window_class._restore_primary_audio_after_video = restore_primary_audio
    window_class._apply_independent_video = apply_independent_video
    window_class._apply_media_mode = apply_media_mode
    window_class._set_media_mode = set_media_mode
    window_class._gtk_video_failed = gtk_video_failed
    window_class._on_gtk_video_message = on_gtk_video_message
    window_class._player_error = player_error
    window_class._current_playback_state = current_playback_state
    window_class._start_stream = wrapped_start_stream
    window_class.play_item = wrapped_play_item
    window_class._stop_player = wrapped_stop
