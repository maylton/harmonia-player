from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from .models import LibraryItem
from .services import YouTubeMusicService
from .storage import Storage

LOGGER = logging.getLogger(__name__)

CATEGORY_LABELS = {
    "songs": "Músicas curtidas",
    "albums": "Álbuns",
    "artists": "Artistas",
    "playlists": "Playlists",
    "uploads": "Uploads",
    "uploaded-albums": "Álbuns enviados",
    "podcasts": "Podcasts",
    "podcast-episodes": "Episódios",
}


def _item_map(item: LibraryItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "subtitle": item.subtitle,
        "thumbnail": item.thumbnail or "",
        "kind": item.kind,
        "playlistId": item.playlist_id or "",
        "setVideoId": item.set_video_id or "",
    }


class HarmoniaQtBridge(QObject):
    homeChanged = Signal()
    libraryChanged = Signal()
    searchChanged = Signal()
    sessionChanged = Signal()
    busyChanged = Signal()
    statusChanged = Signal()
    nowPlayingChanged = Signal()
    playbackChanged = Signal()
    positionChanged = Signal()
    durationChanged = Signal()
    volumeChanged = Signal()

    _syncReady = Signal(object, object, str)
    _searchReady = Signal(int, object, str)
    _streamReady = Signal(int, object, str)
    _sessionReady = Signal(bool, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.storage = Storage()
        self.youtube = YouTubeMusicService(self.storage)
        self._executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="harmonia-qt")
        self._home = self.storage.load_home()
        self._library = self.storage.load_library()
        self._search_items: list[LibraryItem] = []
        self._current_library_category = next(iter(self._library), "songs")
        self._logged_in = bool(self.storage.load_cookie())
        self._busy = False
        self._status = ""
        self._queue: list[LibraryItem] = []
        self._queue_index = -1
        self._current_item: LibraryItem | None = None
        self._stream_request = 0
        self._search_request = 0

        self._audio = QAudioOutput(self)
        self._audio.setVolume(0.85)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio)
        self._player.positionChanged.connect(self.positionChanged)
        self._player.durationChanged.connect(self.durationChanged)
        self._player.playbackStateChanged.connect(lambda *_: self.playbackChanged.emit())
        self._player.mediaStatusChanged.connect(self._media_status_changed)
        self._player.errorOccurred.connect(self._player_error)
        self._audio.volumeChanged.connect(self.volumeChanged)

        self._syncReady.connect(self._apply_sync)
        self._searchReady.connect(self._apply_search)
        self._streamReady.connect(self._apply_stream)
        self._sessionReady.connect(self._apply_session)

        if self._logged_in:
            QTimer.singleShot(120, self.syncAll)

    @Property("QVariantList", notify=homeChanged)
    def homeSections(self) -> list[dict[str, Any]]:
        return [
            {"title": section.title, "items": [_item_map(item) for item in section.items]}
            for section in self._home
        ]

    @Property("QVariantList", notify=libraryChanged)
    def libraryCategories(self) -> list[dict[str, str]]:
        ordered = [key for key in CATEGORY_LABELS if key in self._library]
        ordered.extend(key for key in self._library if key not in ordered)
        return [{"key": key, "label": CATEGORY_LABELS.get(key, key.title())} for key in ordered]

    @Property("QVariantList", notify=libraryChanged)
    def libraryItems(self) -> list[dict[str, Any]]:
        return [_item_map(item) for item in self._library.get(self._current_library_category, [])]

    @Property(str, notify=libraryChanged)
    def currentLibraryCategory(self) -> str:
        return self._current_library_category

    @Property("QVariantList", notify=searchChanged)
    def searchItems(self) -> list[dict[str, Any]]:
        return [_item_map(item) for item in self._search_items]

    @Property(bool, notify=sessionChanged)
    def loggedIn(self) -> bool:
        return self._logged_in

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=statusChanged)
    def statusText(self) -> str:
        return self._status

    @Property(str, notify=nowPlayingChanged)
    def currentTitle(self) -> str:
        return self._current_item.title if self._current_item else "Nenhuma música reproduzindo"

    @Property(str, notify=nowPlayingChanged)
    def currentArtist(self) -> str:
        return self._current_item.subtitle if self._current_item else "Escolha uma faixa para começar"

    @Property(str, notify=nowPlayingChanged)
    def currentArtwork(self) -> str:
        return self._current_item.thumbnail or "" if self._current_item else ""

    @Property(bool, notify=playbackChanged)
    def playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    @Property(int, notify=positionChanged)
    def position(self) -> int:
        return int(self._player.position())

    @Property(int, notify=durationChanged)
    def duration(self) -> int:
        return int(self._player.duration())

    @Property(int, notify=volumeChanged)
    def volume(self) -> int:
        return round(self._audio.volume() * 100)

    @Property(bool, notify=nowPlayingChanged)
    def canPrevious(self) -> bool:
        return self._queue_index > 0

    @Property(bool, notify=nowPlayingChanged)
    def canNext(self) -> bool:
        return self._queue_index >= 0 and self._queue_index + 1 < len(self._queue)

    def _set_busy(self, value: bool) -> None:
        if self._busy != value:
            self._busy = value
            self.busyChanged.emit()

    def _set_status(self, value: str) -> None:
        if self._status != value:
            self._status = value
            self.statusChanged.emit()

    @Slot()
    def syncAll(self) -> None:
        if not self._logged_in:
            self._set_status("Conecte sua conta para sincronizar o Harmonia.")
            return
        self._set_busy(True)
        self._set_status("Sincronizando biblioteca…")

        def worker() -> None:
            try:
                library = self.youtube.sync_library()
                home = self.youtube.sync_home()
                self._syncReady.emit(library, home, "")
            except Exception as exc:
                LOGGER.exception("Qt sync failed")
                self._syncReady.emit(None, None, str(exc))

        self._executor.submit(worker)

    @Slot(object, object, str)
    def _apply_sync(self, library, home, error: str) -> None:
        self._set_busy(False)
        if error:
            self._set_status(f"Não foi possível sincronizar: {error}")
            return
        self._library = library or {}
        self._home = home or []
        if self._current_library_category not in self._library:
            self._current_library_category = next(iter(self._library), "songs")
        self.homeChanged.emit()
        self.libraryChanged.emit()
        self._set_status("")

    @Slot(str)
    def setLibraryCategory(self, category: str) -> None:
        if category == self._current_library_category or category not in self._library:
            return
        self._current_library_category = category
        self.libraryChanged.emit()

    @Slot(str)
    def search(self, query: str) -> None:
        query = query.strip()
        self._search_request += 1
        request_id = self._search_request
        if not query:
            self._search_items = []
            self.searchChanged.emit()
            return
        self._set_busy(True)
        self._set_status(f"Pesquisando por “{query}”…")

        def worker() -> None:
            try:
                result = self.youtube.universal_search(query)
                items: list[LibraryItem] = []
                seen: set[tuple[str, str]] = set()
                for group in result.groups:
                    for item in group.items:
                        key = (item.kind, item.id)
                        if key not in seen:
                            seen.add(key)
                            items.append(item)
                self._searchReady.emit(request_id, items, "")
            except Exception as exc:
                LOGGER.exception("Qt search failed")
                self._searchReady.emit(request_id, [], str(exc))

        self._executor.submit(worker)

    @Slot(int, object, str)
    def _apply_search(self, request_id: int, items, error: str) -> None:
        if request_id != self._search_request:
            return
        self._set_busy(False)
        if error:
            self._set_status(f"Falha na pesquisa: {error}")
            return
        self._search_items = list(items or [])
        self.searchChanged.emit()
        self._set_status("")

    @Slot(int, int)
    def playHomeItem(self, section_index: int, item_index: int) -> None:
        if 0 <= section_index < len(self._home):
            items = self._home[section_index].items
            if 0 <= item_index < len(items):
                self._play_queue(items, item_index)

    @Slot(int)
    def playLibraryItem(self, item_index: int) -> None:
        items = self._library.get(self._current_library_category, [])
        if 0 <= item_index < len(items):
            self._play_queue(items, item_index)

    @Slot(int)
    def playSearchItem(self, item_index: int) -> None:
        if 0 <= item_index < len(self._search_items):
            self._play_queue(self._search_items, item_index)

    def _play_queue(self, items: list[LibraryItem], index: int) -> None:
        selected = items[index]
        if selected.kind not in {"songs", "videos"}:
            self._set_status("Abra álbuns, artistas e playlists pelo frontend GTK enquanto esta tela é portada.")
            return
        self._queue = list(items)
        self._queue_index = index
        self._current_item = selected
        self.nowPlayingChanged.emit()
        self._resolve_current()

    def _resolve_current(self) -> None:
        item = self._current_item
        if item is None:
            return
        self._stream_request += 1
        request_id = self._stream_request
        self._set_busy(True)
        self._set_status(f"Preparando {item.title}…")

        def worker() -> None:
            try:
                stream = self.youtube.resolve_stream(item.id)
                self._streamReady.emit(request_id, stream, "")
            except Exception as exc:
                LOGGER.exception("Qt stream resolve failed")
                self._streamReady.emit(request_id, None, str(exc))

        self._executor.submit(worker)

    @Slot(int, object, str)
    def _apply_stream(self, request_id: int, stream, error: str) -> None:
        if request_id != self._stream_request:
            return
        self._set_busy(False)
        if error or stream is None:
            self._set_status(f"Não foi possível reproduzir a faixa: {error}")
            return
        self._player.setSource(QUrl(stream.url))
        self._player.play()
        self._set_status("")
        if stream.playback_tracking_url:
            self._executor.submit(
                self.youtube.register_playback,
                stream.playback_tracking_url,
                self._current_item.playlist_id if self._current_item else None,
            )

    @Slot()
    def togglePlayback(self) -> None:
        if self._current_item is None:
            return
        if self.playing:
            self._player.pause()
        else:
            self._player.play()

    @Slot()
    def next(self) -> None:
        if self._queue_index + 1 < len(self._queue):
            self._queue_index += 1
            self._current_item = self._queue[self._queue_index]
            self.nowPlayingChanged.emit()
            self._resolve_current()

    @Slot()
    def previous(self) -> None:
        if self.position > 5000:
            self._player.setPosition(0)
            return
        if self._queue_index > 0:
            self._queue_index -= 1
            self._current_item = self._queue[self._queue_index]
            self.nowPlayingChanged.emit()
            self._resolve_current()

    @Slot(int)
    def seek(self, position_ms: int) -> None:
        self._player.setPosition(max(0, min(position_ms, self.duration)))

    @Slot(int)
    def setVolume(self, value: int) -> None:
        self._audio.setVolume(max(0.0, min(1.0, value / 100.0)))

    @Slot(str)
    def connectCookie(self, cookie: str) -> None:
        cookie = cookie.strip()
        if not cookie:
            return
        self._set_busy(True)
        self._set_status("Validando sessão…")

        def worker() -> None:
            try:
                ok = self.youtube.connect(cookie)
                self._sessionReady.emit(bool(ok), "" if ok else "Cookie inválido ou incompleto")
            except Exception as exc:
                self._sessionReady.emit(False, str(exc))

        self._executor.submit(worker)

    @Slot(bool, str)
    def _apply_session(self, ok: bool, error: str) -> None:
        self._set_busy(False)
        if not ok:
            self._set_status(f"Não foi possível conectar: {error}")
            return
        self._logged_in = True
        self.sessionChanged.emit()
        self._set_status("")
        self.syncAll()

    @Slot()
    def disconnectAccount(self) -> None:
        self.youtube.disconnect()
        self._logged_in = False
        self.sessionChanged.emit()
        self._set_status("Conta desconectada.")

    def _media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.next()

    def _player_error(self, _error, error_string: str) -> None:
        if error_string:
            self._set_status(f"Erro de reprodução: {error_string}")

    @Slot()
    def shutdown(self) -> None:
        self._player.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)
