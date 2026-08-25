from __future__ import annotations

import logging
import random
import time
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from .downloads import DownloadManager
from .lyrics import LyricsResolver
from .models import (
    ArtistPage,
    ExploreData,
    ExploreDestination,
    HistoryEntry,
    LibraryItem,
    PlaybackState,
)
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
MONTH_NAMES = ("Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez")


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
    queueChanged = Signal()
    historyChanged = Signal()
    insightsChanged = Signal()
    lyricsChanged = Signal()
    lyricPositionChanged = Signal()
    autoplayLoadingChanged = Signal()

    _syncReady = Signal(object, object, object, str)
    _searchReady = Signal(int, object, str)
    _streamReady = Signal(int, object, str)
    _sessionReady = Signal(bool, str)
    _detailReady = Signal(int, object, object, str)
    _discoveryReady = Signal(int, object, object, str)
    _downloadsUpdated = Signal()
    _mutationReady = Signal(str, bool, str)
    _historyReady = Signal(int, object, str)
    _lyricsReady = Signal(int, object, str)
    _radioReady = Signal(int, object, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.storage = Storage()
        self.youtube = YouTubeMusicService(self.storage)
        self.preferences = Preferences.load(self.storage)
        self.lyrics_resolver = LyricsResolver(self.youtube.lyrics)
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
        self._related_items: list[LibraryItem] = []
        self._queue_index = -1
        self._current_item: LibraryItem | None = None
        self._stream_request = 0
        self._search_request = 0
        self._shuffle = False
        self._repeat = False
        self._autoplay = True
        self._autoplay_loading = False
        self._waiting_for_autoplay = False
        self._radio_request = 0
        self._last_state_save = time.monotonic()
        self._play_generation = 0
        self._history_recorded_generation = -1
        self._pending_tracking_url = ""

        restored = self.storage.load_playback_state()
        if restored and restored.queue:
            self._queue = list(restored.queue)
            self._related_items = list(restored.related)
            self._queue_index = restored.index
            self._current_item = self._queue[self._queue_index]
            self._shuffle = restored.shuffle
            self._repeat = restored.repeat
            self._autoplay = restored.autoplay
            self._play_generation = 1

        self._history_entries: list[HistoryEntry] = self.storage.load_history()
        self._history_loading = False
        self._history_request = 0
        self._insights_data = self.storage.playback_insights()

        self._lyrics_document = None
        self._lyrics_loading = False
        self._lyrics_request = 0
        self._active_lyric_index = -1

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
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(lambda *_: self.durationChanged.emit())
        self._player.playbackStateChanged.connect(lambda *_: self.playbackChanged.emit())
        self._player.mediaStatusChanged.connect(self._media_status_changed)
        self._player.errorOccurred.connect(self._player_error)
        self._audio.volumeChanged.connect(lambda *_: self.volumeChanged.emit())

        self._syncReady.connect(self._apply_sync)
        self._searchReady.connect(self._apply_search)
        self._streamReady.connect(self._apply_stream)
        self._sessionReady.connect(self._apply_session)
        self._detailReady.connect(self._apply_detail)
        self._discoveryReady.connect(self._apply_discovery)
        self._mutationReady.connect(self._apply_mutation)
        self._historyReady.connect(self._apply_history)
        self._lyricsReady.connect(self._apply_lyrics)
        self._radioReady.connect(self._apply_radio)

        if self._logged_in:
            QTimer.singleShot(120, self.syncAll)

    def _liked_ids(self) -> set[str]:
        return {item.id for item in self._library.get("songs", [])}

    def _section_map(
        self,
        title: str,
        items: list[LibraryItem],
        limit: int = 12,
    ) -> dict[str, Any]:
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
        return [
            self._section_map(section.title, section.items)
            for section in self._home
            if section.items
        ]

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
                    **_item_map(
                        record.item,
                        index=index,
                        liked=record.item.id in self._liked_ids(),
                    ),
                    "status": record.status,
                    "progress": record.progress,
                    "downloadedBytes": record.downloaded_bytes,
                    "totalBytes": record.total_bytes,
                    "error": record.error,
                    "filePath": record.file_path,
                }
            )
        return result

    @Property("QVariantList", notify=queueChanged)
    def queueItems(self) -> list[dict[str, Any]]:
        liked_ids = self._liked_ids()
        return [
            {
                **_item_map(item, index=index, liked=item.id in liked_ids),
                "current": index == self._queue_index,
            }
            for index, item in enumerate(self._queue)
        ]

    @Property("QVariantList", notify=queueChanged)
    def relatedItems(self) -> list[dict[str, Any]]:
        liked_ids = self._liked_ids()
        return [
            _item_map(item, index=index, liked=item.id in liked_ids)
            for index, item in enumerate(self._related_items)
        ]

    @Property(bool, notify=playbackChanged)
    def autoplay(self) -> bool:
        return self._autoplay

    @Property(bool, notify=autoplayLoadingChanged)
    def autoplayLoading(self) -> bool:
        return self._autoplay_loading

    @Property("QVariantList", notify=historyChanged)
    def historyItems(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        liked_ids = self._liked_ids()
        for index, entry in enumerate(self._history_entries):
            if entry.source == "local" and entry.played_at:
                played = datetime.fromtimestamp(entry.played_at)
                group = played.strftime("%d/%m/%Y")
                played_label = played.strftime("%H:%M")
            else:
                group = entry.group or "YouTube Music"
                played_label = "YouTube Music" if entry.source == "remote" else ""
            result.append(
                {
                    **_item_map(entry.item, index=index, liked=entry.item.id in liked_ids),
                    "entryId": entry.id if entry.id is not None else -1,
                    "source": entry.source,
                    "group": group,
                    "playedLabel": played_label,
                    "canRemove": entry.source == "local" or bool(entry.feedback_token),
                }
            )
        return result

    @Property(bool, notify=historyChanged)
    def historyEnabled(self) -> bool:
        return self.storage.history_enabled()

    @Property(bool, notify=historyChanged)
    def historyLoading(self) -> bool:
        return self._history_loading

    @Property(bool, notify=historyChanged)
    def hasLocalHistory(self) -> bool:
        return any(entry.source == "local" for entry in self._history_entries)

    @Property("QVariantMap", notify=insightsChanged)
    def insights(self) -> dict[str, Any]:
        data = self._insights_data
        minutes = data.listened_minutes
        if minutes >= 60:
            hours, remainder = divmod(minutes, 60)
            listened_label = f"{hours} h {remainder} min" if remainder else f"{hours} h"
        else:
            listened_label = f"{minutes} min"
        maximum = max(data.monthly_plays) or 1
        liked_ids = self._liked_ids()
        return {
            "year": data.year,
            "totalPlays": data.total_plays,
            "uniqueTracks": data.unique_tracks,
            "listenedMinutes": minutes,
            "listenedLabel": listened_label,
            "topTracks": [
                {
                    **_item_map(ranked.item, index=index, liked=ranked.item.id in liked_ids),
                    "plays": ranked.plays,
                    "listenedMs": ranked.listened_ms,
                }
                for index, ranked in enumerate(data.top_tracks)
            ],
            "topArtists": [
                {"name": ranked.name, "plays": ranked.plays}
                for ranked in data.top_artists
            ],
            "months": [
                {"label": label, "plays": plays, "ratio": plays / maximum}
                for label, plays in zip(MONTH_NAMES, data.monthly_plays, strict=True)
            ],
        }

    @Property("QVariantList", notify=lyricsChanged)
    def lyricLines(self) -> list[dict[str, Any]]:
        if self._lyrics_document is None:
            return []
        return [
            {
                "startMs": line.start_ms,
                "text": line.text,
                "translation": line.translation,
            }
            for line in self._lyrics_document.synced
        ]

    @Property(str, notify=lyricsChanged)
    def lyricsPlain(self) -> str:
        return self._lyrics_document.display_text if self._lyrics_document else ""

    @Property(str, notify=lyricsChanged)
    def lyricsProvider(self) -> str:
        return self._lyrics_document.provider if self._lyrics_document else ""

    @Property(bool, notify=lyricsChanged)
    def lyricsLoading(self) -> bool:
        return self._lyrics_loading

    @Property(int, notify=lyricPositionChanged)
    def activeLyricIndex(self) -> int:
        return self._active_lyric_index

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
            self._queue_index + 1 < len(self._queue)
            or (self._repeat and bool(self._queue))
            or self._autoplay
        )

    def _set_busy(self, value: bool) -> None:
        if self._busy != value:
            self._busy = value
            self.busyChanged.emit()

    def _set_status(self, value: str) -> None:
        if self._status != value:
            self._status = value
            self.statusChanged.emit()

    def _set_autoplay_loading(self, value: bool) -> None:
        if self._autoplay_loading != value:
            self._autoplay_loading = value
            self.autoplayLoadingChanged.emit()

    def _save_playback_state(self, position_ms: int | None = None) -> None:
        if not self._queue:
            return
        self.storage.save_playback_state(
            PlaybackState(
                list(self._queue),
                list(self._related_items),
                max(0, self._queue_index),
                self.position if position_ms is None else max(0, position_ms),
                self._shuffle,
                self._repeat,
                self._autoplay,
            )
        )
        self._last_state_save = time.monotonic()

    def _on_position_changed(self, value: int) -> None:
        self.positionChanged.emit()
        self._update_active_lyric(value)
        self._maybe_record_history(value)
        if self._queue and time.monotonic() - self._last_state_save >= 5:
            self._save_playback_state(value)

    def _maybe_record_history(self, position_ms: int) -> None:
        if (
            self._current_item is None
            or position_ms < 30_000
            or self._history_recorded_generation == self._play_generation
            or not self.storage.history_enabled()
        ):
            return
        entry_id = self.storage.record_history(self._current_item, position_ms)
        self._history_recorded_generation = self._play_generation
        if entry_id is not None:
            self._history_entries.insert(
                0,
                HistoryEntry(
                    entry_id,
                    self._current_item,
                    int(time.time()),
                    position_ms,
                    "local",
                ),
            )
            self.historyChanged.emit()
            self.refreshInsights()
        if self._pending_tracking_url:
            tracking_url = self._pending_tracking_url
            playlist_id = self._current_item.playlist_id
            self._pending_tracking_url = ""
            self._executor.submit(self.youtube.register_playback, tracking_url, playlist_id)

    def _reset_lyrics(self) -> None:
        self._lyrics_request += 1
        self._lyrics_document = None
        self._lyrics_loading = False
        self._active_lyric_index = -1
        self.lyricsChanged.emit()
        self.lyricPositionChanged.emit()

    def _set_current_from_queue(self, index: int, *, resolve: bool = True) -> None:
        if not 0 <= index < len(self._queue):
            return
        self._queue_index = index
        self._current_item = self._queue[index]
        self._play_generation += 1
        self._history_recorded_generation = -1
        self._pending_tracking_url = ""
        self._reset_lyrics()
        self.nowPlayingChanged.emit()
        self.currentLikeChanged.emit()
        self.queueChanged.emit()
        self._save_playback_state(0)
        if resolve:
            self._resolve_current()

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
        self.queueChanged.emit()
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
        return unique[: 24 if song_section else 12]

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
                payload = (
                    self.youtube.artist(item.id)
                    if item.kind == "artists"
                    else self.youtube.browse(item)
                )
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
        values = (
            self._explore_display.shortcuts
            if group == "shortcuts"
            else self._explore_display.genres
        )
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
        selected = unique[: 24 if song_section else 12]
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
        self._related_items = []
        self._waiting_for_autoplay = False
        self._radio_request += 1
        self._set_autoplay_loading(False)
        self._queue = list(items)
        self._set_current_from_queue(index)
        self._ensure_autoplay()

    def _resolve_current(self) -> None:
        item = self._current_item
        if item is None:
            return
        self._stream_request += 1
        request_id = self._stream_request
        self._pending_tracking_url = ""
        offline = self.downloads.offline_path(item.id)
        if offline:
            self._player.setSource(QUrl.fromLocalFile(str(offline)))
            self._player.play()
            self._set_status("")
            self._ensure_autoplay()
            return

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
        self._pending_tracking_url = stream.playback_tracking_url or ""
        self._player.setSource(QUrl(stream.url))
        self._player.play()
        self._set_status("")
        self._ensure_autoplay()

    @Slot()
    def togglePlayback(self) -> None:
        if self._current_item is None:
            return
        if self._player.source().isEmpty():
            self._resolve_current()
        elif self.playing:
            self._player.pause()
        else:
            self._player.play()

    @Slot()
    def next(self) -> None:
        if not self._queue:
            return
        if self._shuffle and len(self._queue) > 1:
            choices = [index for index in range(len(self._queue)) if index != self._queue_index]
            self._set_current_from_queue(random.choice(choices))
            self._ensure_autoplay()
            return
        if self._queue_index + 1 < len(self._queue):
            self._set_current_from_queue(self._queue_index + 1)
            self._ensure_autoplay()
            return
        if self._repeat:
            self._set_current_from_queue(0)
            self._ensure_autoplay()
            return
        if self._autoplay:
            if self._related_items:
                self._promote_related_index(0, True)
                self._set_current_from_queue(self._queue_index + 1)
            else:
                self._waiting_for_autoplay = True
                self._ensure_autoplay(force=True)

    @Slot()
    def previous(self) -> None:
        if self.position > 5000:
            self._player.setPosition(0)
            return
        if self._queue_index > 0:
            self._set_current_from_queue(self._queue_index - 1)
        elif self._repeat and self._queue:
            self._set_current_from_queue(len(self._queue) - 1)

    @Slot()
    def toggleShuffle(self) -> None:
        self._shuffle = not self._shuffle
        self.playbackChanged.emit()
        self._save_playback_state()

    @Slot()
    def toggleRepeat(self) -> None:
        self._repeat = not self._repeat
        self.playbackChanged.emit()
        self.nowPlayingChanged.emit()
        self._save_playback_state()

    @Slot()
    def toggleAutoplay(self) -> None:
        self._autoplay = not self._autoplay
        self._waiting_for_autoplay = False
        if not self._autoplay:
            self._radio_request += 1
            self._set_autoplay_loading(False)
        self.playbackChanged.emit()
        self.nowPlayingChanged.emit()
        self._save_playback_state()
        if self._autoplay:
            self._ensure_autoplay(force=True)

    def _ensure_autoplay(self, force: bool = False) -> None:
        if not self._autoplay or not self._queue or self._autoplay_loading:
            return
        if self._related_items:
            if self._waiting_for_autoplay:
                self._waiting_for_autoplay = False
                self._promote_related_index(0, True)
                self._set_current_from_queue(self._queue_index + 1)
            return
        remaining = len(self._queue) - self._queue_index - 1
        if not force and remaining > 5:
            return
        seed = self._queue[-1]
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

        self._executor.submit(worker)

    @Slot(int, object, str)
    def _apply_radio(self, request_id: int, recommendations, error: str) -> None:
        if request_id != self._radio_request:
            return
        self._set_autoplay_loading(False)
        if error:
            if self._waiting_for_autoplay:
                self._waiting_for_autoplay = False
                self._set_status(f"Não foi possível continuar a rádio: {error}")
            return
        existing = {item.id for item in self._queue}
        self._related_items = [
            item for item in list(recommendations or []) if item.id not in existing
        ]
        self.queueChanged.emit()
        self._save_playback_state()
        if self._waiting_for_autoplay and self._related_items:
            self._waiting_for_autoplay = False
            self._promote_related_index(0, True)
            self._set_current_from_queue(self._queue_index + 1)
        elif self._waiting_for_autoplay:
            self._waiting_for_autoplay = False
            self._set_status("A rádio não encontrou novas músicas.")

    def _promote_related_index(self, index: int, play_next: bool) -> None:
        if not 0 <= index < len(self._related_items):
            return
        item = self._related_items.pop(index)
        position = min(len(self._queue), self._queue_index + 1) if play_next else len(self._queue)
        self._queue.insert(position, item)
        self.queueChanged.emit()
        self.nowPlayingChanged.emit()
        self._save_playback_state()

    @Slot(int, bool)
    def promoteRelated(self, index: int, play_next: bool) -> None:
        self._promote_related_index(index, play_next)

    @Slot(int)
    def selectQueueItem(self, index: int) -> None:
        if 0 <= index < len(self._queue):
            self._set_current_from_queue(index)
            self._ensure_autoplay()

    @Slot(int, int)
    def moveQueueItem(self, index: int, direction: int) -> None:
        target = index + direction
        if not (0 <= index < len(self._queue) and 0 <= target < len(self._queue)):
            return
        self._queue[index], self._queue[target] = self._queue[target], self._queue[index]
        if self._queue_index == index:
            self._queue_index = target
        elif self._queue_index == target:
            self._queue_index = index
        self.queueChanged.emit()
        self.nowPlayingChanged.emit()
        self._save_playback_state()

    @Slot(int)
    def removeQueueItem(self, index: int) -> None:
        if not 0 <= index < len(self._queue):
            return
        removing_current = index == self._queue_index
        self._queue.pop(index)
        if not self._queue:
            self._player.stop()
            self._player.setSource(QUrl())
            self._current_item = None
            self._queue_index = -1
            self._related_items = []
            self.storage.clear_playback_state()
            self._reset_lyrics()
            self.nowPlayingChanged.emit()
            self.currentLikeChanged.emit()
            self.queueChanged.emit()
            return
        if index < self._queue_index:
            self._queue_index -= 1
        elif self._queue_index >= len(self._queue):
            self._queue_index = len(self._queue) - 1
        if removing_current:
            self._set_current_from_queue(self._queue_index)
        else:
            self.queueChanged.emit()
            self.nowPlayingChanged.emit()
            self._save_playback_state()

    @Slot(int)
    def seek(self, position_ms: int) -> None:
        self._player.setPosition(max(0, min(position_ms, self.duration)))
        self._save_playback_state(position_ms)

    @Slot(int)
    def setVolume(self, value: int) -> None:
        self._audio.setVolume(max(0.0, min(1.0, value / 100.0)))

    @Slot()
    def refreshHistory(self) -> None:
        self._history_request += 1
        request_id = self._history_request
        local = self.storage.load_history()
        if not self._logged_in:
            self._history_entries = local
            self._history_loading = False
            self.historyChanged.emit()
            return
        self._history_loading = True
        self.historyChanged.emit()

        def worker() -> None:
            try:
                remote = self.youtube.history()
                self._historyReady.emit(request_id, remote, "")
            except Exception as exc:
                LOGGER.exception("Qt history sync failed")
                self._historyReady.emit(request_id, [], str(exc))

        self._executor.submit(worker)

    @Slot(int, object, str)
    def _apply_history(self, request_id: int, remote, error: str) -> None:
        if request_id != self._history_request:
            return
        self._history_loading = False
        local = self.storage.load_history()
        self._history_entries = [*list(remote or []), *local]
        self.historyChanged.emit()
        if error:
            self._set_status(f"O histórico local foi preservado; o remoto falhou: {error}")

    @Slot(bool)
    def setHistoryEnabled(self, enabled: bool) -> None:
        self.storage.set_history_enabled(enabled)
        self.historyChanged.emit()

    @Slot()
    def clearLocalHistory(self) -> None:
        self.storage.clear_history()
        self._history_entries = [entry for entry in self._history_entries if entry.source != "local"]
        self.historyChanged.emit()
        self.refreshInsights()

    @Slot(int)
    def removeHistoryItem(self, index: int) -> None:
        if not 0 <= index < len(self._history_entries):
            return
        entry = self._history_entries[index]
        if entry.source == "local" and entry.id is not None:
            self.storage.remove_history(entry.id)
            self._history_entries.pop(index)
            self.historyChanged.emit()
            self.refreshInsights()
            return
        if not entry.feedback_token:
            return

        def worker() -> None:
            try:
                self.youtube.remove_history_item(entry.feedback_token or "")
                self._mutationReady.emit("history", True, "")
            except Exception as exc:
                LOGGER.exception("Qt remote history removal failed")
                self._mutationReady.emit("history", False, str(exc))

        self._executor.submit(worker)

    @Slot(int)
    def playHistoryItem(self, index: int) -> None:
        if 0 <= index < len(self._history_entries):
            item = self._history_entries[index].item
            self._play_queue([item], 0)

    @Slot()
    def refreshInsights(self) -> None:
        self._insights_data = self.storage.playback_insights()
        self.insightsChanged.emit()

    @Slot(int)
    def playInsightTrack(self, index: int) -> None:
        if 0 <= index < len(self._insights_data.top_tracks):
            self._play_queue([self._insights_data.top_tracks[index].item], 0)

    @Slot()
    def loadLyrics(self) -> None:
        self._load_lyrics(force=False)

    @Slot()
    def reloadLyrics(self) -> None:
        self._load_lyrics(force=True)

    def _load_lyrics(self, force: bool) -> None:
        item = self._current_item
        if item is None:
            self._reset_lyrics()
            return
        provider = self.storage.get_setting("lyrics_provider", "auto")
        if provider not in {"auto", "lrclib", "youtube"}:
            provider = "auto"
        if not force:
            cached = self.storage.load_lyrics_document(item.id, provider)
            if cached:
                self._lyrics_document = cached
                self._lyrics_loading = False
                self.lyricsChanged.emit()
                self._update_active_lyric(self.position)
                return
        self._lyrics_request += 1
        request_id = self._lyrics_request
        self._lyrics_loading = True
        self._lyrics_document = None
        self._active_lyric_index = -1
        self.lyricsChanged.emit()
        self.lyricPositionChanged.emit()

        def worker() -> None:
            try:
                document = self.lyrics_resolver.fetch(item, self.duration, provider)
                self._lyricsReady.emit(request_id, document, "")
            except Exception as exc:
                LOGGER.exception("Qt lyrics fetch failed")
                self._lyricsReady.emit(request_id, None, str(exc))

        self._executor.submit(worker)

    @Slot(int, object, str)
    def _apply_lyrics(self, request_id: int, document, error: str) -> None:
        if request_id != self._lyrics_request:
            return
        self._lyrics_loading = False
        self._lyrics_document = document
        if document and self._current_item:
            self.storage.save_lyrics_document(self._current_item.id, document)
        self.lyricsChanged.emit()
        self._update_active_lyric(self.position)
        if error:
            self._set_status(f"Não foi possível carregar a letra: {error}")

    def _update_active_lyric(self, position_ms: int) -> None:
        lines = self._lyrics_document.synced if self._lyrics_document else []
        if not lines:
            index = -1
        else:
            index = bisect_right([line.start_ms for line in lines], position_ms) - 1
        if index != self._active_lyric_index:
            self._active_lyric_index = index
            self.lyricPositionChanged.emit()

    def _find_item(self, item_id: str) -> LibraryItem | None:
        groups: list[list[LibraryItem]] = [
            self._search_items,
            self._detail_tracks,
            self._queue,
            self._related_items,
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
        elif kind == "history":
            self._set_status("")
            self.refreshHistory()

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
        if self._queue:
            self._save_playback_state()
        self._player.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)
