from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from PySide6.QtCore import QObject, Signal

from .models import ArtistPage, ExploreData, LibraryItem
from .qt_presenters import section_map, unique_items
from .services import YouTubeMusicService
from .storage import Storage

LOGGER = logging.getLogger(__name__)


class QtCatalogController(QObject):
    homeChanged = Signal()
    libraryChanged = Signal()
    searchChanged = Signal()
    exploreChanged = Signal()
    detailChanged = Signal()

    _syncReady = Signal(object, object, object, str)
    _searchReady = Signal(int, object, str)
    _detailReady = Signal(int, object, object, str)
    _discoveryReady = Signal(int, object, object, str)

    def __init__(
        self,
        storage: Storage,
        youtube: YouTubeMusicService,
        executor: ThreadPoolExecutor,
        set_busy: Callable[[bool], None],
        set_status: Callable[[str], None],
        play_queue: Callable[[list[LibraryItem], int], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.storage = storage
        self.youtube = youtube
        self.executor = executor
        self.set_busy = set_busy
        self.set_status = set_status
        self.play_queue = play_queue

        self.home = self.storage.load_home()
        self.library = self.storage.load_library()
        self.explore = self.storage.load_explore()
        self.explore_display = self.explore
        self.explore_title = "Explorar"
        self.search_items: list[LibraryItem] = []
        self.current_library_category = next(iter(self.library), "songs")

        self.detail_item: LibraryItem | None = None
        self.detail_tracks: list[LibraryItem] = []
        self.detail_sections: list[dict] = []
        self.detail_section_items: list[list[LibraryItem]] = []
        self.detail_description = ""
        self.detail_subscribers = ""
        self.detail_is_artist = False

        self._search_request = 0
        self._detail_request = 0
        self._discovery_request = 0

        self._syncReady.connect(self._apply_sync)
        self._searchReady.connect(self._apply_search)
        self._detailReady.connect(self._apply_detail)
        self._discoveryReady.connect(self._apply_discovery)

    def liked_ids(self) -> set[str]:
        return {item.id for item in self.library.get("songs", [])}

    def section(self, title: str, items: list[LibraryItem], limit: int = 12) -> dict:
        return section_map(title, items, self.liked_ids(), limit=limit)

    def sync_all(self) -> None:
        self.set_busy(True)
        self.set_status("Sincronizando biblioteca, Início e Explorar…")

        def worker() -> None:
            try:
                library = self.youtube.sync_library()
                home = self.youtube.sync_home()
                explore = self.youtube.sync_explore()
                self._syncReady.emit(library, home, explore, "")
            except Exception as exc:
                LOGGER.exception("Qt sync failed")
                self._syncReady.emit(None, None, None, str(exc))

        self.executor.submit(worker)

    def _apply_sync(self, library, home, explore, error: str) -> None:
        self.set_busy(False)
        if error:
            self.set_status(f"Não foi possível sincronizar: {error}")
            return
        self.library = library or {}
        self.home = home or []
        self.explore = explore or ExploreData([], [], [])
        self.explore_display = self.explore
        self.explore_title = "Explorar"
        if self.current_library_category not in self.library:
            self.current_library_category = next(iter(self.library), "songs")
        self.homeChanged.emit()
        self.libraryChanged.emit()
        self.exploreChanged.emit()
        self.detailChanged.emit()
        self.set_status("")

    def set_library_category(self, category: str) -> None:
        if category == self.current_library_category or category not in self.library:
            return
        self.current_library_category = category
        self.libraryChanged.emit()

    def search(self, query: str) -> None:
        query = query.strip()
        self._search_request += 1
        request_id = self._search_request
        if not query:
            self.search_items = []
            self.searchChanged.emit()
            return
        self.set_busy(True)
        self.set_status(f"Pesquisando por “{query}”…")

        def worker() -> None:
            try:
                result = self.youtube.universal_search(query)
                items: list[LibraryItem] = []
                seen: set[tuple[str, str]] = set()
                for group in result.groups:
                    for item in group.items:
                        key = (item.kind, item.id)
                        if key in seen:
                            continue
                        seen.add(key)
                        items.append(item)
                self._searchReady.emit(request_id, items, "")
            except Exception as exc:
                LOGGER.exception("Qt search failed")
                self._searchReady.emit(request_id, [], str(exc))

        self.executor.submit(worker)

    def _apply_search(self, request_id: int, items, error: str) -> None:
        if request_id != self._search_request:
            return
        self.set_busy(False)
        if error:
            self.set_status(f"Falha na pesquisa: {error}")
            return
        self.search_items = list(items or [])
        self.searchChanged.emit()
        self.set_status("")

    def home_items(self, section_index: int) -> list[LibraryItem]:
        if not 0 <= section_index < len(self.home):
            return []
        unique = unique_items(self.home[section_index].items)
        song_section = bool(unique) and all(item.kind == "songs" for item in unique)
        return unique[: 24 if song_section else 12]

    def open_home_item(self, section_index: int, item_index: int) -> None:
        self.open_or_play(self.home_items(section_index), item_index)

    def play_home_section(self, section_index: int) -> None:
        items = [item for item in self.home_items(section_index) if item.kind == "songs"]
        if items:
            self.play_queue(items, 0)

    def open_library_item(self, item_index: int) -> None:
        self.open_or_play(self.library.get(self.current_library_category, []), item_index)

    def open_search_item(self, item_index: int) -> None:
        self.open_or_play(self.search_items, item_index)

    def open_or_play(self, items: list[LibraryItem], index: int) -> None:
        if not 0 <= index < len(items):
            return
        selected = items[index]
        if selected.kind in {"songs", "videos"}:
            playable = [item for item in items if item.kind in {"songs", "videos"}]
            selected_index = playable.index(selected) if selected in playable else 0
            self.play_queue(playable, selected_index)
        else:
            self.open_detail(selected)

    def open_detail(self, item: LibraryItem) -> None:
        self._detail_request += 1
        request_id = self._detail_request
        self.detail_item = item
        self.detail_tracks = []
        self.detail_sections = []
        self.detail_section_items = []
        self.detail_description = ""
        self.detail_subscribers = ""
        self.detail_is_artist = item.kind == "artists"
        self.detailChanged.emit()
        self.set_busy(True)
        self.set_status(f"Carregando {item.title}…")

        def worker() -> None:
            try:
                payload = self.youtube.artist(item.id) if item.kind == "artists" else self.youtube.browse(item)
                self._detailReady.emit(request_id, item, payload, "")
            except Exception as exc:
                LOGGER.exception("Qt detail failed")
                self._detailReady.emit(request_id, item, None, str(exc))

        self.executor.submit(worker)

    def _apply_detail(self, request_id: int, item, payload, error: str) -> None:
        if request_id != self._detail_request:
            return
        self.set_busy(False)
        if error or payload is None:
            self.set_status(f"Não foi possível abrir {item.title}: {error}")
            self.detailChanged.emit()
            return

        if isinstance(payload, ArtistPage):
            artist = payload
            self.detail_item = LibraryItem(
                item.id,
                artist.title,
                artist.subscribers or item.subtitle,
                artist.thumbnail or item.thumbnail,
                "artists",
            )
            self.detail_tracks = list(artist.songs)
            self.detail_description = artist.description
            self.detail_subscribers = artist.subscribers
            self.detail_is_artist = True
            artist_sections = [section for section in (artist.sections or []) if section.items]
            self.detail_section_items = [list(section.items) for section in artist_sections]
            self.detail_sections = [self.section(section.title, section.items) for section in artist_sections]
        else:
            tracks = list(payload or [])
            for track in tracks:
                if not track.thumbnail and item.thumbnail:
                    track.thumbnail = item.thumbnail
            self.detail_item = item
            self.detail_tracks = tracks
            self.detail_sections = []
            self.detail_section_items = []
            self.detail_description = ""
            self.detail_subscribers = ""
            self.detail_is_artist = False

        self.detailChanged.emit()
        self.set_status("")

    def play_detail_track(self, index: int) -> None:
        if 0 <= index < len(self.detail_tracks):
            self.play_queue(self.detail_tracks, index)

    def play_detail_all(self) -> None:
        if self.detail_tracks:
            self.play_queue(self.detail_tracks, 0)

    def open_detail_section_item(self, section_index: int, item_index: int) -> None:
        if not 0 <= section_index < len(self.detail_section_items):
            return
        self.open_or_play(self.detail_section_items[section_index], item_index)

    def play_detail_section(self, section_index: int) -> None:
        if not 0 <= section_index < len(self.detail_section_items):
            return
        items = [item for item in self.detail_section_items[section_index] if item.kind in {"songs", "videos"}]
        if items:
            self.play_queue(items, 0)

    def open_explore_destination(self, group: str, index: int) -> None:
        values = self.explore_display.shortcuts if group == "shortcuts" else self.explore_display.genres
        if not 0 <= index < len(values):
            return
        destination = values[index]
        self._discovery_request += 1
        request_id = self._discovery_request
        self.set_busy(True)
        self.set_status(f"Carregando {destination.title}…")

        def worker() -> None:
            try:
                data = self.youtube.discovery(destination)
                self._discoveryReady.emit(request_id, destination, data, "")
            except Exception as exc:
                LOGGER.exception("Qt discovery failed")
                self._discoveryReady.emit(request_id, destination, None, str(exc))

        self.executor.submit(worker)

    def _apply_discovery(self, request_id: int, destination, data, error: str) -> None:
        if request_id != self._discovery_request:
            return
        self.set_busy(False)
        if error or data is None:
            self.set_status(f"Não foi possível abrir {destination.title}: {error}")
            return
        self.explore_display = data
        self.explore_title = destination.title
        self.exploreChanged.emit()
        self.set_status("")

    def reset_explore(self) -> None:
        if self.explore_display is self.explore:
            return
        self.explore_display = self.explore
        self.explore_title = "Explorar"
        self.exploreChanged.emit()

    def explore_items(self, section_index: int) -> list[LibraryItem]:
        if not 0 <= section_index < len(self.explore_display.sections):
            return []
        unique = unique_items(self.explore_display.sections[section_index].items)
        song_section = bool(unique) and all(item.kind == "songs" for item in unique)
        return unique[: 24 if song_section else 12]

    def open_explore_item(self, section_index: int, item_index: int) -> None:
        self.open_or_play(self.explore_items(section_index), item_index)

    def play_explore_section(self, section_index: int) -> None:
        if not 0 <= section_index < len(self.explore_display.sections):
            return
        items = [item for item in self.explore_display.sections[section_index].items if item.kind == "songs"]
        if items:
            self.play_queue(items, 0)

    def find_item(self, item_id: str) -> LibraryItem | None:
        groups: list[list[LibraryItem]] = [
            self.search_items,
            self.detail_tracks,
            *self.library.values(),
        ]
        groups.extend(section.items for section in self.home)
        groups.extend(section.items for section in self.explore.sections)
        groups.extend(section.items for section in self.explore_display.sections)
        for group in groups:
            for item in group:
                if item.id == item_id:
                    return item
        return None
