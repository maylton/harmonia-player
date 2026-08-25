from __future__ import annotations

import logging
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtWidgets import QApplication

from .downloads import DownloadManager
from .models import ExploreData, LibraryItem
from .mpris import MprisService
from .qt_activity import QtHistoryController, QtLyricsController
from .qt_catalog import QtCatalogController
from .qt_library import QtLibraryController
from .qt_mutations import QtMutationController
from .qt_playback import QtPlaybackController
from .qt_preferences import QtPreferencesController
from .qt_presenters import destination_map, history_map, insights_map, item_map
from .services import YouTubeMusicService
from .storage import Storage

LOGGER = logging.getLogger(__name__)


class HarmoniaQtBackend(QObject):
    """Stable QObject facade exposed to QML.

    Controllers own domain-specific behavior; this object only maps their state
    to QML properties/slots and wires cross-domain events. GTK keeps its own
    presentation layer while both frontends reuse the same services, storage,
    player and MPRIS implementation.
    """

    homeChanged = Signal()
    libraryChanged = Signal()
    searchChanged = Signal()
    suggestionsChanged = Signal()
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

    _downloadsUpdated = Signal()
    _sessionReady = Signal(bool, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = parent
        self.storage = Storage()
        self.youtube = YouTubeMusicService(self.storage)
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="harmonia-qt")
        self._logged_in = bool(self.storage.load_cookie())
        self._busy = False
        self._status = ""

        self.downloads = DownloadManager(
            self.storage,
            self.youtube,
            lambda _record: self._downloadsUpdated.emit(),
        )
        self._downloads = self.storage.load_downloads()

        self.playback = QtPlaybackController(
            self.storage,
            self.youtube,
            self.downloads,
            self._executor,
            self._set_busy,
            self._set_status,
            self,
        )
        self.catalog = QtCatalogController(
            self.storage,
            self.youtube,
            self._executor,
            self._set_busy,
            self._set_status,
            self.playback.play_queue,
            self,
        )
        self.library = QtLibraryController(self.storage, self.catalog, self)
        self.history = QtHistoryController(
            self.storage,
            self.youtube,
            self._executor,
            lambda: self._logged_in,
            self._set_status,
            self.playback.play_queue,
            self,
        )
        self.lyrics = QtLyricsController(
            self.storage,
            self.youtube,
            self._executor,
            lambda: self.playback.current_item,
            lambda: self.playback.duration,
            lambda: self.playback.position,
            self._set_status,
            self,
        )
        self.settings = QtPreferencesController(
            self.storage,
            self.youtube,
            self.downloads,
            self.playback,
            self._executor,
            self._set_status,
            self._reload_after_restore,
            self,
        )
        self.mutations = QtMutationController(
            self.storage,
            self.youtube,
            self._executor,
            self._set_status,
            self.syncAll,
            self,
        )

        self.mpris = MprisService(
            None,
            self.playback.player,
            {
                "next": self.playback.next,
                "previous": self.playback.previous,
                "toggle": self.playback.toggle_playback,
                "pause": self._mpris_pause,
                "play": self._mpris_play,
                "repeat": self.playback.set_repeat,
                "shuffle": self.playback.set_shuffle,
                "stop": self.playback.stop,
                "seek": lambda position_us: self.playback.seek(position_us // 1000),
            },
            {
                "repeat": lambda: self.playback.repeat,
                "shuffle": lambda: self.playback.shuffle,
                "playing": lambda: self.playback.playing,
                "position": lambda: self.playback.position * 1000,
            },
            raise_callback=self._raise_window,
            quit_callback=self._quit_application,
        )

        self._wire_controllers()
        self._downloadsUpdated.connect(self._reload_downloads)
        self._sessionReady.connect(self._apply_session)

        if self.playback.current_item:
            self.mpris.update(self.playback.current_item, self.playback.duration * 1000)
        if self._logged_in:
            self.syncAll()
        self.downloads.resume_pending()

    def _wire_controllers(self) -> None:
        self.catalog.homeChanged.connect(self.homeChanged.emit)
        self.catalog.libraryChanged.connect(self._on_library_changed)
        self.catalog.searchChanged.connect(self.searchChanged.emit)
        self.catalog.suggestionsChanged.connect(self.suggestionsChanged.emit)
        self.catalog.exploreChanged.connect(self.exploreChanged.emit)
        self.catalog.detailChanged.connect(self.detailChanged.emit)
        self.library.changed.connect(self.libraryChanged.emit)
        self.library.detailChanged.connect(self.detailChanged.emit)

        self.playback.nowPlayingChanged.connect(self._on_now_playing_changed)
        self.playback.playbackChanged.connect(self._on_playback_changed)
        self.playback.positionChanged.connect(self._on_position_changed)
        self.playback.durationChanged.connect(self._on_duration_changed)
        self.playback.volumeChanged.connect(self._on_volume_changed)
        self.playback.queueChanged.connect(self.queueChanged.emit)
        self.playback.autoplayLoadingChanged.connect(self.autoplayLoadingChanged.emit)
        self.playback.trackChanged.connect(self.lyrics.reset)
        self.playback.trackStarted.connect(self._on_track_started)
        self.playback.historyRecorded.connect(self.history.on_history_recorded)

        self.history.historyChanged.connect(self.historyChanged.emit)
        self.history.insightsChanged.connect(self.insightsChanged.emit)
        self.lyrics.lyricsChanged.connect(self.lyricsChanged.emit)
        self.lyrics.lyricPositionChanged.connect(self.lyricPositionChanged.emit)
        self.settings.changed.connect(self.preferencesChanged.emit)
        self.settings.cacheChanged.connect(self.preferencesChanged.emit)
        self.mutations.changed.connect(self._on_mutation_changed)

    def _on_library_changed(self) -> None:
        self.libraryChanged.emit()
        self.currentLikeChanged.emit()
        self.detailChanged.emit()
        self.queueChanged.emit()
        self.downloadsChanged.emit()

    def _on_mutation_changed(self) -> None:
        self.currentLikeChanged.emit()
        self.detailChanged.emit()

    def _on_now_playing_changed(self) -> None:
        self.nowPlayingChanged.emit()
        self.currentLikeChanged.emit()
        item = self.playback.current_item
        if item:
            self.mpris.update(item, self.playback.duration * 1000)
        else:
            self.mpris.clear()

    def _on_track_started(self, item, duration_ms: int) -> None:
        if item:
            self.mpris.update(item, duration_ms * 1000)

    def _on_playback_changed(self) -> None:
        self.playbackChanged.emit()
        self.mpris.update()

    def _on_position_changed(self) -> None:
        self.positionChanged.emit()
        self.lyrics.update_position(self.playback.position)

    def _on_duration_changed(self) -> None:
        self.durationChanged.emit()
        if self.playback.current_item:
            self.mpris.update(self.playback.current_item, self.playback.duration * 1000)

    def _on_volume_changed(self) -> None:
        self.volumeChanged.emit()
        self.mpris.update()

    def _liked_ids(self) -> set[str]:
        return self.catalog.liked_ids()

    def _set_busy(self, value: bool) -> None:
        if self._busy == value:
            return
        self._busy = value
        self.busyChanged.emit()

    def _set_status(self, value: str) -> None:
        if self._status == value:
            return
        self._status = value
        self.statusChanged.emit()

    def _reload_after_restore(self) -> None:
        self.catalog.library = self.storage.load_library()
        self.catalog.home = self.storage.load_home()
        self.catalog.explore = self.storage.load_explore()
        self.catalog.explore_display = self.catalog.explore
        self.catalog.explore_title = "Explorar"
        self._downloads = self.storage.load_downloads()
        self.catalog.libraryChanged.emit()
        self.catalog.homeChanged.emit()
        self.catalog.exploreChanged.emit()
        self.downloadsChanged.emit()
        self.history.refresh()
        self.history.refresh_insights()

    def _raise_window(self) -> None:
        if self._engine is None or not hasattr(self._engine, "rootObjects"):
            return
        roots = self._engine.rootObjects()
        if not roots:
            return
        window = roots[0]
        window.show()
        if hasattr(window, "raise_"):
            window.raise_()
        if hasattr(window, "requestActivate"):
            window.requestActivate()

    @staticmethod
    def _quit_application() -> None:
        app = QApplication.instance()
        if app:
            app.quit()

    def _mpris_pause(self) -> None:
        if self.playback.playing:
            self.playback.toggle_playback()

    def _mpris_play(self) -> None:
        if not self.playback.playing:
            self.playback.toggle_playback()

    @Property("QVariantList", notify=homeChanged)
    def homeSections(self) -> list[dict[str, Any]]:
        return [
            self.catalog.section(section.title, section.items)
            for section in self.catalog.home
            if section.items
        ]

    @Property("QVariantList", notify=libraryChanged)
    def libraryOrigins(self) -> list[dict[str, str]]:
        return self.library.origins

    @Property("QVariantList", notify=libraryChanged)
    def libraryCategories(self) -> list[dict[str, str]]:
        return self.library.filters

    @Property("QVariantList", notify=libraryChanged)
    def libraryItems(self) -> list[dict[str, Any]]:
        liked_ids = self._liked_ids()
        return [
            item_map(item, index=index, liked=item.id in liked_ids)
            for index, item in enumerate(self.library.items())
        ]

    @Property(str, notify=libraryChanged)
    def currentLibraryOrigin(self) -> str:
        return self.library.origin

    @Property(str, notify=libraryChanged)
    def currentLibraryCategory(self) -> str:
        return self.library.category

    @Property(str, notify=libraryChanged)
    def currentLibrarySort(self) -> str:
        return self.library.sort

    @Property(str, notify=libraryChanged)
    def libraryDescription(self) -> str:
        return self.library.description

    @Property(bool, notify=libraryChanged)
    def libraryIsLocal(self) -> bool:
        return self.library.origin == "local"

    @Property("QVariantList", notify=searchChanged)
    def searchGroups(self) -> list[dict[str, Any]]:
        liked_ids = self._liked_ids()
        return [
            {
                "key": group.key,
                "title": group.title,
                "items": [
                    item_map(item, index=index, liked=item.id in liked_ids)
                    for index, item in enumerate(group.items)
                ],
                "canLoadMore": bool(group.continuation),
            }
            for group in self.catalog.search_results.groups
        ]

    @Property(str, notify=searchChanged)
    def searchQuery(self) -> str:
        return self.catalog.search_results.query

    @Property(bool, notify=searchChanged)
    def searchHasPartialErrors(self) -> bool:
        return bool(self.catalog.search_results.errors)

    @Property("QVariantList", notify=suggestionsChanged)
    def searchSuggestions(self) -> list[str]:
        return list(self.catalog.search_suggestions)

    @Property("QVariantList", notify=exploreChanged)
    def exploreSections(self) -> list[dict[str, Any]]:
        return [
            self.catalog.section(section.title, section.items)
            for section in self.catalog.explore_display.sections
            if section.items
        ]

    @Property("QVariantList", notify=exploreChanged)
    def exploreShortcuts(self) -> list[dict[str, Any]]:
        return [
            destination_map(item, index=index)
            for index, item in enumerate(self.catalog.explore_display.shortcuts)
        ]

    @Property("QVariantList", notify=exploreChanged)
    def exploreGenres(self) -> list[dict[str, Any]]:
        return [
            destination_map(item, index=index)
            for index, item in enumerate(self.catalog.explore_display.genres)
        ]

    @Property(str, notify=exploreChanged)
    def exploreTitle(self) -> str:
        return self.catalog.explore_title

    @Property(bool, notify=exploreChanged)
    def exploreCanGoBack(self) -> bool:
        return self.catalog.explore_display is not self.catalog.explore

    @Property("QVariantMap", notify=detailChanged)
    def detailItem(self) -> dict[str, Any]:
        item = self.catalog.detail_item
        if item is None:
            return {}
        return item_map(item, liked=item.id in self._liked_ids())

    @Property("QVariantList", notify=detailChanged)
    def detailTracks(self) -> list[dict[str, Any]]:
        liked_ids = self._liked_ids()
        return [
            item_map(item, index=index, liked=item.id in liked_ids)
            for index, item in enumerate(self.catalog.detail_tracks)
        ]

    @Property("QVariantList", notify=detailChanged)
    def detailSections(self) -> list[dict[str, Any]]:
        return list(self.catalog.detail_sections)

    @Property(str, notify=detailChanged)
    def detailDescription(self) -> str:
        return self.catalog.detail_description

    @Property(str, notify=detailChanged)
    def detailSubscribers(self) -> str:
        return self.catalog.detail_subscribers

    @Property(bool, notify=detailChanged)
    def detailIsArtist(self) -> bool:
        return self.catalog.detail_is_artist

    @Property(bool, notify=detailChanged)
    def detailIsLocalPlaylist(self) -> bool:
        return bool(
            self.catalog.detail_item
            and self.catalog.detail_item.kind == "local-playlists"
        )

    @Property(bool, notify=detailChanged)
    def detailSaved(self) -> bool:
        item = self.catalog.detail_item
        if not item or item.kind not in {"albums", "playlists"}:
            return False
        return any(saved.id == item.id for saved in self.catalog.library.get(item.kind, []))

    @Property(bool, notify=detailChanged)
    def detailArtistSubscribed(self) -> bool:
        item = self.catalog.detail_item
        return bool(
            item
            and item.kind == "artists"
            and any(saved.id == item.id for saved in self.catalog.library.get("artists", []))
        )

    @Property("QVariantList", notify=libraryChanged)
    def playlistChoices(self) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = [
            {"source": "remote", "id": item.id, "title": item.title}
            for item in self.catalog.library.get("playlists", [])
        ]
        values.extend(
            {
                "source": "local",
                "id": str(playlist.id),
                "title": f"{playlist.title} · local",
            }
            for playlist in self.storage.load_local_playlists()
            if playlist.id is not None
        )
        return values

    @Property("QVariantList", notify=downloadsChanged)
    def downloadItems(self) -> list[dict[str, Any]]:
        liked_ids = self._liked_ids()
        return [
            {
                **item_map(record.item, index=index, liked=record.item.id in liked_ids),
                "status": record.status,
                "progress": record.progress,
                "downloadedBytes": record.downloaded_bytes,
                "totalBytes": record.total_bytes,
                "error": record.error,
                "filePath": record.file_path,
            }
            for index, record in enumerate(self._downloads)
        ]

    @Property(str, notify=downloadsChanged)
    def downloadStorageLabel(self) -> str:
        return self.settings.format_bytes(self.storage.download_storage_bytes())

    @Property("QVariantList", notify=queueChanged)
    def queueItems(self) -> list[dict[str, Any]]:
        liked_ids = self._liked_ids()
        return [
            {
                **item_map(item, index=index, liked=item.id in liked_ids),
                "current": index == self.playback.queue_index,
            }
            for index, item in enumerate(self.playback.queue)
        ]

    @Property("QVariantList", notify=queueChanged)
    def relatedItems(self) -> list[dict[str, Any]]:
        liked_ids = self._liked_ids()
        return [
            item_map(item, index=index, liked=item.id in liked_ids)
            for index, item in enumerate(self.playback.related_items)
        ]

    @Property(bool, notify=playbackChanged)
    def autoplay(self) -> bool:
        return self.playback.autoplay

    @Property(bool, notify=autoplayLoadingChanged)
    def autoplayLoading(self) -> bool:
        return self.playback.autoplay_loading

    @Property("QVariantList", notify=historyChanged)
    def historyItems(self) -> list[dict[str, Any]]:
        return history_map(self.history.entries, self._liked_ids())

    @Property(bool, notify=historyChanged)
    def historyEnabled(self) -> bool:
        return self.history.enabled

    @Property(bool, notify=historyChanged)
    def historyLoading(self) -> bool:
        return self.history.loading

    @Property(bool, notify=historyChanged)
    def hasLocalHistory(self) -> bool:
        return self.history.has_local

    @Property("QVariantMap", notify=insightsChanged)
    def insights(self) -> dict[str, Any]:
        return insights_map(self.history.insights_data, self._liked_ids())

    @Property("QVariantList", notify=lyricsChanged)
    def lyricLines(self) -> list[dict[str, Any]]:
        if self.lyrics.document is None:
            return []
        return [
            {
                "startMs": line.start_ms,
                "text": line.text,
                "translation": line.translation,
            }
            for line in self.lyrics.document.synced
        ]

    @Property(str, notify=lyricsChanged)
    def lyricsPlain(self) -> str:
        return self.lyrics.document.display_text if self.lyrics.document else ""

    @Property(str, notify=lyricsChanged)
    def lyricsTranslation(self) -> str:
        return self.lyrics.document.translation if self.lyrics.document else ""

    @Property(str, notify=lyricsChanged)
    def lyricsProvider(self) -> str:
        return self.lyrics.document.provider if self.lyrics.document else ""

    @Property(str, notify=lyricsChanged)
    def selectedLyricsProvider(self) -> str:
        return self.lyrics.provider

    @Property(int, notify=lyricsChanged)
    def lyricsOffset(self) -> int:
        return self.lyrics.offset_ms

    @Property(bool, notify=lyricsChanged)
    def lyricsLoading(self) -> bool:
        return self.lyrics.loading

    @Property(int, notify=lyricPositionChanged)
    def activeLyricIndex(self) -> int:
        return self.lyrics.active_index

    @Property(str, notify=preferencesChanged)
    def quality(self) -> str:
        return self.settings.values.quality

    @Property(str, notify=preferencesChanged)
    def language(self) -> str:
        return self.settings.values.language

    @Property(str, notify=preferencesChanged)
    def region(self) -> str:
        return self.settings.values.region

    @Property(str, notify=preferencesChanged)
    def proxy(self) -> str:
        return self.settings.values.proxy

    @Property(bool, notify=preferencesChanged)
    def normalization(self) -> bool:
        return self.settings.values.normalization

    @Property(str, notify=preferencesChanged)
    def equalizer(self) -> str:
        return self.settings.values.equalizer

    @Property(float, notify=preferencesChanged)
    def playbackSpeed(self) -> float:
        return self.settings.values.speed

    @Property(float, notify=preferencesChanged)
    def pitch(self) -> float:
        return self.settings.values.pitch

    @Property(bool, notify=preferencesChanged)
    def skipSilence(self) -> bool:
        return self.settings.values.skip_silence

    @Property(str, notify=preferencesChanged)
    def artworkCacheLabel(self) -> str:
        return self.settings.format_bytes(self.settings.cache_bytes)

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
        return self.playback.current_item.id if self.playback.current_item else ""

    @Property(str, notify=nowPlayingChanged)
    def currentTitle(self) -> str:
        return (
            self.playback.current_item.title
            if self.playback.current_item
            else "Nenhuma música reproduzindo"
        )

    @Property(str, notify=nowPlayingChanged)
    def currentArtist(self) -> str:
        return (
            self.playback.current_item.subtitle
            if self.playback.current_item
            else "Escolha uma faixa para começar"
        )

    @Property(str, notify=nowPlayingChanged)
    def currentArtwork(self) -> str:
        return (
            (self.playback.current_item.thumbnail or "")
            if self.playback.current_item
            else ""
        )

    @Property(bool, notify=currentLikeChanged)
    def currentLiked(self) -> bool:
        return bool(
            self.playback.current_item
            and self.playback.current_item.id in self._liked_ids()
        )

    @Property(bool, notify=playbackChanged)
    def playing(self) -> bool:
        return self.playback.playing

    @Property(bool, notify=playbackChanged)
    def shuffle(self) -> bool:
        return self.playback.shuffle

    @Property(bool, notify=playbackChanged)
    def repeat(self) -> bool:
        return self.playback.repeat

    @Property(int, notify=positionChanged)
    def position(self) -> int:
        return self.playback.position

    @Property(int, notify=durationChanged)
    def duration(self) -> int:
        return self.playback.duration

    @Property(int, notify=volumeChanged)
    def volume(self) -> int:
        return self.playback.volume

    @Property(bool, notify=nowPlayingChanged)
    def canPrevious(self) -> bool:
        return self.playback.can_previous

    @Property(bool, notify=nowPlayingChanged)
    def canNext(self) -> bool:
        return self.playback.can_next

    @Slot()
    def syncAll(self) -> None:
        if not self._logged_in:
            self._set_status("Conecte sua conta para sincronizar o Harmonia.")
            return
        self.catalog.sync_all()

    @Slot(str)
    def setLibraryOrigin(self, origin: str) -> None:
        self.library.set_origin(origin)

    @Slot(str)
    def setLibraryCategory(self, category: str) -> None:
        self.library.set_category(category)

    @Slot(str)
    def setLibrarySort(self, value: str) -> None:
        self.library.set_sort(value)

    @Slot(int)
    def openLibraryItem(self, item_index: int) -> None:
        self.library.open_item(item_index)

    @Slot("QVariantList")
    def addLocalFiles(self, values) -> None:
        self.library.add_local_files(list(values or []))

    @Slot(str)
    def removeLocalItem(self, item_id: str) -> None:
        self.library.remove_local_item(item_id)

    @Slot(str)
    def createLocalPlaylist(self, title: str) -> None:
        self.library.create_local_playlist(title)

    @Slot("QVariantList")
    def addFilesToCurrentLocalPlaylist(self, values) -> None:
        playlist = self.library.current_local_playlist()
        if playlist and playlist.id is not None:
            self.library.add_local_files(list(values or []), playlist.id)

    @Slot(str)
    def renameCurrentLocalPlaylist(self, title: str) -> None:
        self.library.rename_current_playlist(title)

    @Slot()
    def deleteCurrentLocalPlaylist(self) -> None:
        self.library.delete_current_playlist()

    @Slot(int, int)
    def moveCurrentLocalPlaylistItem(self, index: int, direction: int) -> None:
        self.library.move_current_playlist_item(index, direction)

    @Slot(int)
    def removeCurrentLocalPlaylistItem(self, index: int) -> None:
        self.library.remove_current_playlist_item(index)

    @Slot(str)
    def requestSearchSuggestions(self, query: str) -> None:
        self.catalog.request_suggestions(query)

    @Slot()
    def clearSearchSuggestions(self) -> None:
        self.catalog.clear_suggestions()

    @Slot(str)
    def search(self, query: str) -> None:
        self.catalog.search(query)

    @Slot(int, int)
    def openSearchItem(self, group_index: int, item_index: int) -> None:
        self.catalog.open_search_item(group_index, item_index)

    @Slot(int)
    def loadMoreSearch(self, group_index: int) -> None:
        self.catalog.load_more_search(group_index)

    @Slot(int, int)
    def openHomeItem(self, section_index: int, item_index: int) -> None:
        self.catalog.open_home_item(section_index, item_index)

    @Slot(int)
    def playHomeSection(self, section_index: int) -> None:
        self.catalog.play_home_section(section_index)

    @Slot(int)
    def playDetailTrack(self, index: int) -> None:
        self.catalog.play_detail_track(index)

    @Slot()
    def playDetailAll(self) -> None:
        self.catalog.play_detail_all()

    @Slot()
    def shuffleDetail(self) -> None:
        tracks = list(self.catalog.detail_tracks)
        if not tracks:
            return
        random.shuffle(tracks)
        self.playback.play_queue(tracks, 0)

    @Slot(int, int)
    def openDetailSectionItem(self, section_index: int, item_index: int) -> None:
        self.catalog.open_detail_section_item(section_index, item_index)

    @Slot(int)
    def playDetailSection(self, section_index: int) -> None:
        self.catalog.play_detail_section(section_index)

    @Slot(int)
    def expandDetailSection(self, section_index: int) -> None:
        self.catalog.expand_detail_section(section_index)

    @Slot()
    def toggleDetailSaved(self) -> None:
        item = self.catalog.detail_item
        if item and item.kind in {"albums", "playlists"}:
            self.mutations.set_collection_saved(
                item,
                self.catalog.detail_tracks,
                not self.detailSaved,
            )

    @Slot()
    def toggleArtistSubscription(self) -> None:
        item = self.catalog.detail_item
        if item and item.kind == "artists":
            self.mutations.set_artist_subscribed(item, not self.detailArtistSubscribed)

    @Slot(str)
    def createRemotePlaylist(self, title: str) -> None:
        self.mutations.create_playlist(title)

    @Slot(str)
    def renameCurrentRemotePlaylist(self, title: str) -> None:
        item = self.catalog.detail_item
        if not item or item.kind != "playlists":
            return
        self.mutations.rename_playlist(
            item,
            title,
            refresh_detail=lambda: self.catalog.open_detail(item),
        )

    @Slot()
    def deleteCurrentRemotePlaylist(self) -> None:
        item = self.catalog.detail_item
        if not item or item.kind != "playlists":
            return
        self.mutations.delete_playlist(item, self.catalog.clear_detail)

    @Slot(str, int)
    def addItemToPlaylist(self, item_id: str, choice_index: int) -> None:
        item = self._find_item(item_id)
        choices = self.playlistChoices
        if item is None or not 0 <= choice_index < len(choices):
            return
        choice = choices[choice_index]
        if choice["source"] == "remote":
            playlist = next(
                (
                    value
                    for value in self.catalog.library.get("playlists", [])
                    if value.id == choice["id"]
                ),
                None,
            )
            if playlist:
                self.mutations.add_to_playlist(playlist, item)
            return
        try:
            playlist_id = int(choice["id"])
        except (TypeError, ValueError):
            return
        playlist = self.storage.get_local_playlist(playlist_id)
        if playlist and all(value.id != item.id for value in playlist.items):
            playlist.items.append(item)
            self.storage.save_local_playlist(playlist)
            self.libraryChanged.emit()
            self._set_status(f"Adicionada a {playlist.title}.")

    @Slot(int)
    def removeDetailTrackFromPlaylist(self, index: int) -> None:
        collection = self.catalog.detail_item
        if (
            not collection
            or collection.kind != "playlists"
            or not 0 <= index < len(self.catalog.detail_tracks)
        ):
            return
        track = self.catalog.detail_tracks[index]
        if not track.set_video_id:
            return
        self.mutations.remove_from_playlist(
            collection,
            track,
            lambda: self.catalog.open_detail(collection),
        )

    @Slot(str, int)
    def openExploreDestination(self, group: str, index: int) -> None:
        self.catalog.open_explore_destination(group, index)

    @Slot()
    def resetExplore(self) -> None:
        self.catalog.reset_explore()

    @Slot(int, int)
    def openExploreItem(self, section_index: int, item_index: int) -> None:
        self.catalog.open_explore_item(section_index, item_index)

    @Slot(int)
    def playExploreSection(self, section_index: int) -> None:
        self.catalog.play_explore_section(section_index)

    @Slot()
    def togglePlayback(self) -> None:
        self.playback.toggle_playback()

    @Slot()
    def stopPlayback(self) -> None:
        self.playback.stop()

    @Slot()
    def next(self) -> None:
        self.playback.next()

    @Slot()
    def previous(self) -> None:
        self.playback.previous()

    @Slot()
    def toggleShuffle(self) -> None:
        self.playback.toggle_shuffle()

    @Slot()
    def toggleRepeat(self) -> None:
        self.playback.toggle_repeat()

    @Slot()
    def toggleAutoplay(self) -> None:
        self.playback.toggle_autoplay()

    @Slot(int, bool)
    def promoteRelated(self, index: int, play_next: bool) -> None:
        self.playback.promote_related(index, play_next)

    @Slot(int)
    def selectQueueItem(self, index: int) -> None:
        self.playback.select_queue_item(index)

    @Slot(int, int)
    def moveQueueItem(self, index: int, direction: int) -> None:
        self.playback.move_queue_item(index, direction)

    @Slot(int)
    def removeQueueItem(self, index: int) -> None:
        self.playback.remove_queue_item(index)

    @Slot(int)
    def seek(self, position_ms: int) -> None:
        self.playback.seek(position_ms)

    @Slot(int)
    def setVolume(self, value: int) -> None:
        self.playback.set_volume(value)

    @Slot()
    def refreshHistory(self) -> None:
        self.history.refresh()

    @Slot(bool)
    def setHistoryEnabled(self, enabled: bool) -> None:
        self.history.set_enabled(enabled)

    @Slot()
    def clearLocalHistory(self) -> None:
        self.history.clear_local()

    @Slot(int)
    def removeHistoryItem(self, index: int) -> None:
        self.history.remove_item(index)

    @Slot(int)
    def playHistoryItem(self, index: int) -> None:
        self.history.play_item(index)

    @Slot()
    def refreshInsights(self) -> None:
        self.history.refresh_insights()

    @Slot(int)
    def playInsightTrack(self, index: int) -> None:
        self.history.play_insight_track(index)

    @Slot()
    def loadLyrics(self) -> None:
        self.lyrics.load(force=False)

    @Slot()
    def reloadLyrics(self) -> None:
        self.lyrics.load(force=True)

    @Slot(str)
    def setLyricsProvider(self, provider: str) -> None:
        self.lyrics.set_provider(provider)

    @Slot()
    def cycleLyricsProvider(self) -> None:
        self.lyrics.cycle_provider()

    @Slot(int)
    def changeLyricsOffset(self, delta: int) -> None:
        self.lyrics.change_offset(delta)

    @Slot(int)
    def setLyricsOffset(self, value: int) -> None:
        self.lyrics.set_offset(value)

    @Slot(int)
    def seekLyric(self, start_ms: int) -> None:
        self.playback.seek(self.lyrics.seek_target(start_ms))

    @Slot()
    def copyLyrics(self) -> None:
        self.lyrics.copy()

    @Slot()
    def translateLyrics(self) -> None:
        self.lyrics.translate()

    def _find_item(self, item_id: str) -> LibraryItem | None:
        return self.catalog.find_item(item_id) or self.playback.find_item(item_id)

    @Slot(str)
    def toggleLike(self, item_id: str) -> None:
        item = self._find_item(item_id)
        if item:
            self.mutations.set_song_liked(item, item_id not in self._liked_ids())

    @Slot(str)
    def downloadItem(self, item_id: str) -> None:
        item = self._find_item(item_id)
        if item:
            self.downloads.start(item)
            self._set_status(f"Download de {item.title} iniciado.")

    @Slot()
    def downloadDetail(self) -> None:
        playable = [
            item
            for item in self.catalog.detail_tracks
            if item.kind in {"songs", "videos"} and not item.id.startswith("local:")
        ]
        for item in playable:
            self.downloads.start(item)
        if playable:
            self._set_status("Downloads da coleção iniciados.")

    @Slot(int)
    def playDownload(self, index: int) -> None:
        if 0 <= index < len(self._downloads) and self._downloads[index].status == "completed":
            self.playback.play_queue([self._downloads[index].item], 0)

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
    def validateDownloads(self) -> None:
        self.settings.validate_downloads()

    @Slot()
    def _reload_downloads(self) -> None:
        self._downloads = self.storage.load_downloads()
        self.downloadsChanged.emit()
        self.libraryChanged.emit()

    @Slot(str)
    def setQuality(self, value: str) -> None:
        self.settings.set_quality(value)

    @Slot(str, str)
    def setLocale(self, language: str, region: str) -> None:
        self.settings.set_locale(language, region)

    @Slot(str)
    def setProxy(self, value: str) -> None:
        self.settings.set_proxy(value)

    @Slot(bool)
    def setNormalization(self, value: bool) -> None:
        self.settings.set_audio_value("normalization", value)

    @Slot(str)
    def setEqualizer(self, value: str) -> None:
        self.settings.set_audio_value("equalizer", value)

    @Slot(float)
    def setPlaybackSpeed(self, value: float) -> None:
        self.settings.set_audio_value("speed", value)

    @Slot(float)
    def setPitch(self, value: float) -> None:
        self.settings.set_audio_value("pitch", value)

    @Slot(bool)
    def setSkipSilence(self, value: bool) -> None:
        self.settings.set_audio_value("skip_silence", value)

    @Slot()
    def clearArtworkCache(self) -> None:
        self.settings.clear_cache()

    @Slot()
    def validateAccount(self) -> None:
        self.settings.validate_account()

    @Slot(str)
    def exportBackup(self, path: str) -> None:
        self.settings.export_backup(self._local_path(path))

    @Slot(str)
    def restoreBackup(self, path: str) -> None:
        self.settings.restore_backup(self._local_path(path))

    @Slot(int)
    def setSleepTimer(self, minutes: int) -> None:
        self.settings.set_sleep_timer(minutes)

    @staticmethod
    def _local_path(value: str) -> str:
        if value.startswith("file://"):
            from urllib.parse import unquote, urlparse

            return unquote(urlparse(value).path)
        return str(Path(value).expanduser())

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
                self._sessionReady.emit(
                    bool(ok),
                    "" if ok else "Cookie inválido ou incompleto",
                )
            except Exception as exc:
                LOGGER.exception("Qt session connection failed")
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
        self.catalog.library = {}
        self.catalog.home = []
        self.catalog.explore = ExploreData([], [], [])
        self.catalog.explore_display = self.catalog.explore
        self.catalog.explore_title = "Explorar"
        self.catalog.libraryChanged.emit()
        self.catalog.homeChanged.emit()
        self.catalog.exploreChanged.emit()
        self._set_status("Conta desconectada.")

    @Slot()
    def shutdown(self) -> None:
        self.mpris.close()
        self.playback.shutdown()
        self._executor.shutdown(wait=False, cancel_futures=True)
