from __future__ import annotations

import threading

import gi

gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gst, Gtk  # noqa: E402

from .i18n import _  # noqa: E402


def install_gtk_video(window_class) -> None:
    """Install the optional video surface without coupling it to the GTK window core.

    Harmonia's GTK window predates the Qt frontend and intentionally keeps its
    large layout builder stable. This extension wraps only the playback hooks
    needed by Music/Video mode and replaces the existing expanded artwork child
    with a stack containing that same artwork plus a GStreamer paintable.
    """
    if getattr(window_class, "_harmonia_video_installed", False):
        return
    window_class._harmonia_video_installed = True

    original_init = window_class.__init__
    original_play_item = window_class.play_item
    original_stop = window_class._stop_player
    original_player_error = window_class._player_error

    def video_feature_init(self) -> None:
        self._media_mode = "audio"
        self._media_switch_loading = False
        self._media_switch_request = 0
        self._media_ui_guard = False
        self._gtk_video_sink = None
        self._gtk_video_output = None
        self._gtk_video_sink_available = False

        artwork_overlay = self.expanded_cover.get_parent()
        frame = artwork_overlay.get_parent() if artwork_overlay is not None else None
        if not isinstance(frame, Gtk.AspectFrame):
            return

        # Preserve the exact artwork composition already used by the expanded
        # player; only its parent becomes a cross-fading media stack.
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
        if sink is not None:
            try:
                paintable = sink.get_property("paintable")
                video_picture.set_paintable(paintable)

                # gtk4paintablesink can consume ordinary system-memory frames,
                # but when GTK exposes a GL context GStreamer recommends putting
                # it behind glsinkbin.  glsinkbin performs the GL upload/color
                # conversion and makes playbin negotiation considerably more
                # robust across Mesa/Wayland/X11 drivers and decoder output
                # formats.  Keep the direct sink as a safe non-GL fallback.
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

                self.player.set_video_sink(video_output)
                self._gtk_video_sink = sink
                self._gtk_video_output = video_output
                self._gtk_video_sink_available = True
            except Exception:
                self.player.set_video_sink(None)
                self._gtk_video_sink = None
                self._gtk_video_output = None

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

        self._media_audio_button.set_sensitive(
            item is not None and not (self._media_switch_loading and self._media_mode == "video")
        )
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

        self._media_stack.set_visible_child_name(self._media_mode)
        if self._media_mode == "video":
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
        if mode == self._media_mode and not force:
            self._sync_media_mode_ui()
            return
        if mode == "video" and (
            not self._gtk_video_sink_available
            or item.id.startswith("local:")
            or getattr(self, "cast_renderer", None)
        ):
            self._sync_media_mode_ui()
            return

        position_us = max(0, int(self._playback_position_us()))
        was_playing = bool(self._playback_is_playing())
        self._media_switch_request += 1
        request_id = self._media_switch_request
        item_id = item.id
        previous_mode = self._media_mode
        self._media_switch_loading = True
        self._sync_media_mode_ui()

        def worker() -> None:
            try:
                if mode == "video":
                    stream = self.youtube.resolve_video(item, max_height=720, force=force)
                else:
                    stream = self.youtube.resolve_stream(item.id, force=force)
                GLib.idle_add(
                    self._apply_media_mode,
                    request_id,
                    item_id,
                    mode,
                    previous_mode,
                    stream,
                    position_us,
                    was_playing,
                    "",
                )
            except Exception as exc:
                GLib.idle_add(
                    self._apply_media_mode,
                    request_id,
                    item_id,
                    mode,
                    previous_mode,
                    None,
                    position_us,
                    was_playing,
                    str(exc),
                )

        threading.Thread(target=worker, daemon=True, name=f"media-mode-{mode}").start()

    def apply_media_mode(
        self,
        request_id: int,
        item_id: str,
        mode: str,
        previous_mode: str,
        stream,
        position_us: int,
        was_playing: bool,
        error: str,
    ) -> bool:
        current = getattr(self, "current_item", None)
        if request_id != self._media_switch_request or current is None or current.id != item_id:
            return GLib.SOURCE_REMOVE
        self._media_switch_loading = False
        if error or stream is None:
            self._media_mode = previous_mode
            self._sync_media_mode_ui()
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=_("Não foi possível abrir o vídeo: {error}").format(error=error)
                    if mode == "video"
                    else _("Não foi possível voltar para a música: {error}").format(error=error),
                    timeout=5,
                )
            )
            return GLib.SOURCE_REMOVE

        self._media_mode = mode
        if getattr(stream, "duration_ms", None):
            self.current_duration_ms = int(stream.duration_ms)
            duration = self._format_time(self.current_duration_ms)
            self.duration_label.set_label(duration)
            self.expanded_duration_label.set_label(duration)
        self._sync_media_mode_ui()
        self.player.replace(stream.url, position_us, playing=was_playing)
        self.mpris.update(self.current_item, self.current_duration_ms * 1000)
        return GLib.SOURCE_REMOVE

    def wrapped_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._video_feature_init()

    def wrapped_play_item(self, item) -> None:
        if hasattr(self, "_media_switch_request"):
            self._media_switch_request += 1
            self._media_switch_loading = False
            self._media_mode = "audio"
            self._sync_media_mode_ui()
        return original_play_item(self, item)

    def wrapped_stop(self) -> None:
        if hasattr(self, "_media_switch_request"):
            self._media_switch_request += 1
            self._media_switch_loading = False
            self._media_mode = "audio"
            self._sync_media_mode_ui()
        return original_stop(self)

    def wrapped_player_error(self, error: str):
        if (
            getattr(self, "_media_mode", "audio") == "video"
            and getattr(self, "current_item", None) is not None
        ):
            self.toast_overlay.add_toast(
                Adw.Toast(title=_("O vídeo falhou; voltando para a música…"), timeout=3)
            )
            self._set_media_mode("audio", force=True)
            return False
        return original_player_error(self, error)

    window_class._video_feature_init = video_feature_init
    window_class._sync_media_mode_ui = sync_media_mode_ui
    window_class._set_media_mode = set_media_mode
    window_class._apply_media_mode = apply_media_mode
    window_class.__init__ = wrapped_init
    window_class.play_item = wrapped_play_item
    window_class._stop_player = wrapped_stop
    window_class._player_error = wrapped_player_error
