from __future__ import annotations

import logging
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from .i18n import _
from .models import (
    LibraryItem,
    PlaybackState,
)
from .playback_state import (
    filter_new_recommendations,
    move_queue_item,
    radio_seed_for_autoplay,
    remove_queue_item,
    shuffled_queue_keep_current,
)
from .ui import (
    set_icon_selected,
)

LOGGER = logging.getLogger(__name__)


class WindowPlaybackMixin:
    def _current_playback_state(self, position_ms: int | None = None) -> PlaybackState:
        if position_ms is None:
            position_ms = (
                self._playback_position_us() // 1000
                if self._stream_ready
                else self._restored_position_ms
            )
        return PlaybackState(
            list(self.queue),
            list(self.related_items),
            max(0, self.queue_index),
            max(0, position_ms),
            self.shuffle_enabled,
            self.repeat_enabled,
            self.autoplay_enabled,
        )

    def _save_playback_state(self, position_ms: int | None = None) -> None:
        if not self.queue:
            return
        self.storage.save_playback_state(self._current_playback_state(position_ms))
        self._last_queue_save = time.monotonic()

    def _restore_playback_state(self) -> None:
        state = self.storage.load_playback_state()
        if state is None or not state.queue:
            return
        self.queue = state.queue
        self.related_items = state.related
        self.queue_index = state.index
        self.shuffle_enabled = state.shuffle
        self.repeat_enabled = state.repeat
        self.autoplay_enabled = state.autoplay
        self._restored_position_ms = state.position_ms
        self.current_item = self.queue[self.queue_index]
        self.now_title.set_label(self.current_item.title)
        self.now_subtitle.set_label(self.current_item.subtitle or "YouTube Music")
        if self.current_item.thumbnail:
            self._load_artwork(self.current_item.thumbnail, self.now_cover, size=128)
        self.elapsed_label.set_label(self._format_time(state.position_ms))
        self._set_footer_item_state(True)
        for control in self.shuffle_buttons:
            set_icon_selected(control, state.shuffle)
        for control in self.repeat_buttons:
            set_icon_selected(control, state.repeat)
        set_icon_selected(self.autoplay_button, state.autoplay)
        self._render_queue()
        self._refresh_expanded_player()

    def set_queue(self, items: list[LibraryItem], index: int = 0) -> None:
        if not items:
            return
        self._autoplay_request += 1
        self._autoplay_loading = False
        self._waiting_for_autoplay = False
        self.related_items = []
        self.queue = list(items)
        self.queue_index = max(0, min(index, len(items) - 1))
        self._render_queue()
        self._save_playback_state()
        self.play_item(self.queue[self.queue_index])
        self._ensure_autoplay()

    def _play_next(self):
        if self.queue_index + 1 < len(self.queue):
            self.queue_index += 1
            self._render_queue()
            self.play_item(self.queue[self.queue_index])
            self._ensure_autoplay()
        elif self.repeat_enabled and self.queue:
            self.queue_index = 0
            self._render_queue()
            self.play_item(self.queue[0])
        elif self.autoplay_enabled and self.queue:
            if self.related_items:
                self._promote_related(self.related_items[0], play_next=False)
                self._play_next()
            else:
                self._waiting_for_autoplay = True
                self._ensure_autoplay(force=True)
        return False

    def _play_previous(self):
        if self._playback_position_us() > 3_000_000:
            self.play_item(self.queue[self.queue_index])
        elif self.queue_index > 0:
            self.queue_index -= 1
            self._render_queue()
            self.play_item(self.queue[self.queue_index])
        return False

    def _toggle_shuffle(self, button: Gtk.Button) -> None:
        self._set_shuffle(not self.shuffle_enabled)

    def _set_shuffle(self, enabled: bool) -> None:
        if enabled == self.shuffle_enabled:
            return
        self.shuffle_enabled = enabled
        if self.shuffle_enabled and self.queue:
            self.queue, self.queue_index = shuffled_queue_keep_current(self.queue, self.queue_index)
            self._render_queue()
            self._save_playback_state()
        for control in self.shuffle_buttons:
            set_icon_selected(control, self.shuffle_enabled)
        self._save_playback_state()

    def _toggle_repeat(self, button: Gtk.Button) -> None:
        self._set_repeat(not self.repeat_enabled)

    def _set_repeat(self, enabled: bool) -> None:
        if enabled == self.repeat_enabled:
            return
        self.repeat_enabled = enabled
        for control in self.repeat_buttons:
            set_icon_selected(control, self.repeat_enabled)
        self._save_playback_state()

    def _toggle_autoplay(self, button: Gtk.Button) -> None:
        self.autoplay_enabled = not self.autoplay_enabled
        self._waiting_for_autoplay = False
        if self.autoplay_enabled:
            set_icon_selected(button, True)
            button.set_tooltip_text(_("Reprodução automática ativada"))
            self.toast_overlay.add_toast(Adw.Toast(title=_("Reprodução automática ativada")))
            self._ensure_autoplay()
        else:
            self._autoplay_request += 1
            self._autoplay_loading = False
            set_icon_selected(button, False)
            button.set_tooltip_text(_("Reprodução automática desativada"))
            self.toast_overlay.add_toast(Adw.Toast(title=_("Reprodução automática desativada")))
        self._save_playback_state()

    def _ensure_autoplay(self, force: bool = False) -> None:
        if not self.autoplay_enabled or not self.queue or self._autoplay_loading:
            return
        if self.related_items:
            if self._waiting_for_autoplay:
                self._waiting_for_autoplay = False
                self._promote_related(self.related_items[0], play_next=False)
                self._play_next()
            return
        seed = radio_seed_for_autoplay(self.queue, self.queue_index, force=force)
        if seed is None:
            return
        self._autoplay_request += 1
        request_id = self._autoplay_request
        self._autoplay_loading = True

        def worker():
            try:
                recommendations = self.youtube.radio(seed.id)
                GLib.idle_add(self._autoplay_loaded, request_id, recommendations, None)
            except Exception as exc:
                GLib.idle_add(self._autoplay_loaded, request_id, None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _autoplay_loaded(
        self, request_id: int, recommendations: list[LibraryItem] | None, error: str | None
    ):
        if request_id != self._autoplay_request:
            return False
        self._autoplay_loading = False
        if error:
            if self._waiting_for_autoplay:
                self.toast_overlay.add_toast(
                    Adw.Toast(
                        title=_("Não foi possível continuar a rádio: {error}").format(error=error),
                        timeout=5,
                    )
                )
            self._waiting_for_autoplay = False
            return False
        self.related_items = filter_new_recommendations(self.queue, recommendations)
        self._render_queue()
        self._save_playback_state()
        if self._waiting_for_autoplay and self.related_items:
            self._waiting_for_autoplay = False
            self._promote_related(self.related_items[0], play_next=False)
            self._play_next()
        elif self._waiting_for_autoplay:
            self._waiting_for_autoplay = False
            self.toast_overlay.add_toast(
                Adw.Toast(title=_("A rádio não encontrou novas músicas"), timeout=4)
            )
        return False

    def _render_queue(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.add_css_class("queue-popover")
        heading = Gtk.Label(label=_("Fila de reprodução"), xalign=0)
        heading.add_css_class("section-title")
        box.append(heading)
        scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            min_content_width=360,
            max_content_height=430,
            propagate_natural_height=True,
        )
        listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        listing.add_css_class("boxed-list")
        for position, item in enumerate(self.queue):
            row = Adw.ActionRow()
            row.set_use_markup(False)
            row.set_title(item.title)
            row.set_subtitle(item.subtitle)
            row.set_activatable(True)
            if position == self.queue_index:
                row.add_prefix(Gtk.Image.new_from_icon_name("audio-volume-high-symbolic"))
                row.add_css_class("current-track")
            controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            up = Gtk.Button(icon_name="go-up-symbolic", tooltip_text=_("Mover para cima"))
            down = Gtk.Button(icon_name="go-down-symbolic", tooltip_text=_("Mover para baixo"))
            remove = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text=_("Remover da fila"))
            for control in (up, down, remove):
                control.add_css_class("flat")
                controls.append(control)
            up.set_sensitive(position > 0)
            down.set_sensitive(position + 1 < len(self.queue))
            up.connect(
                "clicked",
                lambda *_args, selected=position: GLib.idle_add(
                    self._move_queue_item, selected, -1
                ),
            )
            down.connect(
                "clicked",
                lambda *_args, selected=position: GLib.idle_add(self._move_queue_item, selected, 1),
            )
            remove.connect(
                "clicked",
                lambda *_args, selected=position: GLib.idle_add(self._remove_queue_item, selected),
            )
            row.add_suffix(controls)
            row.connect(
                "activated", lambda _row, selected=position: self._select_queue_item(selected)
            )
            listing.append(row)
        scroll.set_child(listing)
        box.append(scroll)
        related_heading = Gtk.Label(label=_("Relacionadas"), xalign=0)
        related_heading.add_css_class("section-title")
        box.append(related_heading)
        if self.related_items:
            related = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            related.add_css_class("boxed-list")
            for item in self.related_items[:12]:
                row = Adw.ActionRow()
                row.set_use_markup(False)
                row.set_title(item.title)
                row.set_subtitle(item.subtitle)
                next_button = Gtk.Button(
                    icon_name="media-playlist-consecutive-symbolic",
                    tooltip_text=_("Tocar em seguida"),
                )
                add_button = Gtk.Button(
                    icon_name="list-add-symbolic", tooltip_text=_("Adicionar ao fim")
                )
                for button in (next_button, add_button):
                    button.add_css_class("flat")
                    row.add_suffix(button)
                next_button.connect(
                    "clicked",
                    lambda *_args, selected=item: GLib.idle_add(
                        self._promote_related, selected, True
                    ),
                )
                add_button.connect(
                    "clicked",
                    lambda *_args, selected=item: GLib.idle_add(
                        self._promote_related, selected, False
                    ),
                )
                related.append(row)
            box.append(related)
        else:
            note = Gtk.Label(
                label=_("As recomendações aparecem conforme a fila avança."), xalign=0, wrap=True
            )
            note.add_css_class("dim-label")
            box.append(note)
        self.queue_popover.set_child(box)
        self._render_expanded_related()

    def _move_queue_item(self, position: int, direction: int) -> None:
        self.queue_index, changed = move_queue_item(
            self.queue,
            self.queue_index,
            position,
            direction,
        )
        if not changed:
            return
        self._render_queue()
        self._save_playback_state()

    def _remove_queue_item(self, position: int) -> None:
        result = remove_queue_item(self.queue, self.queue_index, position)
        if result is None:
            return
        self.queue_index = result.index
        if result.empty:
            self._stop_player()
            return
        self._render_queue()
        self._save_playback_state()
        if result.removed_current:
            self.play_item(self.queue[self.queue_index])

    def _promote_related(self, item: LibraryItem, play_next: bool) -> None:
        self.related_items = [
            candidate for candidate in self.related_items if candidate.id != item.id
        ]
        position = min(len(self.queue), self.queue_index + 1) if play_next else len(self.queue)
        self.queue.insert(position, item)
        self._render_queue()
        self._save_playback_state()

    def _select_queue_item(self, position: int) -> None:
        self.queue_index = position
        self._render_queue()
        self.queue_popover.popdown()
        self._save_playback_state()
        self.play_item(self.queue[position])

    def play_item(self, item: LibraryItem) -> None:
        resume_position = (
            self._restored_position_ms if getattr(self, "current_item", None) is item else 0
        )
        self._restored_position_ms = 0
        self._pending_seek_ms = resume_position
        self._play_request += 1
        request_id = self._play_request
        self._stream_ready = False
        self._stream_recovery_attempts = 0
        self._lyrics_request += 1
        self.current_lyrics_document = None
        self._lyrics_item_id = None
        for view in self._lyric_views:
            view["generation"] += 1
            view["follow_generation"] += 1
        self._lyric_views.clear()
        self._active_lyric_index = -1
        self.current_item = item
        self._refresh_detail_track_states()
        self._refresh_home_song_rows()
        self._set_footer_item_state(True)
        self.now_title.set_label(item.title)
        self.now_subtitle.set_label(item.subtitle or "YouTube Music")
        if item.thumbnail:
            self._load_artwork(item.thumbnail, self.now_cover, size=128)
        else:
            self.now_cover.set_paintable(None)
            self.ambient_background.set_paintable(None)
        self._refresh_expanded_player()
        self.player_bar.set_visible(not self.expanded_revealer.get_reveal_child())
        self.play_button.set_sensitive(False)
        self.expanded_play_button.set_sensitive(False)
        self.progress.set_sensitive(False)
        self.progress.set_value(0)
        self.expanded_progress.set_sensitive(False)
        self.expanded_progress.set_value(0)
        self.elapsed_label.set_label(_("0:00"))
        self.expanded_elapsed_label.set_label(_("0:00"))
        self.duration_label.set_label(_("0:00"))
        self.expanded_duration_label.set_label(_("0:00"))
        self.toast_overlay.add_toast(
            Adw.Toast(title=_("Preparando {title}…").format(title=item.title), timeout=2)
        )
        if self.lyrics_button.get_active() or (
            self.expanded_revealer.get_reveal_child()
            and self.expanded_stack.get_visible_child_name() == "lyrics"
        ):
            GLib.idle_add(self._load_current_lyrics)

        def worker():
            try:
                if item.id.startswith("local:"):
                    local_path = self.storage.local_media_path(item.id)
                    if not local_path or not local_path.is_file():
                        raise FileNotFoundError(_("O arquivo local não está mais disponível"))
                    GLib.idle_add(self._start_stream, request_id, local_path.as_uri(), None, None)
                    return
                offline_path = self.downloads.offline_path(item.id)
                if offline_path:
                    GLib.idle_add(self._start_stream, request_id, offline_path.as_uri(), None, None)
                    return
                stream = self.youtube.resolve_stream(item.id)
                GLib.idle_add(
                    self._start_stream,
                    request_id,
                    stream.url,
                    stream.duration_ms,
                    stream.playback_tracking_url,
                )
            except Exception as exc:
                GLib.idle_add(self._play_request_error, request_id, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _start_stream(
        self,
        request_id: int,
        url: str,
        duration_ms: int | None,
        playback_tracking_url: str | None = None,
    ):
        if request_id != self._play_request:
            return False
        self._stream_ready = True
        self.play_button.set_sensitive(True)
        self.expanded_play_button.set_sensitive(True)
        self.current_duration_ms = duration_ms or 0
        self.duration_label.set_label(self._format_time(self.current_duration_ms))
        self.expanded_duration_label.set_label(self._format_time(self.current_duration_ms))
        self.progress.set_sensitive(True)
        self.expanded_progress.set_sensitive(True)
        if not self._optional_start_stream(url):
            self.player.play(url)
        self._social_track_started(self._pending_seek_ms)
        self._optional_stream_started()
        if self._pending_seek_ms:
            GLib.timeout_add(700, self._apply_pending_seek, request_id, self._pending_seek_ms)
        self._history_tracking_request = request_id
        GLib.timeout_add_seconds(
            30,
            self._register_qualified_playback,
            request_id,
            self.current_item,
            playback_tracking_url,
        )
        self._save_playback_state()
        self.mpris.update(self.current_item, (duration_ms or 0) * 1000)
        return False

    def _register_qualified_playback(
        self,
        request_id: int,
        item: LibraryItem,
        tracking_url: str | None,
    ) -> bool:
        if (
            request_id != self._play_request
            or request_id != self._history_tracking_request
            or self._playback_position_us() < 28_000_000
            or not self.storage.history_enabled()
        ):
            return False
        if self._history_recorded_request == request_id:
            return False
        self.storage.record_history(item, self._playback_position_us() // 1000)
        self._history_recorded_request = request_id
        if tracking_url:
            threading.Thread(
                target=lambda: self._register_remote_playback(tracking_url, item.playlist_id),
                daemon=True,
                name="playback-history",
            ).start()
        return False

    def _register_remote_playback(self, tracking_url: str, playlist_id: str | None) -> None:
        try:
            self.youtube.register_playback(tracking_url, playlist_id)
        except Exception:
            LOGGER.debug(
                "Não foi possível registrar a reprodução remota; o histórico local foi mantido",
                exc_info=True,
            )

    def _apply_pending_seek(self, request_id: int, position_ms: int) -> bool:
        if request_id == self._play_request and self.current_duration_ms > position_ms:
            self._seek_playback(position_ms * 1000)
        self._pending_seek_ms = 0
        return False

    def _play_request_error(self, request_id: int, error: str):
        if request_id == self._play_request:
            return self._player_error(error)
        return False

    def _toggle_player(self) -> None:
        """Pause/resume a loaded stream, or resolve the selected track again."""
        if self._optional_toggle_player():
            return
        if self._stream_ready:
            self.player.toggle()
        elif getattr(self, "current_item", None):
            self.play_item(self.current_item)

    @staticmethod
    def _format_time(milliseconds: int) -> str:
        seconds = max(0, milliseconds // 1000)
        return f"{seconds // 60}:{seconds % 60:02d}"

    def _update_progress(self):
        if self._stream_ready and self.current_duration_ms <= 0:
            discovered_duration = self.player.duration_us // 1000
            if discovered_duration > 0:
                self.current_duration_ms = discovered_duration
                duration = self._format_time(discovered_duration)
                self.duration_label.set_label(duration)
                self.expanded_duration_label.set_label(duration)
                self.progress.set_sensitive(True)
                self.expanded_progress.set_sensitive(True)
        if self.current_duration_ms > 0:
            position_ms = self._playback_position_us() // 1000
            self._updating_progress = True
            value = min(100, position_ms * 100 / self.current_duration_ms)
            self.progress.set_value(value)
            self.expanded_progress.set_value(value)
            self._updating_progress = False
            elapsed = self._format_time(position_ms)
            self.elapsed_label.set_label(elapsed)
            self.expanded_elapsed_label.set_label(elapsed)
            self._update_synced_lyrics(position_ms)
            self._maybe_scrobble_lastfm(position_ms)
            if time.monotonic() - self._last_queue_save >= 5:
                self._save_playback_state(position_ms)
        return GLib.SOURCE_CONTINUE

    def _seek_requested(self, _scale, _scroll, value):
        if not self._updating_progress and self.current_duration_ms > 0:
            position_us = int(self.current_duration_ms * 1000 * value / 100)
            if self._seek_playback(position_us):
                elapsed = self._format_time(position_us // 1000)
                self.elapsed_label.set_label(elapsed)
                self.expanded_elapsed_label.set_label(elapsed)
                self._update_synced_lyrics(position_us // 1000, allow_backward=True)
        return False

    def _player_state(self, playing: bool, remote: bool = False):
        if self._optional_ignore_local_state() and not remote:
            return False
        icon = "media-playback-pause-symbolic" if playing else "media-playback-start-symbolic"
        self.play_button.set_icon_name(icon)
        self.expanded_play_button.set_icon_name(icon)
        self._refresh_detail_track_states()
        self._refresh_home_song_rows()
        self.mpris.update()
        self._social_playback_changed(playing)
        return False

    def _pause(self):
        if self.cast_renderer and self._cast_playing:
            self._optional_toggle_player()
        elif self.player.playing:
            self.player.toggle()

    def _resume(self):
        if self.cast_renderer and not self._cast_playing:
            self._optional_toggle_player()
        elif not self.player.playing:
            self._toggle_player()

    def _player_error(self, error: str):
        self._stream_ready = False
        item = getattr(self, "current_item", None)
        if item is not None and self._stream_recovery_attempts < 1:
            self._stream_recovery_attempts += 1
            request_id = self._play_request
            self.play_button.set_sensitive(False)
            self.expanded_play_button.set_sensitive(False)
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=_("O stream falhou; renovando a conexão…"),
                    timeout=3,
                )
            )

            def recover() -> None:
                try:
                    stream = self.youtube.resolve_stream(item.id, force=True)
                    GLib.idle_add(
                        self._start_stream,
                        request_id,
                        stream.url,
                        stream.duration_ms,
                        stream.playback_tracking_url,
                    )
                except Exception as exc:
                    GLib.idle_add(self._player_recovery_failed, request_id, str(exc))

            threading.Thread(target=recover, daemon=True, name="stream-recovery").start()
            return False
        self.play_button.set_sensitive(True)
        self.play_button.set_icon_name("media-playback-start-symbolic")
        self.expanded_play_button.set_sensitive(True)
        self.expanded_play_button.set_icon_name("media-playback-start-symbolic")
        self.toast_overlay.add_toast(
            Adw.Toast(title=_("Falha na reprodução: {error}").format(error=error), timeout=6)
        )
        return False

    def _player_recovery_failed(self, request_id: int, error: str) -> bool:
        if request_id != self._play_request:
            return False
        self.play_button.set_sensitive(True)
        self.play_button.set_icon_name("media-playback-start-symbolic")
        self.expanded_play_button.set_sensitive(True)
        self.expanded_play_button.set_icon_name("media-playback-start-symbolic")
        self.toast_overlay.add_toast(
            Adw.Toast(
                title=_("Falha na reprodução após renovar o stream: {error}").format(error=error),
                timeout=6,
            )
        )
        return False

    def _stop_player(self) -> None:
        self._optional_stop()
        self._play_request += 1
        self._lyrics_request += 1
        self._autoplay_request += 1
        self._autoplay_loading = False
        self._waiting_for_autoplay = False
        self._stream_ready = False
        self.player.stop()
        self.lyrics_popover.popdown()
        self._hide_expanded_player()
        self.current_item = None
        self.queue = []
        self.related_items = []
        self.queue_index = -1
        self.storage.clear_playback_state()
        self.current_duration_ms = 0
        self.expanded_progress.set_value(0)
        self.expanded_progress.set_sensitive(False)
        self.expanded_elapsed_label.set_label(_("0:00"))
        self.expanded_duration_label.set_label(_("0:00"))
        self._set_footer_item_state(False)
        self._render_queue()
        self._refresh_detail_track_states()
        self._refresh_home_song_rows()
        self.mpris.clear()
        self._clear_social_presence()
