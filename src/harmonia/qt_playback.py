from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer, Signal

from .downloads import DownloadManager
from .models import HistoryEntry, LibraryItem
from .playback_state import (
    filter_new_recommendations,
    move_queue_item,
    playback_state_snapshot,
    radio_seed_for_autoplay,
    remove_queue_item,
    shuffled_queue_keep_current,
)
from .player import NativePlayer
from .services import YouTubeMusicService
from .storage import Storage

LOGGER = logging.getLogger(__name__)


class QtPlaybackController(QObject):
    """Qt-facing playback state backed by the same NativePlayer used by GTK."""

    nowPlayingChanged = Signal()
    playbackChanged = Signal()
    positionChanged = Signal()
    durationChanged = Signal()
    volumeChanged = Signal()
    queueChanged = Signal()
    autoplayLoadingChanged = Signal()
    trackChanged = Signal()
    trackStarted = Signal(object, int)
    historyRecorded = Signal(object)

    _streamReady = Signal(int, object, str)
    _radioReady = Signal(int, object, str)

    def __init__(
        self,
        storage: Storage,
        youtube: YouTubeMusicService,
        downloads: DownloadManager,
        executor: ThreadPoolExecutor,
        set_busy: Callable[[bool], None],
        set_status: Callable[[str], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.storage = storage
        self.youtube = youtube
        self.downloads = downloads
        self.executor = executor
        self.set_busy = set_busy
        self.set_status = set_status

        self.queue: list[LibraryItem] = []
        self.related_items: list[LibraryItem] = []
        self.queue_index = -1
        self.current_item: LibraryItem | None = None
        self.shuffle = False
        self.repeat = False
        self.autoplay = True
        self.autoplay_loading = False
        self.waiting_for_autoplay = False

        self._stream_request = 0
        self._radio_request = 0
        self._duration_ms = 0
        self._restored_position_ms = 0
        self._stream_ready = False
        self._stream_recovery_attempts = 0
        self._last_state_save = time.monotonic()
        self._play_generation = 0
        self._history_recorded_generation = -1
        self._pending_tracking_url = ""
        self._last_position = -1
        self._last_duration = -1
        self._last_volume = -1

        restored = self.storage.load_playback_state()
        if restored and restored.queue:
            self.queue = list(restored.queue)
            self.related_items = list(restored.related)
            self.queue_index = max(0, min(restored.index, len(self.queue) - 1))
            self.current_item = self.queue[self.queue_index]
            self.shuffle = restored.shuffle
            self.repeat = restored.repeat
            self.autoplay = restored.autoplay
            self._restored_position_ms = restored.position_ms
            self._play_generation = 1

        self.player = NativePlayer(self._on_player_state, self._player_error, self.next)
        self.player.volume = 0.85

        self._streamReady.connect(self._apply_stream)
        self._radioReady.connect(self._apply_radio)

        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(250)
        self._progress_timer.timeout.connect(self._tick)
        self._progress_timer.start()

    @property
    def playing(self) -> bool:
        return self.player.playing

    @property
    def position(self) -> int:
        if not self._stream_ready:
            return max(0, self._restored_position_ms)
        return max(0, self.player.position_us // 1000)

    @property
    def duration(self) -> int:
        queried = self.player.duration_us // 1000 if self._stream_ready else 0
        return max(0, self._duration_ms or queried)

    @property
    def volume(self) -> int:
        return round(self.player.volume * 100)

    @property
    def can_previous(self) -> bool:
        return self.queue_index > 0

    @property
    def can_next(self) -> bool:
        return self.queue_index >= 0 and (
            self.queue_index + 1 < len(self.queue)
            or (self.repeat and bool(self.queue))
            or self.autoplay
        )

    def apply_audio_settings(
        self,
        *,
        normalization: bool,
        equalizer: str,
        speed: float,
        pitch: float,
        skip_silence: bool,
    ) -> None:
        self.player.apply_audio_settings(
            normalization=normalization,
            equalizer=equalizer,
            speed=speed,
            pitch=pitch,
            skip_silence=skip_silence,
        )

    def _tick(self) -> None:
        position = self.position
        duration = self.duration
        volume = self.volume
        if position != self._last_position:
            self._last_position = position
            self.positionChanged.emit()
        if duration != self._last_duration:
            self._last_duration = duration
            self.durationChanged.emit()
        if volume != self._last_volume:
            self._last_volume = volume
            self.volumeChanged.emit()
        self._maybe_record_history(position)
        if self.queue and time.monotonic() - self._last_state_save >= 5:
            self._save_state(position)

    def _set_autoplay_loading(self, value: bool) -> None:
        if self.autoplay_loading == value:
            return
        self.autoplay_loading = value
        self.autoplayLoadingChanged.emit()

    def _save_state(self, position_ms: int | None = None) -> None:
        if not self.queue:
            return
        position = self.position if position_ms is None else position_ms
        self.storage.save_playback_state(
            playback_state_snapshot(
                self.queue,
                self.related_items,
                self.queue_index,
                position,
                shuffle=self.shuffle,
                repeat=self.repeat,
                autoplay=self.autoplay,
            )
        )
        self._last_state_save = time.monotonic()

    def _maybe_record_history(self, position_ms: int) -> None:
        if (
            self.current_item is None
            or position_ms < 30_000
            or self._history_recorded_generation == self._play_generation
            or not self.storage.history_enabled()
        ):
            return
        entry_id = self.storage.record_history(self.current_item, position_ms)
        self._history_recorded_generation = self._play_generation
        if entry_id is not None:
            self.historyRecorded.emit(
                HistoryEntry(
                    entry_id,
                    self.current_item,
                    int(time.time()),
                    position_ms,
                    "local",
                )
            )
        if self._pending_tracking_url:
            tracking_url = self._pending_tracking_url
            playlist_id = self.current_item.playlist_id
            self._pending_tracking_url = ""
            self.executor.submit(self.youtube.register_playback, tracking_url, playlist_id)

    def set_current(self, index: int, *, resolve: bool = True) -> None:
        if not 0 <= index < len(self.queue):
            return
        self.queue_index = index
        self.current_item = self.queue[index]
        self._play_generation += 1
        self._history_recorded_generation = -1
        self._pending_tracking_url = ""
        self._restored_position_ms = 0
        self._duration_ms = 0
        self._stream_ready = False
        self._stream_recovery_attempts = 0
        self.nowPlayingChanged.emit()
        self.queueChanged.emit()
        self.trackChanged.emit()
        self._save_state(0)
        if resolve:
            self.resolve_current()

    def play_queue(self, items: list[LibraryItem], index: int) -> None:
        if not items or not 0 <= index < len(items):
            return
        selected = items[index]
        if selected.kind not in {"songs", "videos"}:
            return
        self.related_items = []
        self.waiting_for_autoplay = False
        self._radio_request += 1
        self._set_autoplay_loading(False)
        self.queue = list(items)
        self.set_current(index)
        self.ensure_autoplay()

    def resolve_current(self) -> None:
        item = self.current_item
        if item is None:
            return
        self._stream_request += 1
        request_id = self._stream_request
        self._pending_tracking_url = ""
        self._stream_ready = False

        if item.id.startswith("local:"):
            local_path = self.storage.local_media_path(item.id)
            if not local_path or not local_path.is_file():
                self.set_status("O arquivo local não está mais disponível.")
                return
            self._start_uri(request_id, local_path.as_uri(), None, None)
            return

        offline = self.downloads.offline_path(item.id)
        if offline:
            self._start_uri(request_id, offline.as_uri(), None, None)
            return

        self.set_busy(True)
        self.set_status(f"Preparando {item.title}…")

        def worker() -> None:
            try:
                stream = self.youtube.resolve_stream(item.id)
                self._streamReady.emit(request_id, stream, "")
            except Exception as exc:
                LOGGER.exception("Qt stream resolve failed")
                self._streamReady.emit(request_id, None, str(exc))

        self.executor.submit(worker)

    def _start_uri(
        self,
        request_id: int,
        uri: str,
        duration_ms: int | None,
        tracking_url: str | None,
    ) -> None:
        if request_id != self._stream_request:
            return
        self.set_busy(False)
        self._duration_ms = max(0, int(duration_ms or 0))
        self._pending_tracking_url = tracking_url or ""
        self._stream_ready = True
        self.player.play(uri)
        self.playbackChanged.emit()
        self.durationChanged.emit()
        self.positionChanged.emit()
        self.trackStarted.emit(self.current_item, self._duration_ms)
        self.set_status("")
        restored = self._restored_position_ms
        self._restored_position_ms = 0
        if restored:
            QTimer.singleShot(700, lambda: self.seek(restored))
        self._save_state(restored)
        self.ensure_autoplay()

    def _apply_stream(self, request_id: int, stream, error: str) -> None:
        if request_id != self._stream_request:
            return
        if error or stream is None:
            self.set_busy(False)
            self.set_status(f"Não foi possível reproduzir a faixa: {error}")
            return
        self._start_uri(
            request_id,
            stream.url,
            stream.duration_ms,
            stream.playback_tracking_url,
        )

    def toggle_playback(self) -> None:
        if self.current_item is None:
            return
        if not self._stream_ready:
            self.resolve_current()
        else:
            self.player.toggle()

    def stop(self) -> None:
        self._stream_request += 1
        self._radio_request += 1
        self.player.stop()
        self._stream_ready = False
        self._duration_ms = 0
        self._restored_position_ms = 0
        self.current_item = None
        self.queue = []
        self.related_items = []
        self.queue_index = -1
        self.waiting_for_autoplay = False
        self._set_autoplay_loading(False)
        self.storage.clear_playback_state()
        self.nowPlayingChanged.emit()
        self.queueChanged.emit()
        self.trackChanged.emit()
        self.playbackChanged.emit()
        self.positionChanged.emit()
        self.durationChanged.emit()

    def next(self) -> bool:
        if not self.queue:
            return False
        if self.queue_index + 1 < len(self.queue):
            self.set_current(self.queue_index + 1)
            self.ensure_autoplay()
            return False
        if self.repeat:
            self.set_current(0)
            self.ensure_autoplay()
            return False
        if self.autoplay:
            if self.related_items:
                self._promote_related_index(0, False)
                self.set_current(self.queue_index + 1)
            else:
                self.waiting_for_autoplay = True
                self.ensure_autoplay(force=True)
        return False

    def previous(self) -> None:
        if self.position > 3000:
            self.seek(0)
            return
        if self.queue_index > 0:
            self.set_current(self.queue_index - 1)
        elif self.repeat and self.queue:
            self.set_current(len(self.queue) - 1)

    def set_shuffle(self, enabled: bool) -> None:
        if enabled == self.shuffle:
            return
        self.shuffle = enabled
        if enabled and self.queue:
            self.queue, self.queue_index = shuffled_queue_keep_current(self.queue, self.queue_index)
            self.queueChanged.emit()
            self.nowPlayingChanged.emit()
        self.playbackChanged.emit()
        self._save_state()

    def toggle_shuffle(self) -> None:
        self.set_shuffle(not self.shuffle)

    def set_repeat(self, enabled: bool) -> None:
        if enabled == self.repeat:
            return
        self.repeat = enabled
        self.playbackChanged.emit()
        self.nowPlayingChanged.emit()
        self._save_state()

    def toggle_repeat(self) -> None:
        self.set_repeat(not self.repeat)

    def toggle_autoplay(self) -> None:
        self.autoplay = not self.autoplay
        self.waiting_for_autoplay = False
        if not self.autoplay:
            self._radio_request += 1
            self._set_autoplay_loading(False)
        self.playbackChanged.emit()
        self.nowPlayingChanged.emit()
        self._save_state()
        if self.autoplay:
            self.ensure_autoplay(force=True)

    def ensure_autoplay(self, force: bool = False) -> None:
        if not self.autoplay or not self.queue or self.autoplay_loading:
            return
        if self.related_items:
            if self.waiting_for_autoplay:
                self.waiting_for_autoplay = False
                self._promote_related_index(0, False)
                self.set_current(self.queue_index + 1)
            return
        seed = radio_seed_for_autoplay(self.queue, self.queue_index, force=force)
        if seed is None:
            return
        self._radio_request += 1
        request_id = self._radio_request
        self._set_autoplay_loading(True)

        def worker() -> None:
            try:
                recommendations = self.youtube.radio(seed.id)
                self._radioReady.emit(request_id, recommendations, "")
            except Exception as exc:
                LOGGER.exception("Qt autoplay radio failed")
                self._radioReady.emit(request_id, [], str(exc))

        self.executor.submit(worker)

    def _apply_radio(self, request_id: int, recommendations, error: str) -> None:
        if request_id != self._radio_request:
            return
        self._set_autoplay_loading(False)
        if error:
            if self.waiting_for_autoplay:
                self.waiting_for_autoplay = False
                self.set_status(f"Não foi possível continuar a rádio: {error}")
            return
        self.related_items = filter_new_recommendations(self.queue, recommendations)
        self.queueChanged.emit()
        self._save_state()
        if self.waiting_for_autoplay and self.related_items:
            self.waiting_for_autoplay = False
            self._promote_related_index(0, False)
            self.set_current(self.queue_index + 1)
        elif self.waiting_for_autoplay:
            self.waiting_for_autoplay = False
            self.set_status("A rádio não encontrou novas músicas.")

    def _promote_related_index(self, index: int, play_next: bool) -> None:
        if not 0 <= index < len(self.related_items):
            return
        item = self.related_items.pop(index)
        position = min(len(self.queue), self.queue_index + 1) if play_next else len(self.queue)
        self.queue.insert(position, item)
        self.queueChanged.emit()
        self.nowPlayingChanged.emit()
        self._save_state()

    def promote_related(self, index: int, play_next: bool) -> None:
        self._promote_related_index(index, play_next)

    def select_queue_item(self, index: int) -> None:
        if 0 <= index < len(self.queue):
            self.set_current(index)
            self.ensure_autoplay()

    def move_queue_item(self, index: int, direction: int) -> None:
        self.queue_index, changed = move_queue_item(
            self.queue,
            self.queue_index,
            index,
            direction,
        )
        if not changed:
            return
        self.queueChanged.emit()
        self.nowPlayingChanged.emit()
        self._save_state()

    def remove_queue_item(self, index: int) -> None:
        result = remove_queue_item(self.queue, self.queue_index, index)
        if result is None:
            return
        self.queue_index = result.index
        if result.empty:
            self.stop()
            return
        if result.removed_current:
            self.set_current(self.queue_index)
        else:
            self.queueChanged.emit()
            self.nowPlayingChanged.emit()
            self._save_state()

    def seek(self, position_ms: int) -> None:
        target = max(0, min(position_ms, self.duration or position_ms))
        if self._stream_ready and self.player.seek(target * 1000):
            self._restored_position_ms = 0
            self.positionChanged.emit()
            self._save_state(target)
        elif not self._stream_ready:
            self._restored_position_ms = target
            self.positionChanged.emit()
            self._save_state(target)

    def set_volume(self, value: int) -> None:
        self.player.volume = max(0.0, min(1.0, value / 100.0))
        self.volumeChanged.emit()

    def find_item(self, item_id: str) -> LibraryItem | None:
        for group in (self.queue, self.related_items):
            for item in group:
                if item.id == item_id:
                    return item
        if self.current_item and self.current_item.id == item_id:
            return self.current_item
        return None

    def _on_player_state(self, _playing: bool) -> bool:
        self.playbackChanged.emit()
        return False

    def _player_error(self, error_string: str) -> bool:
        self._stream_ready = False
        item = self.current_item
        if (
            item is not None
            and not item.id.startswith("local:")
            and self._stream_recovery_attempts < 1
        ):
            self._stream_recovery_attempts += 1
            request_id = self._stream_request
            self.set_status("O stream falhou; renovando a conexão…")

            def recover() -> None:
                try:
                    stream = self.youtube.resolve_stream(item.id, force=True)
                    self._streamReady.emit(request_id, stream, "")
                except Exception as exc:
                    LOGGER.exception("Qt stream recovery failed")
                    self._streamReady.emit(request_id, None, str(exc))

            self.executor.submit(recover)
            return False
        if error_string:
            self.set_status(f"Erro de reprodução: {error_string}")
        self.playbackChanged.emit()
        return False

    def shutdown(self) -> None:
        self._progress_timer.stop()
        if self.queue:
            self._save_state()
        self.player.close()
