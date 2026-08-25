from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from .downloads import DownloadManager
from .models import LibraryItem
from .preferences import Preferences
from .qt_activity import QtHistoryController, QtLyricsController
from .qt_catalog import QtCatalogController
from .qt_playback import QtPlaybackController
from .qt_presenters import (
    CATEGORY_LABELS,
    destination_map,
    history_map,
    insights_map,
    item_map,
)
from .services import YouTubeMusicService
from .storage import Storage

LOGGER = logging.getLogger(__name__)


class HarmoniaQtBackend(QObject):
    """Thin QObject facade exposed to QML.

    Domain logic lives in the catalog, playback and activity controllers. This
    class intentionally owns only cross-domain wiring, authentication,
    downloads and preferences so QML continues to see one stable `backend`.
    """

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

    _downloadsUpdated = Signal()
    _sessionReady = Signal(bool, str)
    _likeReady = Signal(bool, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.storage = Storage()
        self.youtube = YouTubeMusicService(self.storage)
        self.preferences = Preferences.load(self.storage)
        self._executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="harmonia-qt")
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

        self._wire_controllers()
        self._downloadsUpdated.connect(self._reload_downloads)
        self._sessionReady.connect(self._apply_session)
        self._likeReady.connect(self._apply_like)

        if self._logged_in:
            QTimer.singleShot(120, self.syncAll)

    def _wire_controllers(self) -> None:
        self.catalog.homeChanged.connect(self.homeChanged.emit)
        self.catalog.libraryChanged.connect(self._on_library_changed)
        self.catalog.searchChanged.connect(self.searchChanged.emit)
        self.catalog.exploreChanged.connect(self.exploreChanged.emit)
        self.catalog.detailChanged.connect(self.detailChanged.emit)

        self.playback.nowPlayingChanged.connect(self._on_now_playing_changed)
        self.playback.playbackChanged.connect(self.playbackChanged.emit)
        self.playback.positionChanged.connect(self._on_position_changed)
        self.playback.durationChanged.connect(self.durationChanged.emit)
        self.playback.volumeChanged.connect(self.volumeChanged.emit)
        self.playback.queueChanged.connect(self.queueChanged.emit)
        self.playback.autoplayLoadingChanged.connect(self.autoplayLoadingChanged.emit)
        self.playback.trackChanged.connect(self.lyrics.reset)
        self.playback.historyRecorded.connect(self.history.on_history_recorded)

        self.history.historyChanged.connect(self.historyChanged.emit)
        self.history.insightsChanged.connect(self.insightsChanged.emit)
        self.lyrics.lyricsChanged.connect(self.lyricsChanged.emit)
        self.lyrics.lyricPositionChanged.connect(self.lyricPositionChanged.emit)

    def _on_library_changed(self) -> None:
        self.libraryChanged.emit()
        self.currentLikeChanged.emit()
        self.queueChanged.emit()
        self.downloadsChanged.emit()

    def _on_now_playing_changed(self) -> None:
        self.nowPlayingChanged.emit()
        self.currentLikeChanged.emit()

    def _on_position_changed(self) -> None:
        self.positionChanged.emit()
        self.lyrics.update_position(self.playback.position)

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

    @Property("QVariantList", notify=homeChanged)
    def homeSections(self) -> list[dict[str, Any]]:
        return [
            self.catalog.section(section.title, section.items)
            for section in self.catalog.home
            if section.items
        ]

    @Property("QVariantList", notify=libraryChanged)
    def libraryCategories(self) -> list[dict[str, str]]:
        ordered = [key for key in CATEGORY_LABELS if key in self.catalog.library]
        ordered.extend(key for key in self.catalog.library if key not in ordered)
        return [{"key": key, "label": CATEGORY_LABELS.get(key, key.title())} for key in ordered]

    @Property("QVariantList", notify=libraryChanged)
    def libraryItems(self) -> list[dict[str, Any]]:
        liked_ids = self._liked_ids()
        return [
            item_map(item, index=index, liked=item.id in liked_ids)
            for index, item in enumerate(
                self.catalog.library.get(self.catalog.current_library_category, [])
            )
        ]

    @Property(str, notify=libraryChanged)
    def currentLibraryCategory(self) -> str:
        return self.catalog.current_library_category

    @Property("QVariantList", notify=searchChanged)
    def searchItems(self) -> list[dict[str, Any]]:
        liked_ids = self._liked_ids()
        return [
            item_map(item, index=index, liked=item.id in liked_ids)
            for index, item in enumerate(self.catalog.search_items)
        ]

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

    @Property("QVariantList", notify=downloadsChanged)
    def downloadItems(self) -> list[dict[str, Any]]:
        liked_ids = self._liked_ids()
        return [
            {
                **item_map(
                    record.item,
                    index=index,
                    liked=record.item.id in liked_ids,
                ),
                "status": record.status,
                "progress": record.progress,
                "downloadedBytes": record.downloaded_bytes,
                "totalBytes": record.total_bytes,
                "error": record.error,
                "filePath": record.file_path,
            }
            for index, record in enumerate(self._downloads)
        ]

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
    def lyricsProvider(self) -> str:
        return self.lyrics.document.provider if self.lyrics.document else ""

    @Property(bool, notify=lyricsChanged)
    def lyricsLoading(self) -> bool:
        return self.lyrics.loading

    @Property(int, notify=lyricPositionChanged)
    def activeLyricIndex(self) -> int:
        return self.lyrics.active_index

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
    def setLibraryCategory(self, category: str) -> None:
        self.catalog.set_library_category(category)

    @Slot(str)
    def search(self, query: str) -> None:
        self.catalog.search(query)

    @Slot(int, int)
    def openHomeItem(self, section_index: int, item_index: int) -> None:
        self.catalog.open_home_item(section_index, item_index)

    @Slot(int)
    def playHomeSection(self, section_index: int) -> None:
        self.catalog.play_home_section(section_index)

    @Slot(int)
    def openLibraryItem(self, item_index: int) -> None:
        self.catalog.open_library_item(item_index)

    @Slot(int)
    def openSearchItem(self, item_index: int) -> None:
        self.catalog.open_search_item(item_index)

    @Slot(int)
    def playDetailTrack(self, index: int) -> None:
        self.catalog.play_detail_track(index)

    @Slot()
    def playDetailAll(self) -> None:
        self.catalog.play_detail_all()

    @Slot(int, int)
    def openDetailSectionItem(self, section_index: int, item_index: int) -> None:
        self.catalog.open_detail_section_item(section_index, item_index)

    @Slot(int)
    def playDetailSection(self, section_index: int) -> None:
        self.catalog.play_detail_section(section_index)

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

    def _find_item(self, item_id: str) -> LibraryItem | None:
        return self.catalog.find_item(item_id) or self.playback.find_item(item_id)

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
                self._likeReady.emit(True, "")
            except Exception as exc:
                LOGGER.exception("Qt like mutation failed")
                self._likeReady.emit(False, str(exc))

        self._executor.submit(worker)

    @Slot(bool, str)
    def _apply_like(self, ok: bool, error: str) -> None:
        if not ok:
            self._set_status(f"Não foi possível aplicar a alteração: {error}")
            return
        self._set_status("")
        self.syncAll()

    @Slot(str)
    def downloadItem(self, item_id: str) -> None:
        item = self._find_item(item_id)
        if item:
            self.downloads.start(item)
            self._set_status(f"Download de {item.title} iniciado.")

    @Slot()
    def downloadDetail(self) -> None:
        for item in self.catalog.detail_tracks:
            if item.kind in {"songs", "videos"}:
                self.downloads.start(item)
        if self.catalog.detail_tracks:
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
                self._sessionReady.emit(
                    bool(ok),
                    "" if ok else "Cookie inválido ou incompleto",
                )
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

    @Slot()
    def shutdown(self) -> None:
        self.playback.shutdown()
        self._executor.shutdown(wait=False, cancel_futures=True)
