from __future__ import annotations

import logging
from bisect import bisect_right
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication

from .lyrics import GoogleTranslationClient, LyricsResolver
from .models import HistoryEntry, LibraryItem, LyricLine
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
    _translationReady = Signal(int, str, object, str)

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
        self.translation_client = GoogleTranslationClient()
        self.executor = executor
        self.current_item = current_item
        self.duration = duration
        self.position = position
        self.set_status = set_status

        self.document = None
        self.loading = False
        self.request = 0
        self.active_index = -1
        self.provider = self.storage.get_setting("lyrics_provider", "auto")
        if self.provider not in {"auto", "lrclib", "youtube"}:
            self.provider = "auto"
        try:
            self.offset_ms = int(self.storage.get_setting("lyrics_offset_ms", "0"))
        except ValueError:
            self.offset_ms = 0

        self._lyricsReady.connect(self._apply_lyrics)
        self._translationReady.connect(self._apply_translation)

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
        if not force:
            cached = self.storage.load_lyrics_document(item.id, self.provider)
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
                document = self.resolver.fetch(item, self.duration(), self.provider)
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

    def set_provider(self, provider: str) -> None:
        if provider not in {"auto", "lrclib", "youtube"} or provider == self.provider:
            return
        self.provider = provider
        self.storage.set_setting("lyrics_provider", provider)
        self.lyricsChanged.emit()
        self.load(force=False)

    def cycle_provider(self) -> None:
        providers = ("auto", "lrclib", "youtube")
        self.set_provider(providers[(providers.index(self.provider) + 1) % len(providers)])

    def set_offset(self, value: int) -> None:
        value = max(-5000, min(5000, int(value)))
        if value == self.offset_ms:
            return
        self.offset_ms = value
        self.storage.set_setting("lyrics_offset_ms", str(value))
        self.lyricsChanged.emit()
        self.update_position(self.position(), force=True)

    def change_offset(self, delta: int) -> None:
        self.set_offset(self.offset_ms + delta)

    def seek_target(self, start_ms: int) -> int:
        return max(0, int(start_ms) - self.offset_ms)

    def copy(self) -> None:
        document = self.document
        if not document:
            return
        value = document.display_text
        if document.translation:
            value += "\n\n" + document.translation
        if document.synced and any(line.translation for line in document.synced):
            value = "\n".join(
                f"{line.text}\n{line.translation}" if line.translation else line.text
                for line in document.synced
            )
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(value)
            self.set_status("Letra copiada.")

    def translate(self) -> None:
        item = self.current_item()
        document = self.document
        if not item or not document:
            return
        if document.translation_language == "pt" and (
            document.translation or any(line.translation for line in document.synced)
        ):
            document.translation = ""
            document.translation_language = ""
            document.synced = [LyricLine(line.start_ms, line.text) for line in document.synced]
            self.storage.save_lyrics_document(item.id, document)
            self.lyricsChanged.emit()
            return

        self.set_status("Traduzindo letra…")
        request_id = self.request
        lines = [line.text for line in document.synced] or document.display_text.splitlines()

        def worker() -> None:
            try:
                result = self.translation_client.translate(lines, "pt")
                self._translationReady.emit(request_id, item.id, result, "")
            except Exception as exc:
                LOGGER.exception("Qt lyrics translation failed")
                self._translationReady.emit(request_id, item.id, [], str(exc))

        self.executor.submit(worker)

    def _apply_translation(
        self,
        request_id: int,
        video_id: str,
        result,
        error: str,
    ) -> None:
        item = self.current_item()
        document = self.document
        if (
            request_id != self.request
            or not item
            or item.id != video_id
            or document is None
        ):
            return
        if error or not result or not any(result):
            self.set_status(f"Falha ao traduzir: {error or 'resposta vazia'}")
            return
        if document.synced:
            document.synced = [
                LyricLine(
                    line.start_ms,
                    line.text,
                    result[index] if index < len(result) else "",
                )
                for index, line in enumerate(document.synced)
            ]
        else:
            document.translation = "\n".join(result)
        document.translation_language = "pt"
        self.storage.save_lyrics_document(item.id, document)
        self.lyricsChanged.emit()
        self.set_status("Letra traduzida.")

    def update_position(self, position_ms: int, *, force: bool = False) -> None:
        lines = self.document.synced if self.document else []
        adjusted = max(0, int(position_ms) + self.offset_ms)
        index = bisect_right([line.start_ms for line in lines], adjusted) - 1 if lines else -1
        if index == self.active_index and not force:
            return
        self.active_index = index
        self.lyricPositionChanged.emit()
