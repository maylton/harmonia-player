from __future__ import annotations

import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from .downloads import DownloadManager
from .models import HistoryEntry, LibraryItem, PlaybackState
from .services import YouTubeMusicService
from .storage import Storage

LOGGER = logging.getLogger(__name__)


class QtPlaybackController(QObject):
    nowPlayingChanged = Signal()
    playbackChanged = Signal()
    positionChanged = Signal()
    durationChanged = Signal()
    volumeChanged = Signal()
    queueChanged = Signal()
    autoplayLoadingChanged = Signal()
    trackChanged = Signal()
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
        self._last_state_save = time.monotonic()
        self._play_generation = 0
        self._history_recorded_generation = -1
        self._pending_tracking_url = ""

        restored = self.storage.load_playback_state()
        if restored and restored.queue:
            self.queue = list(restored.queue)
            self.related_items = list(restored.related)
            self.queue_index = max(0, min(restored.index, len(self.queue) - 1))
            self.current_item = self.queue[self.queue_index]
            self.shuffle = restored.shuffle
            self.repeat = restored.repeat
            self.autoplay = restored.autoplay
            self._play_generation = 1

        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.85)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(lambda *_: self.durationChanged.emit())
        self.player.playbackStateChanged.connect(lambda *_: self.playbackChanged.emit())
        self.player.mediaStatusChanged.connect(self._media_status_changed)
        self.player.errorOccurred.connect(self._player_error)
        self.audio.volumeChanged.connect(lambda *_: self.volumeChanged.emit())

        self._streamReady.connect(self._apply_stream)
        self._radioReady.connect(self._apply_radio)

    @property
    def playing(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    @property
    def position(self) -> int:
        return int(self.player.position())

    @property
    def duration(self) -> int:
        return int(self.player.duration())

    @property
    def volume(self) -> int:
        return round(self.audio.volume() * 100)

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

    def _set_autoplay_loading(self, value: bool) -> None:
        if self.autoplay_loading == value:
            return
        self.autoplay_loading = value
        self.autoplayLoadingChanged.emit()

    def _save_state(self, position_ms: int | None = None) -> None:
        if not self.queue:
            return
        self.storage.save_playback_state(
            PlaybackState(
                list(self.queue),
                list(self.related_items),
                max(0, self.queue_index),
                self.position if position_ms is None else max(0, position_ms),
                self.shuffle,
                self.repeat,
                self.autoplay,
            )
        )
        self._last_state_save = time.monotonic()

    def _on_position_changed(self, value: int) -> None:
        self.positionChanged.emit()
        self._maybe_record_history(value)
        if self.queue and time.monotonic() - self._last_state_save >= 5:
            self._save_state(value)

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
        offline = self.downloads.offline_path(item.id)
        if offline:
            self.player.setSource(QUrl.fromLocalFile(str(offline)))
            self.player.play()
            self.set_status("")
            self.ensure_autoplay()
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

    def _apply_stream(self, request_id: int, stream, error: str) -> None:
        if request_id != self._stream_request:
            return
        self.set_busy(False)
        if error or stream is None:
            self.set_status(f"Não foi possível reproduzir a faixa: {error}")
            return
        self._pending_tracking_url = stream.playback_tracking_url or ""
        self.player.setSource(QUrl(stream.url))
        self.player.play()
        self.set_status("")
        self.ensure_autoplay()

    def toggle_playback(self) -> None:
        if self.current_item is None:
            return
        if self.player.source().isEmpty():
            self.resolve_current()
        elif self.playing:
            self.player.pause()
        else:
            self.player.play()

    def next(self) -> None:
        if not self.queue:
            return
        if self.shuffle and len(self.queue) > 1:
            choices = [index for index in range(len(self.queue)) if index != self.queue_index]
            self.set_current(random.choice(choices))
            self.ensure_autoplay()
            return
        if self.queue_index + 1 < len(self.queue):
            self.set_current(self.queue_index + 1)
            self.ensure_autoplay()
            return
        if self.repeat:
            self.set_current(0)
            self.ensure_autoplay()
            return
        if not self.autoplay:
            return
        if self.related_items:
            self._promote_related_index(0, True)
            self.set_current(self.queue_index + 1)
        else:
            self.waiting_for_autoplay = True
            self.ensure_autoplay(force=True)

    def previous(self) -> None:
        if self.position > 5000:
            self.player.setPosition(0)
            return
        if self.queue_index > 0:
            self.set_current(self.queue_index - 1)
        elif self.repeat and self.queue:
            self.set_current(len(self.queue) - 1)

    def toggle_shuffle(self) -> None:
        self.shuffle = not self.shuffle
        self.playbackChanged.emit()
        self._save_state()

    def toggle_repeat(self) -> None:
        self.repeat = not self.repeat
        self.playbackChanged.emit()
        self.nowPlayingChanged.emit()
        self._save_state()

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
                self._promote_related_index(0, True)
                self.set_current(self.queue_index + 1)
            return
        remaining = len(self.queue) - self.queue_index - 1
        if not force and remaining > 5:
            return
        seed = self.queue[-1]
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
        existing = {item.id for item in self.queue}
        self.related_items = [item for item in list(recommendations or []) if item.id not in existing]
        self.queueChanged.emit()
        self._save_state()
        if self.waiting_for_autoplay and self.related_items:
            self.waiting_for_autoplay = False
            self._promote_related_index(0, True)
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
        target = index + direction
        if not (0 <= index < len(self.queue) and 0 <= target < len(self.queue)):
            return
        self.queue[index], self.queue[target] = self.queue[target], self.queue[index]
        if self.queue_index == index:
            self.queue_index = target
        elif self.queue_index == target:
            self.queue_index = index
        self.queueChanged.emit()
        self.nowPlayingChanged.emit()
        self._save_state()

    def remove_queue_item(self, index: int) -> None:
        if not 0 <= index < len(self.queue):
            return
        removing_current = index == self.queue_index
        self.queue.pop(index)
        if not self.queue:
            self.player.stop()
            self.player.setSource(QUrl())
            self.current_item = None
            self.queue_index = -1
            self.related_items = []
            self.storage.clear_playback_state()
            self.nowPlayingChanged.emit()
            self.queueChanged.emit()
            self.trackChanged.emit()
            return
        if index < self.queue_index:
            self.queue_index -= 1
        elif self.queue_index >= len(self.queue):
            self.queue_index = len(self.queue) - 1
        if removing_current:
            self.set_current(self.queue_index)
        else:
            self.queueChanged.emit()
            self.nowPlayingChanged.emit()
            self._save_state()

    def seek(self, position_ms: int) -> None:
        self.player.setPosition(max(0, min(position_ms, self.duration)))
        self._save_state(position_ms)

    def set_volume(self, value: int) -> None:
        self.audio.setVolume(max(0.0, min(1.0, value / 100.0)))

    def find_item(self, item_id: str) -> LibraryItem | None:
        for group in (self.queue, self.related_items):
            for item in group:
                if item.id == item_id:
                    return item
        if self.current_item and self.current_item.id == item_id:
            return self.current_item
        return None

    def _media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.next()

    def _player_error(self, _error, error_string: str) -> None:
        if error_string:
            self.set_status(f"Erro de reprodução: {error_string}")

    def shutdown(self) -> None:
        if self.queue:
            self._save_state()
        self.player.stop()
