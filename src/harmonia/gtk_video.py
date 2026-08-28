from __future__ import annotations

import logging
import threading
import time
from contextlib import suppress

import gi

gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gst, Gtk  # noqa: E402

from .i18n import _  # noqa: E402

LOGGER = logging.getLogger(__name__)


def install_gtk_video(window_class) -> None:
    """Install a synchronized GTK video layer next to the existing audio player.

    Audio remains owned by the original NativePlayer. Video uses a second,
    muted playbin feeding gtk4paintablesink, which lets GTK consume YouTube's
    adaptive video-only formats without disturbing queue, MPRIS, history,
    scrobbling, equalizer or the audio transport.
    """
    if getattr(window_class, "_harmonia_video_installed", False):
        return
    window_class._harmonia_video_installed = True

    original_init = window_class.__init__
    original_play_item = window_class.play_item
    original_stop = window_class._stop_player
    original_seek = window_class._seek_playback

    def video_feature_init(self) -> None:
        self._media_mode = "audio"
        self._media_switch_loading = False
        self._media_switch_request = 0
        self._media_ui_guard = False
        self._gtk_video_generation = 0
        self._gtk_video_sink = None
        self._gtk_video_output = None
        self._gtk_video_player = None
        self._gtk_video_bus = None
        self._gtk_video_sink_available = False
        self._gtk_video_last_sync_seek = 0.0
        self._gtk_video_initial_warmup = False

        artwork_overlay = self.expanded_cover.get_parent()
        frame = artwork_overlay.get_parent() if artwork_overlay is not None else None
        if not isinstance(frame, Gtk.AspectFrame):
            return

        frame.set_child(None)
        media_stack = Gtk.Stack(
            transition_type=Gtk.StackTransitionType.CROSSFADE,
            transition_duration=220,
            hexpand=True,
            vexpand=True,
        )
        media_stack.add_named(artwork_overlay, "audio")

        video_picture = Gtk.Picture(
            content_fit=Gtk.ContentFit.CONTAIN,
            can_shrink=True,
            hexpand=True,
            vexpand=True,
        )
        video_picture.add_css_class("view")
        media_stack.add_named(video_picture, "video")

        media_overlay = Gtk.Overlay(hexpand=True, vexpand=True)
        media_overlay.set_child(media_stack)

        selector = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=4,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.START,
        )
        selector.set_margin_top(12)
        selector.add_css_class("linked")
        audio_button = Gtk.ToggleButton(label=_("Música"))
        video_button = Gtk.ToggleButton(label=_("Vídeo"))
        video_button.set_group(audio_button)
        audio_button.set_active(True)
        spinner = Gtk.Spinner()
        spinner.set_visible(False)
        selector.append(audio_button)
        selector.append(video_button)
        selector.append(spinner)
        media_overlay.add_overlay(selector)
        frame.set_child(media_overlay)

        self._media_visual_frame = frame
        self._media_stack = media_stack
        self._media_audio_button = audio_button
        self._media_video_button = video_button
        self._media_spinner = spinner
        self._expanded_video_picture = video_picture

        sink = Gst.ElementFactory.make("gtk4paintablesink", "harmonia-gtk-video")
        video_player = Gst.ElementFactory.make("playbin", "harmonia-gtk-video-layer")
        fake_audio = Gst.ElementFactory.make("fakesink", "harmonia-gtk-video-muted-audio")
        if sink is not None and video_player is not None:
            try:
                paintable = sink.get_property("paintable")
                video_picture.set_paintable(paintable)

                video_output = sink
                try:
                    gl_context = paintable.get_property("gl-context")
                except Exception:
                    gl_context = None
                if gl_context is not None:
                    glsinkbin = Gst.ElementFactory.make("glsinkbin", "harmonia-gtk-video-bin")
                    if glsinkbin is not None:
                        glsinkbin.set_property("sink", sink)
                        video_output = glsinkbin

                video_player.set_property("video-sink", video_output)
                if fake_audio is not None:
                    fake_audio.set_property("sync", True)
                    video_player.set_property("audio-sink", fake_audio)

                bus = video_player.get_bus()
                bus.add_signal_watch()
                bus.connect("message", self._on_gtk_video_message)

                self._gtk_video_sink = sink
                self._gtk_video_output = video_output
                self._gtk_video_player = video_player
                self._gtk_video_bus = bus
                self._gtk_video_fake_audio = fake_audio
                self._gtk_video_sink_available = True
            except Exception:
                LOGGER.exception("Could not prepare GTK video layer")
                with suppress(Exception):
                    video_player.set_state(Gst.State.NULL)
                self._gtk_video_sink = None
                self._gtk_video_output = None
                self._gtk_video_player = None
                self._gtk_video_bus = None

        audio_button.connect(
            "toggled",
            lambda button: (
                self._set_media_mode("audio")
                if button.get_active() and not self._media_ui_guard
                else None
            ),
        )
        video_button.connect(
            "toggled",
            lambda button: (
                self._set_media_mode("video")
                if button.get_active() and not self._media_ui_guard
                else None
            ),
        )
        self._gtk_video_sync_source = GLib.timeout_add(200, self._sync_gtk_video_transport)
        self._sync_media_mode_ui()

    def sync_media_mode_ui(self) -> None:
        if not hasattr(self, "_media_stack"):
            return
        item = getattr(self, "current_item", None)
        can_video = bool(
            self._gtk_video_sink_available
            and item is not None
            and item.id
            and not item.id.startswith("local:")
            and not getattr(self, "cast_renderer", None)
        )
        self._media_ui_guard = True
        try:
            self._media_audio_button.set_active(self._media_mode == "audio")
            self._media_video_button.set_active(self._media_mode == "video")
        finally:
            self._media_ui_guard = False

        self._media_audio_button.set_sensitive(item is not None)
        self._media_video_button.set_sensitive(can_video and not self._media_switch_loading)
        if not self._gtk_video_sink_available:
            self._media_video_button.set_tooltip_text(
                _("O plugin GStreamer gtk4paintablesink não está disponível.")
            )
        elif item is not None and item.id.startswith("local:"):
            self._media_video_button.set_tooltip_text(
                _("Arquivos locais não possuem vídeo associado no YouTube Music.")
            )
        else:
            self._media_video_button.set_tooltip_text(_("Alternar para o vídeo desta música"))

        self._media_spinner.set_visible(self._media_switch_loading)
        if self._media_switch_loading:
            self._media_spinner.start()
        else:
            self._media_spinner.stop()

        # Keep artwork visible until the secondary player has both preroll and
        # transport position ready. Some adaptive MP4 sources refuse seeking
        # until they briefly enter PLAYING, so the warm-up also stays hidden.
        show_video = self._media_mode == "video" and not self._media_switch_loading
        self._media_stack.set_visible_child_name("video" if show_video else "audio")
        if show_video:
            self._media_visual_frame.set_ratio(16 / 9)
            self._media_visual_frame.set_size_request(512, 288)
        else:
            self._media_visual_frame.set_ratio(1.0)
            self._media_visual_frame.set_size_request(384, 384)

    def set_media_mode(self, mode: str, *, force: bool = False) -> None:
        mode = "video" if mode == "video" else "audio"
        item = getattr(self, "current_item", None)
        if item is None or not getattr(self, "_stream_ready", False):
            self._sync_media_mode_ui()
            return

        if mode == "audio":
            self._media_switch_request += 1
            self._media_switch_loading = False
            self._stop_gtk_video_layer()
            self._media_mode = "audio"
            self._sync_media_mode_ui()
            return

        if self._media_mode == "video" and not force:
            self._sync_media_mode_ui()
            return
        if (
            not self._gtk_video_sink_available
            or item.id.startswith("local:")
            or getattr(self, "cast_renderer", None)
        ):
            self._sync_media_mode_ui()
            return

        self._media_switch_request += 1
        request_id = self._media_switch_request
        item_id = item.id
        self._media_switch_loading = True
        self._sync_media_mode_ui()

        def worker() -> None:
            try:
                stream = self.youtube.resolve_video(
                    item,
                    max_height=720,
                    force=force,
                    allow_video_only=True,
                )
                GLib.idle_add(self._apply_media_mode, request_id, item_id, stream, "")
            except Exception as exc:
                GLib.idle_add(self._apply_media_mode, request_id, item_id, None, str(exc))

        threading.Thread(target=worker, daemon=True, name="media-mode-video").start()

    def apply_media_mode(
        self,
        request_id: int,
        item_id: str,
        stream,
        error: str,
    ) -> bool:
        current = getattr(self, "current_item", None)
        if request_id != self._media_switch_request or current is None or current.id != item_id:
            return GLib.SOURCE_REMOVE

        if error or stream is None:
            self._media_switch_loading = False
            self._media_mode = "audio"
            self._sync_media_mode_ui()
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=_("Não foi possível abrir o vídeo: {error}").format(error=error),
                    timeout=5,
                )
            )
            return GLib.SOURCE_REMOVE

        LOGGER.info(
            "GTK video resolved %s: %sp itag=%s muxed=%s client=%s",
            stream.video_id,
            stream.height,
            stream.itag,
            stream.muxed,
            stream.client,
        )
        self._media_mode = "video"
        self._sync_media_mode_ui()
        self._start_gtk_video_layer(stream)
        return GLib.SOURCE_REMOVE

    def start_gtk_video_layer(self, stream) -> None:
        video_player = self._gtk_video_player
        if video_player is None:
            self._gtk_video_failed(_("A camada de vídeo do GStreamer não está disponível."))
            return

        self._gtk_video_generation += 1
        generation = self._gtk_video_generation
        self._gtk_video_last_sync_seek = 0.0
        self._gtk_video_initial_warmup = False
        try:
            video_player.set_state(Gst.State.READY)
            source_uri = self.player._source_uri(stream.url, stream.request_headers)
            video_player.set_property("uri", source_uri)
            result = video_player.set_state(Gst.State.PAUSED)
            if result == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError(_("A camada de vídeo não conseguiu iniciar o preroll"))
        except Exception as exc:
            self._gtk_video_failed(str(exc))
            return

        GLib.timeout_add(40, self._finish_gtk_video_preroll, generation, 0)

    def finish_gtk_video_preroll(self, generation: int, attempt: int) -> bool:
        if generation != self._gtk_video_generation or self._media_mode != "video":
            return GLib.SOURCE_REMOVE
        video_player = self._gtk_video_player
        if video_player is None:
            return GLib.SOURCE_REMOVE

        result, state, _pending = video_player.get_state(0)
        if result == Gst.StateChangeReturn.FAILURE:
            self._gtk_video_failed(_("O GStreamer falhou ao preparar os frames do vídeo."))
            return GLib.SOURCE_REMOVE
        if state not in (Gst.State.PAUSED, Gst.State.PLAYING):
            if attempt < 100:
                GLib.timeout_add(
                    40,
                    self._finish_gtk_video_preroll,
                    generation,
                    attempt + 1,
                )
            else:
                self._gtk_video_failed(_("O vídeo demorou demais para iniciar."))
            return GLib.SOURCE_REMOVE

        target_us = max(0, int(self._playback_position_us()))
        if target_us <= 250_000:
            self._complete_gtk_video_start(generation)
            return GLib.SOURCE_REMOVE

        if self._seek_gtk_video_position(target_us, accurate=True):
            GLib.timeout_add(60, self._finish_gtk_video_seek, generation, target_us, 0)
            return GLib.SOURCE_REMOVE

        # A number of YouTube adaptive MP4 streams advertise range support but
        # reject a seek while playbin is only PAUSED. Warm the video pipeline in
        # PLAYING while it remains hidden behind the artwork, then retry until
        # demux/source seeking becomes available. The video is muted, so this is
        # invisible and inaudible to the user.
        LOGGER.info(
            "GTK video initial seek was not accepted in PAUSED; warming hidden pipeline"
        )
        self._gtk_video_initial_warmup = True
        result = video_player.set_state(Gst.State.PLAYING)
        if result == Gst.StateChangeReturn.FAILURE:
            self._gtk_video_failed(_("O fluxo de vídeo não conseguiu preparar a sincronização."))
            return GLib.SOURCE_REMOVE
        GLib.timeout_add(100, self._retry_gtk_video_initial_seek, generation, 0)
        return GLib.SOURCE_REMOVE

    def retry_gtk_video_initial_seek(self, generation: int, attempt: int) -> bool:
        if generation != self._gtk_video_generation or self._media_mode != "video":
            return GLib.SOURCE_REMOVE
        video_player = self._gtk_video_player
        if video_player is None:
            return GLib.SOURCE_REMOVE

        result, state, _pending = video_player.get_state(0)
        if result == Gst.StateChangeReturn.FAILURE:
            self._gtk_video_failed(_("O vídeo falhou enquanto preparava a sincronização."))
            return GLib.SOURCE_REMOVE

        target_us = max(0, int(self._playback_position_us()))
        if state in (Gst.State.PAUSED, Gst.State.PLAYING) and self._seek_gtk_video_position(
            target_us,
            accurate=True,
        ):
            self._gtk_video_initial_warmup = False
            if not self._playback_is_playing():
                video_player.set_state(Gst.State.PAUSED)
            LOGGER.info(
                "GTK video initial seek accepted after warm-up at %d us (attempt %d)",
                target_us,
                attempt,
            )
            GLib.timeout_add(60, self._finish_gtk_video_seek, generation, target_us, 0)
            return GLib.SOURCE_REMOVE

        if attempt < 50:
            GLib.timeout_add(
                100,
                self._retry_gtk_video_initial_seek,
                generation,
                attempt + 1,
            )
            return GLib.SOURCE_REMOVE

        self._gtk_video_initial_warmup = False
        self._gtk_video_failed(_("O fluxo de vídeo não ficou disponível para sincronização."))
        return GLib.SOURCE_REMOVE

    def seek_gtk_video_position(
        self,
        target_us: int,
        *,
        accurate: bool = True,
    ) -> bool:
        video_player = self._gtk_video_player
        if video_player is None:
            return False

        target_us = max(0, int(target_us))
        flags = Gst.SeekFlags.FLUSH | (
            Gst.SeekFlags.ACCURATE if accurate else Gst.SeekFlags.KEY_UNIT
        )
        accepted = bool(
            video_player.seek_simple(
                Gst.Format.TIME,
                flags,
                target_us * 1000,
            )
        )
        mode = "accurate" if accurate else "key-unit"
        if not accepted and accurate:
            accepted = bool(
                video_player.seek_simple(
                    Gst.Format.TIME,
                    Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                    target_us * 1000,
                )
            )
            mode = "key-unit-fallback"
        if accepted:
            self._gtk_video_last_sync_seek = time.monotonic()
        LOGGER.debug(
            "GTK video seek target=%d us mode=%s accepted=%s",
            target_us,
            mode,
            accepted,
        )
        return accepted

    def finish_gtk_video_seek(
        self,
        generation: int,
        target_us: int,
        attempt: int,
    ) -> bool:
        if generation != self._gtk_video_generation or self._media_mode != "video":
            return GLib.SOURCE_REMOVE
        video_player = self._gtk_video_player
        if video_player is None:
            return GLib.SOURCE_REMOVE

        result, state, _pending = video_player.get_state(0)
        if result == Gst.StateChangeReturn.FAILURE:
            self._gtk_video_failed(_("O GStreamer falhou durante a sincronização do vídeo."))
            return GLib.SOURCE_REMOVE

        ok, video_ns = video_player.query_position(Gst.Format.TIME)
        video_us = max(0, int(video_ns // 1000)) if ok else -1
        audio_us = max(0, int(self._playback_position_us()))
        drift_us = audio_us - video_us if video_us >= 0 else -1

        # Compare against the audio clock *now*, not only against the position at
        # which the seek was issued. Audio keeps advancing during network flush
        # and decoder preroll, especially on the first video switch.
        if ok and abs(drift_us) <= 1_000_000:
            LOGGER.info(
                "GTK video initial sync settled: audio=%d us video=%d us drift=%d us",
                audio_us,
                video_us,
                drift_us,
            )
            self._complete_gtk_video_start(generation)
            return GLib.SOURCE_REMOVE

        # Refresh the target a few times while the video remains hidden. This
        # avoids chasing an old timestamp if the initial seek itself took a
        # second or more to flush and preroll.
        if attempt in (15, 35, 55):
            retry_target = audio_us
            if self._seek_gtk_video_position(retry_target, accurate=True):
                target_us = retry_target

        if attempt < 75:
            GLib.timeout_add(
                60,
                self._finish_gtk_video_seek,
                generation,
                target_us,
                attempt + 1,
            )
            return GLib.SOURCE_REMOVE

        LOGGER.warning(
            "GTK video sync did not settle: requested=%d us audio=%d us video=%d us",
            target_us,
            audio_us,
            video_us,
        )
        self._gtk_video_failed(_("Não foi possível sincronizar o vídeo com a música."))
        return GLib.SOURCE_REMOVE

    def complete_gtk_video_start(self, generation: int) -> None:
        if generation != self._gtk_video_generation or self._media_mode != "video":
            return
        video_player = self._gtk_video_player
        if video_player is None:
            return

        self._gtk_video_initial_warmup = False
        video_player.set_state(
            Gst.State.PLAYING if self._playback_is_playing() else Gst.State.PAUSED
        )
        self._media_switch_loading = False
        self._sync_media_mode_ui()
        audio_us = max(0, int(self._playback_position_us()))
        ok, video_ns = video_player.query_position(Gst.Format.TIME)
        video_us = max(0, int(video_ns // 1000)) if ok else -1
        LOGGER.info(
            "GTK video layer visible: audio=%d us video=%d us drift=%d us",
            audio_us,
            video_us,
            audio_us - video_us if video_us >= 0 else -1,
        )

    def sync_gtk_video_transport(self) -> bool:
        if self._media_mode != "video" or self._media_switch_loading:
            return GLib.SOURCE_CONTINUE
        video_player = self._gtk_video_player
        if video_player is None:
            return GLib.SOURCE_CONTINUE

        _result, state, _pending = video_player.get_state(0)
        desired = Gst.State.PLAYING if self._playback_is_playing() else Gst.State.PAUSED
        if state in (Gst.State.PLAYING, Gst.State.PAUSED) and state != desired:
            video_player.set_state(desired)

        ok, video_ns = video_player.query_position(Gst.Format.TIME)
        if not ok:
            return GLib.SOURCE_CONTINUE
        audio_us = max(0, int(self._playback_position_us()))
        video_us = max(0, int(video_ns // 1000))
        drift_us = audio_us - video_us

        # Independent playbins share the same wall clock closely enough that
        # corrections should be rare. A short cooldown prevents seek storms on
        # fragmented MP4 while still correcting visible A/V drift quickly.
        if (
            abs(drift_us) > 500_000
            and time.monotonic() - self._gtk_video_last_sync_seek >= 1.0
        ):
            LOGGER.info(
                "GTK video drift correction: audio=%d us video=%d us drift=%d us",
                audio_us,
                video_us,
                drift_us,
            )
            self._seek_gtk_video_position(audio_us, accurate=True)
        return GLib.SOURCE_CONTINUE

    def stop_gtk_video_layer(self) -> None:
        self._gtk_video_generation += 1
        self._gtk_video_last_sync_seek = 0.0
        self._gtk_video_initial_warmup = False
        if self._gtk_video_player is not None:
            with suppress(Exception):
                self._gtk_video_player.set_state(Gst.State.READY)

    def gtk_video_failed(self, detail: str) -> None:
        LOGGER.error("GTK video layer failed: %s", detail)
        self._gtk_video_generation += 1
        self._gtk_video_initial_warmup = False
        if self._gtk_video_player is not None:
            with suppress(Exception):
                self._gtk_video_player.set_state(Gst.State.READY)
        self._media_switch_loading = False
        self._media_mode = "audio"
        self._sync_media_mode_ui()
        self.toast_overlay.add_toast(
            Adw.Toast(title=_("O vídeo falhou; voltando para a música…"), timeout=3)
        )

    def on_gtk_video_message(self, _bus, message) -> None:
        if message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            try:
                source = message.src.get_path_string() if message.src is not None else "unknown"
            except Exception:
                source = "unknown"
            LOGGER.error(
                "GTK video GStreamer error from %s: %s (%s)",
                source,
                error,
                debug or "sem debug",
            )
            if self._media_mode == "video":
                self._gtk_video_failed(str(error))
        elif message.type == Gst.MessageType.EOS and self._media_mode == "video":
            self._gtk_video_failed(_("O vídeo terminou antes da faixa de áudio."))

    def wrapped_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._video_feature_init()

    def wrapped_play_item(self, item) -> None:
        if hasattr(self, "_media_switch_request"):
            self._media_switch_request += 1
            self._media_switch_loading = False
            self._stop_gtk_video_layer()
            self._media_mode = "audio"
            self._sync_media_mode_ui()
        return original_play_item(self, item)

    def wrapped_stop(self) -> None:
        if hasattr(self, "_media_switch_request"):
            self._media_switch_request += 1
            self._media_switch_loading = False
            self._stop_gtk_video_layer()
            self._media_mode = "audio"
            self._sync_media_mode_ui()
        return original_stop(self)

    def wrapped_seek(self, position_us: int) -> bool:
        accepted = bool(original_seek(self, position_us))
        if (
            accepted
            and getattr(self, "_media_mode", "audio") == "video"
            and not getattr(self, "_media_switch_loading", False)
            and getattr(self, "_gtk_video_player", None) is not None
        ):
            self._seek_gtk_video_position(position_us, accurate=True)
        return accepted

    window_class._video_feature_init = video_feature_init
    window_class._sync_media_mode_ui = sync_media_mode_ui
    window_class._set_media_mode = set_media_mode
    window_class._apply_media_mode = apply_media_mode
    window_class._start_gtk_video_layer = start_gtk_video_layer
    window_class._finish_gtk_video_preroll = finish_gtk_video_preroll
    window_class._retry_gtk_video_initial_seek = retry_gtk_video_initial_seek
    window_class._seek_gtk_video_position = seek_gtk_video_position
    window_class._finish_gtk_video_seek = finish_gtk_video_seek
    window_class._complete_gtk_video_start = complete_gtk_video_start
    window_class._sync_gtk_video_transport = sync_gtk_video_transport
    window_class._stop_gtk_video_layer = stop_gtk_video_layer
    window_class._gtk_video_failed = gtk_video_failed
    window_class._on_gtk_video_message = on_gtk_video_message
    window_class.__init__ = wrapped_init
    window_class.play_item = wrapped_play_item
    window_class._stop_player = wrapped_stop
    window_class._seek_playback = wrapped_seek
