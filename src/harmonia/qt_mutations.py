from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal

from .models import LibraryItem
from .services import YouTubeMusicService
from .storage import Storage

LOGGER = logging.getLogger(__name__)


class QtMutationController(QObject):
    """Remote YouTube Music mutations reused by the Qt presentation layer."""

    changed = Signal()
    _ready = Signal(str, str, bool, str)

    def __init__(
        self,
        storage: Storage,
        youtube: YouTubeMusicService,
        executor: ThreadPoolExecutor,
        set_status: Callable[[str], None],
        sync_library: Callable[[], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.storage = storage
        self.youtube = youtube
        self.executor = executor
        self.set_status = set_status
        self.sync_library = sync_library
        self._success_callbacks: dict[str, Callable[[], None]] = {}
        self._generation = 0
        self._ready.connect(self._apply)

    def _run(
        self,
        action: str,
        target: str,
        operation: Callable[[], object],
        success_message: str,
        on_success: Callable[[], None] | None = None,
    ) -> None:
        self._generation += 1
        token = f"{action}:{self._generation}"
        if on_success:
            self._success_callbacks[token] = on_success
        self.set_status("Enviando alteração ao YouTube Music…")

        def worker() -> None:
            try:
                operation()
                self.storage.log_action(action, target or None, "completed")
                self._ready.emit(token, success_message, True, "")
            except Exception as exc:
                LOGGER.exception("Qt mutation %s failed", action)
                self.storage.log_action(action, target or None, "failed", str(exc))
                self._ready.emit(token, success_message, False, str(exc))

        self.executor.submit(worker)

    def _apply(self, token: str, success_message: str, ok: bool, error: str) -> None:
        callback = self._success_callbacks.pop(token, None)
        if not ok:
            self.set_status(f"Alteração não aplicada: {error}")
            return
        self.set_status(success_message)
        if callback:
            callback()
        self.changed.emit()

    def set_song_liked(self, item: LibraryItem, liked: bool) -> None:
        self._run(
            "like-song" if liked else "unlike-song",
            item.id,
            lambda: self.youtube.mutate(lambda client: client.like_song(item.id, liked)),
            "Música adicionada à biblioteca" if liked else "Música removida da biblioteca",
            self.sync_library,
        )

    def set_artist_subscribed(self, item: LibraryItem, subscribed: bool) -> None:
        self._run(
            "subscribe-artist" if subscribed else "unsubscribe-artist",
            item.id,
            lambda: self.youtube.mutate(
                lambda client: client.subscribe_artist(item.id, subscribed)
            ),
            "Inscrição realizada" if subscribed else "Inscrição cancelada",
            self.sync_library,
        )

    def set_collection_saved(
        self,
        item: LibraryItem,
        tracks: list[LibraryItem],
        saved: bool,
    ) -> None:
        playlist_id = item.playlist_id or next(
            (track.playlist_id for track in tracks if track.playlist_id),
            None,
        )
        if item.kind == "playlists":
            playlist_id = playlist_id or item.id
        if not playlist_id:
            self.set_status("O YouTube Music não informou como salvar este item.")
            return
        self._run(
            "like-collection" if saved else "unlike-collection",
            playlist_id,
            lambda: self.youtube.mutate(
                lambda client: client.like_playlist(playlist_id, saved)
            ),
            "Adicionado à biblioteca" if saved else "Removido da biblioteca",
            self.sync_library,
        )

    def create_playlist(self, title: str) -> None:
        title = title.strip()
        if not title:
            return
        self._run(
            "create-playlist",
            "",
            lambda: self.youtube.mutate(lambda client: client.create_playlist(title)),
            "Playlist criada",
            self.sync_library,
        )

    def rename_playlist(
        self,
        item: LibraryItem,
        title: str,
        refresh_detail: Callable[[], None] | None = None,
    ) -> None:
        title = title.strip()
        if not title:
            return

        def completed() -> None:
            self.sync_library()
            if refresh_detail:
                refresh_detail()

        self._run(
            "rename-playlist",
            item.id,
            lambda: self.youtube.mutate(lambda client: client.rename_playlist(item.id, title)),
            "Playlist renomeada",
            completed,
        )

    def delete_playlist(self, item: LibraryItem, on_deleted: Callable[[], None]) -> None:
        def completed() -> None:
            self.sync_library()
            on_deleted()

        self._run(
            "delete-playlist",
            item.id,
            lambda: self.youtube.mutate(lambda client: client.delete_playlist(item.id)),
            "Playlist excluída",
            completed,
        )

    def add_to_playlist(self, playlist: LibraryItem, song: LibraryItem) -> None:
        self._run(
            "add-to-playlist",
            song.id,
            lambda: self.youtube.mutate(
                lambda client: client.add_to_playlist(playlist.id, song.id)
            ),
            f"Adicionada a {playlist.title}",
        )

    def remove_from_playlist(
        self,
        playlist: LibraryItem,
        song: LibraryItem,
        refresh_detail: Callable[[], None],
    ) -> None:
        self._run(
            "remove-from-playlist",
            song.id,
            lambda: self.youtube.mutate(
                lambda client: client.remove_from_playlist(
                    playlist.id,
                    song.id,
                    song.set_video_id or "",
                )
            ),
            "Faixa removida da playlist",
            refresh_detail,
        )
