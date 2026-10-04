from __future__ import annotations

import logging
import threading
import urllib.parse
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk

from .i18n import _
from .models import LibraryItem
from .ui import menu_action_button

LOGGER = logging.getLogger(__name__)
TRACK_KINDS = ("songs", "videos")
COLLECTION_KINDS = ("albums", "playlists", "local-playlists")


def share_url(item: LibraryItem) -> str | None:
    """The music.youtube.com link for an item, or None for local ones."""
    if item.id.startswith("local") or item.kind == "local-playlists":
        return None
    if item.kind in TRACK_KINDS:
        return f"https://music.youtube.com/watch?v={urllib.parse.quote(item.id)}"
    if item.kind in ("playlists", "albums") and (item.playlist_id or item.id.startswith("VL")):
        playlist = item.playlist_id or item.id.removeprefix("VL")
        return f"https://music.youtube.com/playlist?list={urllib.parse.quote(playlist)}"
    if item.kind == "artists":
        return f"https://music.youtube.com/channel/{urllib.parse.quote(item.id)}"
    return f"https://music.youtube.com/browse/{urllib.parse.quote(item.id)}"


class WindowItemMenuMixin:
    """The three-dot menu shared by tracks, albums and playlists everywhere.

    It follows YouTube Music's item menu: one flat list, icon then label,
    ordered from playing (shuffle, radio, play next, queue) to keeping
    (library, download, playlist) and sharing, then navigation.
    """

    def item_options_button(self, item: LibraryItem, **menu_options) -> Gtk.MenuButton | None:
        if item.kind not in TRACK_KINDS + COLLECTION_KINDS:
            return None
        options = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text=_("Mais opções"))
        popover = Gtk.Popover(has_arrow=False)
        popover.add_css_class("item-menu")
        options.set_popover(popover)
        # Built on demand: liked, saved and offline states change over time.
        popover.connect(
            "show", lambda *_: popover.set_child(self.item_menu(item, popover, **menu_options))
        )
        return options

    def item_menu(
        self,
        item: LibraryItem,
        popover: Gtk.Popover,
        *,
        collection: LibraryItem | None = None,
        liked: bool | None = None,
        on_like: Callable[[], None] | None = None,
    ) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.add_css_class("item-menu-list")

        def entry(label: str, icon: str, callback, *, sensitive: bool = True) -> None:
            button = menu_action_button(label, icon)
            button.set_sensitive(sensitive)
            button.connect("clicked", lambda *_: (popover.popdown(), callback()))
            box.append(button)

        if item.kind in TRACK_KINDS:
            self._track_entries(item, entry, collection, liked, on_like)
        else:
            self._collection_entries(item, entry)
        url = share_url(item)
        if url:
            entry(_("Compartilhar"), "emblem-shared-symbolic", lambda: self._copy_share_link(url))
        if item.kind in TRACK_KINDS:
            self._navigation_entries(item, entry, collection)
        return box

    def _track_entries(self, track, entry, collection, liked, on_like) -> None:
        remote = not track.id.startswith("local:")
        if remote:
            entry(_("Iniciar rádio"), "media-playlist-consecutive-symbolic",
                  lambda: self._start_track_radio(track))  # fmt: skip
        self.queue_menu_entries(track, entry)
        if remote:
            if liked is None:
                liked = any(song.id == track.id for song in self.sections.get("songs", []))
            entry(
                _("Remover das curtidas") if liked else _("Curtir música"),
                "starred-symbolic" if liked else "non-starred-symbolic",
                on_like or (lambda: self._toggle_song(track, not liked)),
            )
            entry(_("Salvar na playlist"), "list-add-symbolic",
                  lambda: self.add_to_playlist_dialog(track))  # fmt: skip
            if self.downloads.offline_path(track.id) is not None:
                entry(_("Disponível offline"), "emblem-ok-symbolic", lambda: None, sensitive=False)
            else:
                entry(_("Baixar"), "folder-download-symbolic",
                      lambda: self._download_items([track]))  # fmt: skip
        if collection and collection.kind == "playlists" and track.set_video_id:
            entry(_("Remover desta playlist"), "list-remove-symbolic",
                  lambda: self._remove_track(collection, track))  # fmt: skip

    def _collection_entries(self, item, entry) -> None:
        entry(_("Aleatório"), "media-playlist-shuffle-symbolic",
              lambda: self.with_collection_tracks(item, self._play_shuffled))  # fmt: skip
        self.queue_menu_entries(item, entry)
        if item.kind == "local-playlists":
            return
        saved = any(saved.id == item.id for saved in self.sections.get(item.kind, []))
        entry(
            _("Remover da biblioteca") if saved else _("Salvar na biblioteca"),
            "object-select-symbolic" if saved else "bookmark-new-symbolic",
            lambda: self.with_collection_tracks(
                item, lambda tracks: self.save_collection(item, tracks, not saved)
            ),
        )
        entry(_("Baixar"), "folder-download-symbolic",
              lambda: self.with_collection_tracks(item, self._download_items))  # fmt: skip

    def _navigation_entries(self, track, entry, collection) -> None:
        from .ui import track_artist

        artist = track_artist(track)
        if track.artist_id:
            entry(_("Ir para o artista"), "avatar-default-symbolic",
                  lambda: self.open_item(LibraryItem(track.artist_id, artist, kind="artists")))  # fmt: skip
        elif artist:
            entry(_("Buscar o artista"), "system-search-symbolic",
                  lambda: self._search_for(artist))  # fmt: skip
        current = collection.id if collection else None
        album_id = track.album_id or (
            current if collection and collection.kind == "albums" else None
        )
        if album_id and album_id != current:
            entry(_("Ir para o álbum"), "media-optical-symbolic",
                  lambda: self.open_item(LibraryItem(album_id, track.album, kind="albums")))  # fmt: skip

    def with_collection_tracks(self, item: LibraryItem, callback) -> None:
        """Run callback(tracks) with an album's or playlist's tracks."""
        if item.kind == "local-playlists":
            playlist = self.storage.get_local_playlist(int(item.id.split(":", 1)[1]))
            callback(list(playlist.items) if playlist else [])
            return

        def worker() -> None:
            try:
                tracks = self.youtube.browse(item)
            except Exception as exc:
                LOGGER.debug("Não foi possível carregar %s", item.id, exc_info=True)
                GLib.idle_add(self._collection_tracks_failed, item, str(exc))
                return
            GLib.idle_add(self._with_tracks_loaded, callback, tracks)

        threading.Thread(target=worker, daemon=True, name="collection-tracks").start()

    @staticmethod
    def _with_tracks_loaded(callback, tracks: list[LibraryItem]) -> bool:
        callback(tracks)
        return False

    def _collection_tracks_failed(self, item: LibraryItem, error: str) -> bool:
        self.toast_overlay.add_toast(
            Adw.Toast(
                title=_("Não foi possível carregar {title}: {error}").format(
                    title=item.title, error=error
                ),
                timeout=6,
            )
        )
        return False

    def _copy_share_link(self, url: str) -> None:
        Gdk.Display.get_default().get_clipboard().set(url)
        self.toast_overlay.add_toast(Adw.Toast(title=_("Link copiado"), timeout=2))
