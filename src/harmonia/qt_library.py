from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

from PySide6.QtCore import QObject, Signal

from .models import LibraryItem, LocalPlaylist
from .qt_catalog import QtCatalogController
from .storage import Storage

ORIGINS = (
    ("youtube", "YouTube Music"),
    ("uploads", "Uploads"),
    ("downloads", "Downloads"),
    ("local", "Arquivos locais"),
    ("podcasts", "Podcasts"),
)
FILTERS = (
    ("albums", "Álbuns"),
    ("artists", "Artistas"),
    ("songs", "Músicas"),
    ("playlists", "Playlists"),
)


class QtLibraryController(QObject):
    """Library presentation state shared by the Qt pages.

    Remote data remains owned by ``QtCatalogController`` and persistence by
    ``Storage``. This controller only decides which existing source/category is
    visible and performs local-library operations, avoiding a second library
    cache or remote-service implementation.
    """

    changed = Signal()
    detailChanged = Signal()

    def __init__(
        self,
        storage: Storage,
        catalog: QtCatalogController,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.storage = storage
        self.catalog = catalog
        self.origin = "youtube"
        self.category = "albums"
        self.sort = "recent"
        self.catalog.libraryChanged.connect(self.changed.emit)

    @property
    def origins(self) -> list[dict[str, str]]:
        return [{"key": key, "label": label} for key, label in ORIGINS]

    @property
    def filters(self) -> list[dict[str, str]]:
        supported = {"songs", "playlists"} if self.origin in {"downloads", "local", "podcasts"} else {
            "albums",
            "artists",
            "songs",
            "playlists",
        }
        if self.origin == "uploads":
            supported = {"albums", "songs"}
        return [
            {"key": key, "label": label}
            for key, label in FILTERS
            if key in supported
        ]

    @property
    def description(self) -> str:
        if self.origin != "youtube":
            return {
                "uploads": "Músicas enviadas à sua conta do YouTube Music.",
                "downloads": "Conteúdo disponível para reprodução offline.",
                "local": "Arquivos e playlists armazenados neste computador.",
                "podcasts": "Programas e episódios salvos na sua conta.",
            }[self.origin]
        return {
            "albums": "Álbuns e EPs salvos na sua coleção.",
            "artists": "Artistas que você acompanha.",
            "songs": "Todas as músicas marcadas como favoritas.",
            "playlists": "Playlists salvas na sua conta.",
        }[self.category]

    def _normalize_category(self) -> None:
        supported = {entry["key"] for entry in self.filters}
        if self.category in supported:
            return
        self.category = "songs" if "songs" in supported else next(iter(supported), "albums")

    def set_origin(self, origin: str) -> None:
        if origin not in {key for key, _label in ORIGINS} or origin == self.origin:
            return
        self.origin = origin
        self._normalize_category()
        self.changed.emit()

    def set_category(self, category: str) -> None:
        if category not in {entry["key"] for entry in self.filters} or category == self.category:
            return
        self.category = category
        self.changed.emit()

    def set_sort(self, sort: str) -> None:
        if sort not in {"recent", "title"} or sort == self.sort:
            return
        self.sort = sort
        self.changed.emit()

    def items(self) -> list[LibraryItem]:
        library = self.catalog.library
        if self.origin == "youtube":
            items = list(library.get(self.category, []))
        elif self.origin == "uploads":
            key = "uploaded-albums" if self.category == "albums" else "uploads"
            items = list(library.get(key, [])) if self.category in {"albums", "songs"} else []
        elif self.origin == "downloads":
            items = (
                [record.item for record in self.storage.load_downloads() if record.status == "completed"]
                if self.category == "songs"
                else []
            )
        elif self.origin == "local":
            if self.category == "songs":
                items = self.storage.load_local_media()
            elif self.category == "playlists":
                items = [self._playlist_item(playlist) for playlist in self.storage.load_local_playlists()]
            else:
                items = []
        else:
            if self.category == "songs":
                items = [
                    item
                    for item in library.get("podcast-episodes", [])
                    if item.kind == "songs"
                ]
            elif self.category == "playlists":
                items = list(library.get("podcasts", []))
            else:
                items = []
        if self.sort == "title":
            items.sort(key=lambda item: item.title.casefold())
        return items

    @staticmethod
    def _playlist_item(playlist: LocalPlaylist) -> LibraryItem:
        return LibraryItem(
            f"local-playlist:{playlist.id}",
            playlist.title,
            f"{len(playlist.items)} faixas",
            kind="local-playlists",
        )

    def open_item(self, index: int) -> None:
        items = self.items()
        if not 0 <= index < len(items):
            return
        item = items[index]
        if item.kind == "local-playlists":
            try:
                playlist_id = int(item.id.split(":", 1)[1])
            except (IndexError, ValueError):
                return
            playlist = self.storage.get_local_playlist(playlist_id)
            if playlist:
                self.catalog.show_local_playlist(playlist)
                self.detailChanged.emit()
            return
        self.catalog.open_or_play(items, index)

    @staticmethod
    def _local_path(value: str) -> str:
        if value.startswith("file:"):
            parsed = urlparse(value)
            return unquote(parsed.path)
        return value

    def add_local_files(self, values: list[str], playlist_id: int | None = None) -> None:
        paths = [self._local_path(value) for value in values]
        items = self.storage.add_local_files([path for path in paths if Path(path).is_file()])
        if playlist_id is not None:
            playlist = self.storage.get_local_playlist(playlist_id)
            if playlist:
                known = {item.id for item in playlist.items}
                playlist.items.extend(item for item in items if item.id not in known)
                self.storage.save_local_playlist(playlist)
                self.catalog.show_local_playlist(playlist)
                self.detailChanged.emit()
        self.changed.emit()

    def remove_local_item(self, item_id: str) -> None:
        self.storage.remove_local_media(item_id)
        self.changed.emit()

    def create_local_playlist(self, title: str) -> None:
        title = title.strip()
        if not title:
            return
        playlist_id = self.storage.create_local_playlist(title)
        playlist = self.storage.get_local_playlist(playlist_id)
        if playlist:
            self.origin = "local"
            self.category = "playlists"
            self.changed.emit()
            self.catalog.show_local_playlist(playlist)
            self.detailChanged.emit()

    def current_local_playlist(self) -> LocalPlaylist | None:
        item = self.catalog.detail_item
        if item is None or item.kind != "local-playlists":
            return None
        try:
            playlist_id = int(item.id.split(":", 1)[1])
        except (IndexError, ValueError):
            return None
        return self.storage.get_local_playlist(playlist_id)

    def rename_current_playlist(self, title: str) -> None:
        playlist = self.current_local_playlist()
        title = title.strip()
        if not playlist or not title:
            return
        playlist.title = title
        self.storage.save_local_playlist(playlist)
        self.catalog.show_local_playlist(playlist)
        self.changed.emit()
        self.detailChanged.emit()

    def delete_current_playlist(self) -> None:
        playlist = self.current_local_playlist()
        if not playlist or playlist.id is None:
            return
        self.storage.delete_local_playlist(playlist.id)
        self.origin = "local"
        self.category = "playlists"
        self.catalog.clear_detail()
        self.changed.emit()
        self.detailChanged.emit()

    def move_current_playlist_item(self, index: int, direction: int) -> None:
        playlist = self.current_local_playlist()
        if not playlist:
            return
        target = index + direction
        if not (0 <= index < len(playlist.items) and 0 <= target < len(playlist.items)):
            return
        playlist.items[index], playlist.items[target] = playlist.items[target], playlist.items[index]
        self.storage.save_local_playlist(playlist)
        self.catalog.show_local_playlist(playlist)
        self.detailChanged.emit()

    def remove_current_playlist_item(self, index: int) -> None:
        playlist = self.current_local_playlist()
        if not playlist or not 0 <= index < len(playlist.items):
            return
        playlist.items.pop(index)
        self.storage.save_local_playlist(playlist)
        self.catalog.show_local_playlist(playlist)
        self.detailChanged.emit()
