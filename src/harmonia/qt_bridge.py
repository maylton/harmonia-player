from __future__ import annotations

import logging
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from .downloads import DownloadManager
from .models import ArtistPage, ExploreData, ExploreDestination, LibraryItem
from .preferences import Preferences
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


def _item_map(item: LibraryItem, *, index: int = -1, liked: bool = False) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "subtitle": item.subtitle,
        "thumbnail": item.thumbnail or "",
        "kind": item.kind,
        "playlistId": item.playlist_id or "",
        "setVideoId": item.set_video_id or "",
        "index": index,
        "liked": liked,
    }


def _destination_map(item: ExploreDestination, *, index: int = -1) -> dict[str, Any]:
    return {
        "title": item.title,
        "browseId": item.browse_id,
        "params": item.params or "",
        "index": index,
    }


class HarmoniaQtBridge(QObject):
    homeChanged = Signal()
    libraryChanged = Signal()
    searchChanged = Signal()
    exploreChanged = Signal()
    detailChanged = Signal()
    downloadsChanged = Signal()
    preferencesChanged = Signal()
    sessionChanged = Signal()
    busyChanged = Signal()
    statusChanged = Signal()
    nowPlayingChanged = Signal()
    playbackChanged = Signal()
    positionChanged = Signal()
    durationChanged = Signal()
    volumeChanged = Signal()
    currentLikeChanged = Signal()

    _syncReady = Signal(object, object, object, str)
    _searchReady = Signal(int, object, str)
    _streamReady = Signal(int, object, str)
    _sessionReady = Signal(bool, str)
    _detailReady = Signal(int, object, object, str)
    _discoveryReady = Signal(int, object, object, str)
    _downloadsUpdated = Signal()
    _mutationReady = Signal(str, bool, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.storage = Storage()
        self.youtube = YouTubeMusicService(self.storage)
        self.preferences = Preferences.load(self.storage)
        self._executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="harmonia-qt")

        self._home = self.storage.load_home()
        self._library = self.storage.load_library()
        self._explore = self.storage.load_explore()
        self._explore_display = self._explore
        self._explore_title = "Explorar"
        self._search_items: list[LibraryItem] = []
        self._current_library_category = next(iter(self._library), "songs")
        self._logged_in = bool(self.storage.load_cookie())
        self._busy = False
        self._status = ""

        self._detail_item: LibraryItem | None = None
        self._detail_tracks: list[LibraryItem] = []
        self._detail_sections: list[dict[str, Any]] = []
        self._detail_section_items: list[list[LibraryItem]] = []
        self._detail_description = ""
        self._detail_subscribers = ""
        self._detail_is_artist = False
        self._detail_request = 0
        self._discovery_request = 0

        self._queue: list[LibraryItem] = []
        self._queue_index = -1
        self._current_item: LibraryItem | None = None
        self._stream_request = 0
        self._search_request = 0
        self._shuffle = False
        self._repeat = False

        self.downloads = DownloadManager(
            self.storage,
            self.youtube,
            lambda _record: self._downloadsUpdated.emit(),
        )
        self._downloads = self.storage.load_downloads()
        self._downloadsUpdated.connect(self._reload_downloads)

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
        self._detailReady.connect(self._apply_detail)
        self._discoveryReady.connect(self._apply_discovery)
        self._mutationReady.connect(self._apply_mutation)

        if self._logged_in:
            QTimer.singleShot(120, self.syncAll)

    def _liked_ids(self) -> set[str]:
        return {item.id for item in self._library.get("songs", [])}

    def _section_map(self, title: str, items: list[LibraryItem], limit: int = 12) -> dict[str, Any]:
        unique: list[LibraryItem] = []
        seen: set[str] = set()
        for item in items:
            if item.id not in seen:
                seen.add(item.id)
                unique.append(item)

        song_section = bool(unique) and all(item.kind == "songs" for item in unique)
        selected = unique[: max(limit, 24) if song_section else limit]
        liked_ids = self._liked_ids()
        mapped = [
            _item_map(item, index=index, liked=item.id in liked_ids)
            for index, item in enumerate(selected)
        ]
        columns = [mapped[index : index + 4] for index in range(0, len(mapped), 4)]
        return {
            "title": title,
            "songSection": song_section,
            "items": mapped,
            "columns": columns if song_section else [],
        }

    @Property("QVariantList", notify=homeChanged)
    def homeSections(self) -> list[dict[str, Any]]:
        return [self._section_map(section.title, section.items) for section in self._home if section.items]

    @Property("QVariantList", notify=libraryChanged)
    def libraryCategories(self) -> list[dict[str, str]]:
        ordered = [key for key in CATEGORY_LABELS if key in self._library]
        ordered.extend(key for key in self._library if key not in ordered)
        return [{"key": key, "label": CATEGORY_LABELS.get(key, key.title())} for key in ordered]

    @Property("QVariantList", notify=libraryChanged)
    def libraryItems(self) -> list[dict[str, Any]]:
        liked_ids = self._liked_ids()
        return [
            _item_map(item, index=index, liked=item.id in liked_ids)
            for index, item in enumerate(self._library.get(self._current_library_category, []))
        ]

    @Property(str, notify=libraryChanged)
    def currentLibraryCategory(self) -> str:
        return self._current_library_category

    @Property("QVariantList", notify=searchChanged)
    def searchItems(self) -> list[dict[str, Any]]:
        liked_ids = self._liked_ids()
        return [
            _item_map(item, index=index, liked=item.id in liked_ids)
            for index, item in enumerate(self._search_items)
        ]

    @Property("QVariantList", notify=exploreChanged)
    def exploreSections(self) -> list[dict[str, Any]]:
        return [
            self._section_map(section.title, section.items)
            for section in self._explore_display.sections
            if section.items
        ]

    @Property("QVariantList", notify=exploreChanged)
    def exploreShortcuts(self) -> list[dict[str, Any]]:
        return [
            _destination_map(item, index=index)
            for index, item in enumerate(self._explore_display.shortcuts)
        ]

    @Property("QVariantList", notify=exploreChanged)
    def exploreGenres(self) -> list[dict[str, Any]]:
        return [
            _destination_map(item, index=index)
            for index, item in enumerate(self._explore_display.genres)
        ]

    @Property(str, notify=exploreChanged)
    def exploreTitle(self) -> str:
        return self._explore_title

    @Property(bool, notify=exploreChanged)
    def exploreCanGoBack(self) -> bool:
        return self._explore_display is not self._explore

    @Property("QVariantMap", notify=detailChanged)
    def detailItem(self) -> dict[str, Any]:
        if self._detail_item is None:
            return {}
        return _item_map(self._detail_item, liked=self._detail_item.id in self._liked_ids())

    @Property("QVariantList", notify=detailChanged)
    def detailTracks(self) -> list[dict[str, Any]]:
        liked_ids = self._liked_ids()
        return [
            _item_map(item, index=index, liked=item.id in liked_ids)
            for index, item in enumerate(self._detail_tracks)
        ]

    @Property("QVariantList", notify=detailChanged)
    def detailSections(self) -> list[dict[str, Any]]:
        return list(self._detail_sections)

    @Property(str, notify=detailChanged)
    def detailDescription(self) -> str:
        return self._detail_description

    @Property(str, notify=detailChanged)
    def detailSubscribers(self) -> str:
        return self._detail_subscribers

    @Property(bool, notify=detailChanged)
    def detailIsArtist(self) -> bool:
        return self._detail_is_artist

    @Property("QVariantList", notify=downloadsChanged)
    def downloadItems(self) -> list[dict[str, Any]]:
        result = []
        for index, record in enumerate(self._downloads):
            result.append(
                {
                    **_item_map(record.item, index=index, liked=record.item.id in self._liked_ids()),
                    "status": record.status,
                    "progress": record.progress,
                    "downloadedBytes": record.downloaded_bytes,
                    "totalBytes": record.total_bytes,
                    "error": record.error,
                    "filePath": record.file_path,
                }
            )
        return result

    @Property(str, notify=preferencesChanged)
    def quality(self) -> str:
        return self.preferences.quality

    @Property(str, notify=preferencesChanged)
    def language(self) -> str:
        return self.preferences.language

    @Property(str, notify=preferencesChanged)
    def region(self) -> str:
        return self.preferences.region

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
    def currentId(self) -> str:
        return self._current_item.id if self._current_item else ""

    @Property(str, notify=nowPlayingChanged)
    def currentTitle(self) -> str:
        return self._current_item.title if self._current_item else "Nenhuma música reproduzindo"

    @Property(str, notify=nowPlayingChanged)
    def currentArtist(self) -> str:
        return (
            self._current_item.subtitle if self._current_item else "Escolha uma faixa para começar"
        )

    @Property(str, notify=nowPlayingChanged)
    def currentArtwork(self) -> str:
        return (self._current_item.thumbnail or "") if self._current_item else ""

    @Property(bool, notify=currentLikeChanged)
    def currentLiked(self) -> bool:
        return bool(self._current_item and self._current_item.id in self._liked_ids())

    @Property(bool, notify=playbackChanged)
    def playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    @Property(bool, notify=playbackChanged)
    def shuffle(self) -> bool:
        return self._shuffle

    @Property(bool, notify=playbackChanged)
    def repeat(self) -> bool:
        return self._repeat

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
        return self._queue_index >= 0 and (
            self._queue_index + 1 < len(self._queue) or (self._repeat and bool(self._queue))
        )

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
        self._set_status("Sincronizando biblioteca, Início e Explorar…")

        def worker() -> None:
            try:
                library = self.youtube.sync_library()
                home = self.youtube.sync_home()
                explore = self.youtube.sync_explore()
                self._syncReady.emit(library, home, explore, "")
            except Exception as exc:
                LOGGER.exception("Qt sync failed")
                self._syncReady.emit(None, None, None, str(exc))

        self._executor.submit(worker)

    @Slot(object, object, object, str)
    def _apply_sync(self, library, home, explore, error: str) -> None:
        self._set_busy(False)
        if error:
            self._set_status(f"Não foi possível sincronizar: {error}")
            return
        self._library = library or {}
        self._home = home or []
        self._explore = explore or ExploreData([], [], [])
        self._explore_display = self._explore
        self._explore_title = "Explorar"
        if self._current_library_category not in self._library:
            self._current_library_category = next(iter(self._library), "songs")
        self.homeChanged.emit()
        self.libraryChanged.emit()
        self.exploreChanged.emit()
        self.detailChanged.emit()
        self.currentLikeChanged.emit()
        self._reload_downloads()
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

    def _home_items(self, section_index: int) -> list[LibraryItem]:
        if not 0 <= section_index < len(self._home):
            return []
        unique: list[LibraryItem] = []
        seen: set[str] = set()
        for item in self._home[section_index].items:
            if item.id not in seen:
                seen.add(item.id)
                unique.append(item)
        song_section = bool(unique) and all(item.kind == "songs" for item in unique)
        return unique[:24 if song_section else 12]

    @Slot(int, int)
    def openHomeItem(self, section_index: int, item_index: int) -> None:
        items = self._home_items(section_index)
        self._open_or_play(items, item_index)

    @Slot(int)
    def playHomeSection(self, section_index: int) -> None:
        items = [item for item in self._home_items(section_index) if item.kind == "songs"]
        if items:
            self._play_queue(items, 0)

    @Slot(int)
    def openLibraryItem(self, item_index: int) -> None:
        items = self._library.get(self._current_library_category, [])
        self._open_or_play(items, item_index)

    @Slot(int)
    def openSearchItem(self, item_index: int) -> None:
        self._open_or_play(self._search_items, item_index)

    def _open_or_play(self, items: list[LibraryItem], index: int) -> None:
        if not 0 <= index < len(items):
            return
        selected = items[index]
        if selected.kind in {"songs", "videos"}:
            playable = [item for item in items if item.kind in {"songs", "videos"}]
            selected_index = playable.index(selected) if selected in playable else 0
            self._play_queue(playable, selected_index)
        else:
            self._open_detail(selected)

    def _open_detail(self, item: LibraryItem) -> None:
        self._detail_request += 1
        request_id = self._detail_request
        self._detail_item = item
        self._detail_tracks = []
        self._detail_sections = []
        self._detail_section_items = []
        self._detail_description = ""
        self._detail_subscribers = ""
        self._detail_is_artist = item.kind == "artists"
        self.detailChanged.emit()
        self._set_busy(True)
        self._set_status(f"Carregando {item.title}…")

        def worker() -> None:
            try:
                payload = self.youtube.artist(item.id) if item.kind == "artists" else self.youtube.browse(item)
                self._detailReady.emit(request_id, item, payload, "")
            except Exception as exc:
                LOGGER.exception("Qt detail failed")
                self._detailReady.emit(request_id, item, None, str(exc))

        self._executor.submit(worker)

    @Slot(int, object, object, str)
    def _apply_detail(self, request_id: int, item, payload, error: str) -> None:
        if request_id != self._detail_request:
            return
        self._set_busy(False)
        if error or payload is None:
            self._set_status(f"Não foi possível abrir {item.title}: {error}")
            self.detailChanged.emit()
            return

        if isinstance(payload, ArtistPage):
            artist = payload
            self._detail_item = LibraryItem(
                item.id,
                artist.title,
                artist.subscribers or item.subtitle,
                artist.thumbnail or item.thumbnail,
                "artists",
            )
            self._detail_tracks = list(artist.songs)
            self._detail_description = artist.description
            self._detail_subscribers = artist.subscribers
            self._detail_is_artist = True
            artist_sections = [section for section in (artist.sections or []) if section.items]
            self._detail_section_items = [list(section.items) for section in artist_sections]
            self._detail_sections = [
                self._section_map(section.title, section.items) for section in artist_sections
            ]
        else:
            tracks = list(payload or [])
            for track in tracks:
                if not track.thumbnail and item.thumbnail:
                    track.thumbnail = item.thumbnail
            self._detail_item = item
            self._detail_tracks = tracks
            self._detail_sections = []
            self._detail_section_items = []
            self._detail_description = ""
            self._detail_subscribers = ""
            self._detail_is_artist = False

        self.detailChanged.emit()
        self._set_status("")

    @Slot(int)
    def playDetailTrack(self, index: int) -> None:
        if 0 <= index < len(self._detail_tracks):
            self._play_queue(self._detail_tracks, index)

    @Slot()
    def playDetailAll(self) -> None:
        if self._detail_tracks:
            self._play_queue(self._detail_tracks, 0)

    @Slot(int, int)
    def openDetailSectionItem(self, section_index: int, item_index: int) -> None:
        if not 0 <= section_index < len(self._detail_section_items):
            return
        items = self._detail_section_items[section_index]
        self._open_or_play(items, item_index)

    @Slot(int)
    def playDetailSection(self, section_index: int) -> None:
        if not 0 <= section_index < len(self._detail_section_items):
            return
        items = [
            item
            for item in self._detail_section_items[section_index]
            if item.kind in {"songs", "videos"}
        ]
        if items:
            self._play_queue(items, 0)

    @Slot(str, int)
    def openExploreDestination(self, group: str, index: int) -> None:
        values = self._explore_display.shortcuts if group == "shortcuts" else self._explore_display.genres
        if not 0 <= index < len(values):
            return
        destination = values[index]
        self._discovery_request += 1
        request_id = self._discovery_request
        self._set_busy(True)
        self._set_status(f"Carregando {destination.title}…")

        def worker() -> None:
            try:
                data = self.youtube.discovery(destination)
                self._discoveryReady.emit(request_id, destination, data, "")
            except Exception as exc:
                LOGGER.exception("Qt discovery failed")
                self._discoveryReady.emit(request_id, destination, None, str(exc))

        self._executor.submit(worker)

    @Slot(int, object, object, str)
    def _apply_discovery(self, request_id: int, destination, data, error: str) -> None:
        if request_id != self._discovery_request:
            return
        self._set_busy(False)
        if error or data is None:
            self._set_status(f"Não foi possível abrir {destination.title}: {error}")
            return
        self._explore_display = data
        self._explore_title = destination.title
        self.exploreChanged.emit()
        self._set_status("")

    @Slot()
    def resetExplore(self) -> None:
        if self._explore_display is self._explore:
            return
        self._explore_display = self._explore
        self._explore_title = "Explorar"
        self.exploreChanged.emit()

    @Slot(int, int)
    def openExploreItem(self, section_index: int, item_index: int) -> None:
        if not 0 <= section_index < len(self._explore_display.sections):
            return
        items = self._explore_display.sections[section_index].items
        unique: list[LibraryItem] = []
        seen: set[str] = set()
        for item in items:
            if item.id not in seen:
                seen.add(item.id)
                unique.append(item)
        song_section = bool(unique) and all(item.kind == "songs" for item in unique)
        selected = unique[:24 if song_section else 12]
        self._open_or_play(selected, item_index)

    @Slot(int)
    def playExploreSection(self, section_index: int) -> None:
        if not 0 <= section_index < len(self._explore_display.sections):
            return
        items = [
            item
            for item in self._explore_display.sections[section_index].items
            if item.kind == "songs"
        ]
        if items:
            self._play_queue(items, 0)

    def _play_queue(self, items: list[LibraryItem], index: int) -> None:
        if not items or not 0 <= index < len(items):
            return
        selected = items[index]
        if selected.kind not in {"songs", "videos"}:
            self._open_detail(selected)
            return
        self._queue = list(items)
        self._queue_index = index
        self._current_item = selected
        self.nowPlayingChanged.emit()
        self.currentLikeChanged.emit()
        self._resolve_current()

    def _resolve_current(self) -> None:
        item = self._current_item
        if item is None:
            return
        offline = self.downloads.offline_path(item.id)
        if offline:
            self._player.setSource(QUrl.fromLocalFile(str(offline)))
            self._player.play()
            self._set_status("")
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
        if not self._queue:
            return
        if self._shuffle and len(self._queue) > 1:
            choices = [index for index in range(len(self._queue)) if index != self._queue_index]
            self._queue_index = random.choice(choices)
        elif self._queue_index + 1 < len(self._queue):
            self._queue_index += 1
        elif self._repeat:
            self._queue_index = 0
        else:
            return
        self._current_item = self._queue[self._queue_index]
        self.nowPlayingChanged.emit()
        self.currentLikeChanged.emit()
        self._resolve_current()

    @Slot()
    def previous(self) -> None:
        if self.position > 5000:
            self._player.setPosition(0)
            return
        if self._queue_index > 0:
            self._queue_index -= 1
        elif self._repeat and self._queue:
            self._queue_index = len(self._queue) - 1
        else:
            return
        self._current_item = self._queue[self._queue_index]
        self.nowPlayingChanged.emit()
        self.currentLikeChanged.emit()
        self._resolve_current()

    @Slot()
    def toggleShuffle(self) -> None:
        self._shuffle = not self._shuffle
        self.playbackChanged.emit()

    @Slot()
    def toggleRepeat(self) -> None:
        self._repeat = not self._repeat
        self.playbackChanged.emit()
        self.nowPlayingChanged.emit()

    @Slot(int)
    def seek(self, position_ms: int) -> None:
        self._player.setPosition(max(0, min(position_ms, self.duration)))

    @Slot(int)
    def setVolume(self, value: int) -> None:
        self._audio.setVolume(max(0.0, min(1.0, value / 100.0)))

    def _find_item(self, item_id: str) -> LibraryItem | None:
        groups: list[list[LibraryItem]] = [
            self._search_items,
            self._detail_tracks,
            self._queue,
            *self._library.values(),
        ]
        groups.extend(section.items for section in self._home)
        groups.extend(section.items for section in self._explore.sections)
        groups.extend(section.items for section in self._explore_display.sections)
        for group in groups:
            for item in group:
                if item.id == item_id:
                    return item
        if self._current_item and self._current_item.id == item_id:
            return self._current_item
        return None

    @Slot(str)
    def toggleLike(self, item_id: str) -> None:
        item = self._find_item(item_id)
        if item is None:
            return
        liked = item_id not in self._liked_ids()
        self._set_status("Atualizando músicas curtidas…")

        def worker() -> None:
            try:
                self.youtube.mutate(lambda client: client.like_song(item.id, liked))
                self._mutationReady.emit("like", True, "")
            except Exception as exc:
                LOGGER.exception("Qt like mutation failed")
                self._mutationReady.emit("like", False, str(exc))

        self._executor.submit(worker)

    @Slot(str)
    def downloadItem(self, item_id: str) -> None:
        item = self._find_item(item_id)
        if item:
            self.downloads.start(item)
            self._set_status(f"Download de {item.title} iniciado.")

    @Slot()
    def downloadDetail(self) -> None:
        for item in self._detail_tracks:
            if item.kind in {"songs", "videos"}:
                self.downloads.start(item)
        if self._detail_tracks:
            self._set_status("Downloads da coleção iniciados.")

    @Slot(str)
    def pauseDownload(self, item_id: str) -> None:
        self.downloads.pause(item_id)

    @Slot(str)
    def resumeDownload(self, item_id: str) -> None:
        record = self.storage.get_download(item_id)
        if record:
            self.downloads.start(record.item)

    @Slot(str)
    def removeDownload(self, item_id: str) -> None:
        self.downloads.remove(item_id)

    @Slot()
    def _reload_downloads(self) -> None:
        self._downloads = self.storage.load_downloads()
        self.downloadsChanged.emit()

    @Slot(str, bool, str)
    def _apply_mutation(self, kind: str, ok: bool, error: str) -> None:
        if not ok:
            self._set_status(f"Não foi possível aplicar a alteração: {error}")
            return
        if kind == "like":
            self._set_status("")
            self.syncAll()

    @Slot(str)
    def setQuality(self, value: str) -> None:
        if value not in Preferences.QUALITY_BITRATES or value == self.preferences.quality:
            return
        self.preferences.quality = value
        self.preferences.save(self.storage)
        self.preferencesChanged.emit()
        self._set_status("Qualidade de áudio atualizada.")

    @Slot(str, str)
    def setLocale(self, language: str, region: str) -> None:
        language = language.strip() or "pt-BR"
        region = region.strip().upper() or "BR"
        self.preferences.language = language
        self.preferences.region = region
        self.preferences.save(self.storage)
        self.preferencesChanged.emit()
        self._set_status("Idioma e região salvos. Sincronize para atualizar o conteúdo.")

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
