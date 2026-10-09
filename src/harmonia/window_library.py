from __future__ import annotations

import logging
import threading
from html import escape

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from .i18n import _
from .models import (
    LibraryItem,
)
from .ui import (
    action_button,
    page_shell,
)
from .window_constants import LABELS

LOGGER = logging.getLogger(__name__)


class WindowLibraryMixin:
    def _render(self) -> None:
        has_local_content = bool(
            self.storage.load_local_media()
            or self.storage.load_downloads()
            or self.storage.load_local_playlists()
        )
        if not self.storage.load_cookie() and not has_local_content:
            self.stack.add_named(self._welcome(), "welcome")
            self.stack.set_visible_child_name("welcome")
            return
        shell = page_shell("content", spacing=22)
        page, content = shell.scroll, shell.content
        content.append(self._library_header())
        if self.library_origin == "local":
            content.append(self._local_library_actions())
        content.append(self._library_body())
        old = self.stack.get_child_by_name("library")
        if old:
            self.stack.remove(old)
        self.stack.add_named(page, "library")
        self.stack.set_visible_child_name("library")

    def _library_header(self) -> Gtk.Widget:
        """Title and description, with the origin, sorting and category controls."""
        hero = Adw.WrapBox(
            orientation=Gtk.Orientation.HORIZONTAL,
            child_spacing=18,
            line_spacing=12,
            natural_line_length=900,
            wrap_policy=Adw.WrapPolicy.NATURAL,
        )
        hero.add_css_class("hero")
        hero.add_css_class("app-page-header")
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        title = Gtk.Label(label=_("Biblioteca"), xalign=0)
        title.add_css_class("hero-title")
        copy.append(title)
        subtitle = Gtk.Label(label=self._library_description(), xalign=0)
        subtitle.add_css_class("hero-subtitle")
        copy.append(subtitle)
        hero.append(copy)
        hero.append(self._library_controls())
        return hero

    def _library_controls(self) -> Gtk.Widget:
        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, valign=Gtk.Align.END)
        source_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.END
        )
        origin_keys = ["youtube", "uploads", "downloads", "local", "podcasts"]
        origin = Gtk.DropDown.new_from_strings(
            [
                _("YouTube Music"),
                _("Uploads"),
                _("Downloads"),
                _("Arquivos locais"),
                _("Podcasts"),
            ]
        )
        origin.set_selected(origin_keys.index(self.library_origin))
        origin.connect(
            "notify::selected",
            lambda dropdown, _pspec: self._set_library_origin(origin_keys[dropdown.get_selected()]),
        )
        source_row.append(origin)
        sorting = Gtk.DropDown.new_from_strings([_("Mais recentes"), _("A-Z")])
        sorting.set_selected(0 if self.library_sort == "recent" else 1)
        sorting.connect(
            "notify::selected",
            lambda dropdown, _pspec: self._set_library_sort(
                "recent" if dropdown.get_selected() == 0 else "title"
            ),
        )
        source_row.append(sorting)
        controls.append(source_row)
        filters = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2, valign=Gtk.Align.END)
        filters.add_css_class("segmented-control")
        group = None
        for key in ("albums", "artists", "songs", "playlists"):
            button = Gtk.ToggleButton(label=LABELS[key])
            if group is None:
                group = button
            else:
                button.set_group(group)
            button.set_active(key == self.library_filter)
            button.connect(
                "toggled",
                lambda selected, category=key: (
                    selected.get_active() and self._set_library_filter(category)
                ),
            )
            filters.append(button)
        controls.append(filters)
        return controls

    def _local_library_actions(self) -> Gtk.Widget:
        actions = Adw.WrapBox(
            orientation=Gtk.Orientation.HORIZONTAL,
            child_spacing=8,
            line_spacing=8,
            natural_line_length=620,
            wrap_policy=Adw.WrapPolicy.NATURAL,
        )
        for label, icon, role, open_dialog in (
            (_("Adicionar arquivos"), "document-open-symbolic", "secondary",
             self._add_local_files_dialog),
            (_("Importar playlist"), "document-open-symbolic", "secondary",
             self._import_local_playlist_dialog),
            (_("Nova playlist local"), "list-add-symbolic", "primary",
             self._create_local_playlist_dialog),
        ):  # fmt: skip
            button = action_button(label, icon, role=role)
            button.connect("clicked", lambda *_args, run=open_dialog: run())
            actions.append(button)
        return actions

    def _library_body(self) -> Gtk.Widget:
        items = self._library_items_for_view()
        if not self.sections and self.library_origin in ("youtube", "uploads", "podcasts"):
            return Adw.StatusPage(
                icon_name="view-refresh-symbolic",
                title=_("Sincronizando…"),
                description=_("Buscando sua biblioteca no YouTube Music"),
            )
        if not items:
            return Adw.StatusPage(
                icon_name="folder-music-symbolic",
                title=_("Nada nesta visualização"),
                description=_("Altere a origem ou adicione conteúdo à biblioteca."),
            )
        if self.library_filter == "songs":
            return self._song_section(self._library_description(), items, items)
        return self._section(self.library_filter, items, limit=len(items))

    def _library_description(self) -> str:
        if self.library_origin != "youtube":
            return {
                "uploads": _("Músicas enviadas à sua conta do YouTube Music."),
                "downloads": _("Conteúdo disponível para reprodução offline."),
                "local": _("Arquivos e playlists armazenados neste computador."),
                "podcasts": _("Programas e episódios salvos na sua conta."),
            }[self.library_origin]
        return {
            "albums": _("Álbuns e EPs salvos na sua coleção."),
            "artists": _("Artistas que você acompanha."),
            "songs": _("Todas as músicas marcadas como favoritas."),
            "playlists": _("Playlists salvas na sua conta."),
        }[self.library_filter]

    def _library_items_for_view(self) -> list[LibraryItem]:
        if self.library_origin == "youtube":
            items = list(self.sections.get(self.library_filter, []))
        elif self.library_origin == "uploads":
            key = "uploaded-albums" if self.library_filter == "albums" else "uploads"
            items = (
                list(self.sections.get(key, []))
                if self.library_filter in ("albums", "songs")
                else []
            )
        elif self.library_origin == "downloads":
            items = (
                [
                    record.item
                    for record in self.storage.load_downloads()
                    if record.status == "completed"
                ]
                if self.library_filter == "songs"
                else []
            )
        elif self.library_origin == "local":
            if self.library_filter == "songs":
                items = self.storage.load_local_media()
            elif self.library_filter == "playlists":
                items = [
                    LibraryItem(
                        f"local-playlist:{playlist.id}",
                        playlist.title,
                        f"{len(playlist.items)} faixas",
                        kind="local-playlists",
                    )
                    for playlist in self.storage.load_local_playlists()
                ]
            else:
                items = []
        else:
            if self.library_filter == "songs":
                items = [
                    item
                    for item in self.sections.get("podcast-episodes", [])
                    if item.kind == "songs"
                ]
            elif self.library_filter == "playlists":
                items = list(self.sections.get("podcasts", []))
            else:
                items = []
        if self.library_sort == "title":
            items.sort(key=lambda item: item.title.casefold())
        return items

    def _set_library_filter(self, key: str) -> None:
        if key != self.library_filter:
            self.library_filter = key
            self._render()
            self.stack.set_visible_child_name("library")

    def _set_library_origin(self, key: str) -> None:
        if key != self.library_origin:
            self.library_origin = key
            if key in ("downloads", "local") and self.library_filter not in ("songs", "playlists"):
                self.library_filter = "songs"
            self._render()
            self.stack.set_visible_child_name("library")

    def _set_library_sort(self, key: str) -> None:
        if key != self.library_sort:
            self.library_sort = key
            self._render()
            self.stack.set_visible_child_name("library")

    def _welcome(self) -> Gtk.Widget:
        page = Adw.StatusPage(
            icon_name="audio-headphones-symbolic",
            title=_("Sua música, no seu desktop"),
            description=_(
                "Conecte sua sessão do YouTube Music para sincronizar playlists, músicas, álbuns e artistas."
            ),
        )
        page.add_css_class("welcome")
        button = action_button(_("Conectar ao YouTube Music"), role="accent")
        button.set_halign(Gtk.Align.CENTER)
        button.connect("clicked", lambda *_: self.login_dialog())
        page.set_child(button)
        return page

    def _remove_local_library_item(self, item: LibraryItem) -> None:
        self.storage.remove_local_media(item.id)
        self._render()

    def show_category(self, key: str) -> None:
        """Select a YouTube library category without leaving the library shell.

        Older builds created a separate ``category`` stack page here.  Besides
        duplicating the grid, that page dropped the origin, sorting and category
        controls, leaving no way to move from Artists to Albums without using
        the sidebar.  A category is presentation state of the library, not a
        navigation destination of its own.
        """
        if key not in LABELS:
            return
        self.library_origin = "youtube"
        self.library_filter = key
        self.show_library()
        self._set_active_nav(key if key in self.nav_buttons else "library")

    def navigate_credit(self, kind: str, target: str, name: str) -> None:
        """Open an artist or album named in a subtitle, from anywhere in the app."""
        if getattr(self, "expanded_revealer", None) and self.expanded_revealer.get_reveal_child():
            self._hide_expanded_player()
        if kind == "artist":
            self.open_item(LibraryItem(target, name, kind="artists"))
        elif kind == "album":
            self.open_item(LibraryItem(target, name, kind="albums"))
        elif name:
            self._search_for(name)

    def open_item(self, item: LibraryItem) -> None:
        if item.kind in ("songs", "videos"):
            songs = self.sections.get("songs", [])
            if item in songs:
                self.set_queue(songs, songs.index(item))
            else:
                self.set_queue([item], 0)
            return
        if item.kind == "local-playlists":
            try:
                playlist_id = int(item.id.split(":", 1)[1])
            except (IndexError, ValueError):
                return
            playlist = self.storage.get_local_playlist(playlist_id)
            if playlist:
                self._show_local_playlist(playlist)
            return
        if item.kind == "artists":
            self._open_artist(item)
            return
        self.back.set_visible(True)
        self.detail_track_rows = []
        status = Adw.StatusPage(
            icon_name="view-refresh-symbolic",
            title=_("Carregando…"),
            description=_("Buscando {title}").format(title=escape(item.title)),
        )
        old = self.stack.get_child_by_name("detail")
        if old:
            self.stack.remove(old)
        self.stack.add_named(status, "detail")
        self.stack.set_visible_child_name("detail")

        def worker():
            try:
                tracks = self.youtube.browse(item)
                GLib.idle_add(self._show_detail, item, tracks, None, status)
            except Exception as exc:
                GLib.idle_add(self._show_detail, item, None, str(exc), status)

        threading.Thread(target=worker, daemon=True).start()
