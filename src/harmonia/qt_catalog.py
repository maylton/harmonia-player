from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal

from .models import ArtistPage, ExploreData, LibraryItem, SearchResults
from .qt_presenters import section_map, unique_items
from .services import YouTubeMusicService
from .storage import Storage

LOGGER = logging.getLogger(__name__)


class QtCatalogController(QObject):
    """Home, Explore, Search and remote-detail state for the Qt frontend."""

    homeChanged = Signal()
    libraryChanged = Signal()
    searchChanged = Signal()
    suggestionsChanged = Signal()
    exploreChanged = Signal()
    detailChanged = Signal()

    _syncReady = Signal(object, object, object, str)
    _searchReady = Signal(int, object, str)
    _suggestionsReady = Signal(int, str, object)
    _searchMoreReady = Signal(int, int, object, str)
    _detailReady = Signal(int, object, object, str)
    _detailSectionReady = Signal(int, int, object, str)
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
        self.search_results = SearchResults("", [])
        self.search_suggestions: list[str] = []

        self.detail_item: LibraryItem | None = None
        self.detail_tracks: list[LibraryItem] = []
        self.detail_sections: list[dict] = []
        self.detail_section_items: list[list[LibraryItem]] = []
        self.detail_artist_sections = []
        self.detail_description = ""
        self.detail_subscribers = ""
        self.detail_is_artist = False

        self._search_request = 0
        self._suggestion_request = 0
        self._detail_request = 0
        self._detail_section_request = 0
        self._discovery_request = 0

        self._syncReady.connect(self._apply_sync)
        self._searchReady.connect(self._apply_search)
        self._suggestionsReady.connect(self._apply_suggestions)
        self._searchMoreReady.connect(self._apply_search_more)
        self._detailReady.connect(self._apply_detail)
        self._detailSectionReady.connect(self._apply_detail_section)
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
        self.homeChanged.emit()
        self.libraryChanged.emit()
        self.exploreChanged.emit()
        self.detailChanged.emit()
        self.set_status("")

    def request_suggestions(self, query: str) -> None:
        query = query.strip()
        self._suggestion_request += 1
        request_id = self._suggestion_request
        if len(query) < 2:
            self.search_suggestions = []
            self.suggestionsChanged.emit()
            return

        def worker() -> None:
            try:
                suggestions = self.youtube.suggestions(query)
            except Exception:
                suggestions = []
            self._suggestionsReady.emit(request_id, query, suggestions)

        self.executor.submit(worker)

    def _apply_suggestions(self, request_id: int, _query: str, suggestions) -> None:
        if request_id != self._suggestion_request:
            return
        self.search_suggestions = list(suggestions or [])[:8]
        self.suggestionsChanged.emit()

    def clear_suggestions(self) -> None:
        self._suggestion_request += 1
        if self.search_suggestions:
            self.search_suggestions = []
            self.suggestionsChanged.emit()

    def search(self, query: str) -> None:
        query = query.strip()
        self._search_request += 1
        request_id = self._search_request
        self.clear_suggestions()
        if not query:
            self.search_results = SearchResults("", [])
            self.searchChanged.emit()
            return
        self.set_busy(True)
        self.set_status(f"Pesquisando por “{query}”…")

        def worker() -> None:
            try:
                result = self.youtube.universal_search(query)
                self._searchReady.emit(request_id, result, "")
            except Exception as exc:
                LOGGER.exception("Qt search failed")
                self._searchReady.emit(request_id, SearchResults(query, []), str(exc))

        self.executor.submit(worker)

    def _apply_search(self, request_id: int, results, error: str) -> None:
        if request_id != self._search_request:
            return
        self.set_busy(False)
        if error:
            self.set_status(f"Falha na pesquisa: {error}")
            return
        self.search_results = results or SearchResults("", [])
        self.searchChanged.emit()
        if self.search_results.errors:
            self.set_status("Algumas categorias da busca não puderam ser carregadas.")
        else:
            self.set_status("")

    def open_search_item(self, group_index: int, item_index: int) -> None:
        if not 0 <= group_index < len(self.search_results.groups):
            return
        group = self.search_results.groups[group_index]
        self.open_or_play(group.items, item_index)

    def load_more_search(self, group_index: int) -> None:
        if not 0 <= group_index < len(self.search_results.groups):
            return
        group = self.search_results.groups[group_index]
        if not group.continuation:
            return
        request_id = self._search_request
        query = self.search_results.query
        self.set_status(f"Carregando mais {group.title.lower()}…")

        def worker() -> None:
            try:
                incoming = self.youtube.search_more(query, group)
                self._searchMoreReady.emit(request_id, group_index, incoming, "")
            except Exception as exc:
                LOGGER.exception("Qt search continuation failed")
                self._searchMoreReady.emit(request_id, group_index, None, str(exc))

        self.executor.submit(worker)

    def _apply_search_more(self, request_id: int, group_index: int, incoming, error: str) -> None:
        if request_id != self._search_request or not 0 <= group_index < len(self.search_results.groups):
            return
        if error or incoming is None:
            self.set_status(f"Não foi possível carregar mais resultados: {error}")
            return
        group = self.search_results.groups[group_index]
        known = {item.id for item in group.items}
        group.items.extend(item for item in incoming.items if item.id not in known)
        group.continuation = incoming.continuation
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
        self.detail_artist_sections = []
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
            self.detail_artist_sections = [section for section in (artist.sections or []) if section.items]
            self.detail_section_items = [list(section.items) for section in self.detail_artist_sections]
            self.detail_sections = []
            for section in self.detail_artist_sections:
                mapped = self.section(section.title, section.items)
                mapped["canExpand"] = bool(section.browse_id)
                self.detail_sections.append(mapped)
        else:
            tracks = list(payload or [])
            for track in tracks:
                if not track.thumbnail and item.thumbnail:
                    track.thumbnail = item.thumbnail
            self.detail_item = item
            self.detail_tracks = tracks
            self.detail_sections = []
            self.detail_section_items = []
            self.detail_artist_sections = []
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

    def expand_detail_section(self, section_index: int) -> None:
        if not 0 <= section_index < len(self.detail_artist_sections):
            return
        section = self.detail_artist_sections[section_index]
        if not section.browse_id:
            return
        self._detail_section_request += 1
        request_id = self._detail_section_request
        self.set_status(f"Carregando {section.title}…")

        def worker() -> None:
            try:
                items = self.youtube.artist_section(section)
                self._detailSectionReady.emit(request_id, section_index, items, "")
            except Exception as exc:
                LOGGER.exception("Qt artist section failed")
                self._detailSectionReady.emit(request_id, section_index, None, str(exc))

        self.executor.submit(worker)

    def _apply_detail_section(self, request_id: int, section_index: int, items, error: str) -> None:
        if request_id != self._detail_section_request or not 0 <= section_index < len(self.detail_sections):
            return
        if error or items is None:
            self.set_status(f"Não foi possível carregar a seção: {error}")
            return
        values = list(items)
        self.detail_section_items[section_index] = values
        title = self.detail_artist_sections[section_index].title
        mapped = self.section(title, values, limit=max(24, len(values)))
        mapped["canExpand"] = False
        self.detail_sections[section_index] = mapped
        self.detailChanged.emit()
        self.set_status("")

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
        groups: list[list[LibraryItem]] = [self.detail_tracks, *self.library.values()]
        groups.extend(group.items for group in self.search_results.groups)
        groups.extend(section.items for section in self.home)
        groups.extend(section.items for section in self.explore.sections)
        groups.extend(section.items for section in self.explore_display.sections)
        for group in groups:
            for item in group:
                if item.id == item_id:
                    return item
        return None
