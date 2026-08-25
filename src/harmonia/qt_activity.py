from __future__ import annotations

import logging
from bisect import bisect_right
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal

from .lyrics import LyricsResolver
from .models import HistoryEntry, LibraryItem
from .services import YouTubeMusicService
from .storage import Storage

LOGGER = logging.getLogger(__name__)


class QtHistoryController(QObject):
    historyChanged = Signal()
    insightsChanged = Signal()

    _historyReady = Signal(int, object, str)
    _removeReady = Signal(bool, str)

    def __init__(
        self,
        storage: Storage,
        youtube: YouTubeMusicService,
        executor: ThreadPoolExecutor,
        logged_in: Callable[[], bool],
        set_status: Callable[[str], None],
        play_queue: Callable[[list[LibraryItem], int], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.storage = storage
        self.youtube = youtube
        self.executor = executor
        self.logged_in = logged_in
        self.set_status = set_status
        self.play_queue = play_queue

        self.entries: list[HistoryEntry] = self.storage.load_history()
        self.loading = False
        self.request = 0
        self.insights_data = self.storage.playback_insights()

        self._historyReady.connect(self._apply_history)
        self._removeReady.connect(self._apply_remote_removal)

    @property
    def enabled(self) -> bool:
        return self.storage.history_enabled()

    @property
    def has_local(self) -> bool:
        return any(entry.source == "local" for entry in self.entries)

    def on_history_recorded(self, entry: HistoryEntry) -> None:
        self.entries.insert(0, entry)
        self.historyChanged.emit()
        self.refresh_insights()

    def refresh(self) -> None:
        self.request += 1
        request_id = self.request
        local = self.storage.load_history()
        if not self.logged_in():
            self.entries = local
            self.loading = False
            self.historyChanged.emit()
            return
        self.loading = True
        self.historyChanged.emit()

        def worker() -> None:
            try:
                remote = self.youtube.history()
                self._historyReady.emit(request_id, remote, "")
            except Exception as exc:
                LOGGER.exception("Qt history sync failed")
                self._historyReady.emit(request_id, [], str(exc))

        self.executor.submit(worker)

    def _apply_history(self, request_id: int, remote, error: str) -> None:
        if request_id != self.request:
            return
        self.loading = False
        local = self.storage.load_history()
        self.entries = [*list(remote or []), *local]
        self.historyChanged.emit()
        if error:
            self.set_status(f"O histórico local foi preservado; o remoto falhou: {error}")

    def set_enabled(self, enabled: bool) -> None:
        self.storage.set_history_enabled(enabled)
        self.historyChanged.emit()

    def clear_local(self) -> None:
        self.storage.clear_history()
        self.entries = [entry for entry in self.entries if entry.source != "local"]
        self.historyChanged.emit()
        self.refresh_insights()

    def remove_item(self, index: int) -> None:
        if not 0 <= index < len(self.entries):
            return
        entry = self.entries[index]
        if entry.source == "local" and entry.id is not None:
            self.storage.remove_history(entry.id)
            self.entries.pop(index)
            self.historyChanged.emit()
            self.refresh_insights()
            return
        if not entry.feedback_token:
            return

        def worker() -> None:
            try:
                self.youtube.remove_history_item(entry.feedback_token or "")
                self._removeReady.emit(True, "")
            except Exception as exc:
                LOGGER.exception("Qt remote history removal failed")
                self._removeReady.emit(False, str(exc))

        self.executor.submit(worker)

    def _apply_remote_removal(self, ok: bool, error: str) -> None:
        if not ok:
            self.set_status(f"Não foi possível remover do histórico: {error}")
            return
        self.set_status("")
        self.refresh()

    def play_item(self, index: int) -> None:
        if 0 <= index < len(self.entries):
            self.play_queue([self.entries[index].item], 0)

    def refresh_insights(self) -> None:
        self.insights_data = self.storage.playback_insights()
        self.insightsChanged.emit()

    def play_insight_track(self, index: int) -> None:
        if 0 <= index < len(self.insights_data.top_tracks):
            self.play_queue([self.insights_data.top_tracks[index].item], 0)


class QtLyricsController(QObject):
    lyricsChanged = Signal()
    lyricPositionChanged = Signal()

    _lyricsReady = Signal(int, object, str)

    def __init__(
        self,
        storage: Storage,
        youtube: YouTubeMusicService,
        executor: ThreadPoolExecutor,
        current_item: Callable[[], LibraryItem | None],
        duration: Callable[[], int],
        position: Callable[[], int],
        set_status: Callable[[str], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.storage = storage
        self.resolver = LyricsResolver(youtube.lyrics)
        self.executor = executor
        self.current_item = current_item
        self.duration = duration
        self.position = position
        self.set_status = set_status

        self.document = None
        self.loading = False
        self.request = 0
        self.active_index = -1
        self._lyricsReady.connect(self._apply_lyrics)

    def reset(self) -> None:
        self.request += 1
        self.document = None
        self.loading = False
        self.active_index = -1
        self.lyricsChanged.emit()
        self.lyricPositionChanged.emit()

    def load(self, *, force: bool = False) -> None:
        item = self.current_item()
        if item is None:
            self.reset()
            return
        provider = self.storage.get_setting("lyrics_provider", "auto")
        if provider not in {"auto", "lrclib", "youtube"}:
            provider = "auto"
        if not force:
            cached = self.storage.load_lyrics_document(item.id, provider)
            if cached:
                self.document = cached
                self.loading = False
                self.lyricsChanged.emit()
                self.update_position(self.position())
                return

        self.request += 1
        request_id = self.request
        self.loading = True
        self.document = None
        self.active_index = -1
        self.lyricsChanged.emit()
        self.lyricPositionChanged.emit()

        def worker() -> None:
            try:
                document = self.resolver.fetch(item, self.duration(), provider)
                self._lyricsReady.emit(request_id, document, "")
            except Exception as exc:
                LOGGER.exception("Qt lyrics fetch failed")
                self._lyricsReady.emit(request_id, None, str(exc))

        self.executor.submit(worker)

    def _apply_lyrics(self, request_id: int, document, error: str) -> None:
        if request_id != self.request:
            return
        self.loading = False
        self.document = document
        item = self.current_item()
        if document and item:
            self.storage.save_lyrics_document(item.id, document)
        self.lyricsChanged.emit()
        self.update_position(self.position())
        if error:
            self.set_status(f"Não foi possível carregar a letra: {error}")

    def update_position(self, position_ms: int) -> None:
        lines = self.document.synced if self.document else []
        index = bisect_right([line.start_ms for line in lines], position_ms) - 1 if lines else -1
        if index == self.active_index:
            return
        self.active_index = index
        self.lyricPositionChanged.emit()
