from __future__ import annotations

import logging
import re
import threading
import urllib.request
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from .i18n import _, ngettext
from .models import (
    LibraryItem,
    LocalPlaylist,
)
from .ui import (
    action_button,
    icon_button,
    page_header,
    page_shell,
    section_link,
)
from .window_constants import ICONS, LABELS, LIKED_ICON

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
        hero.append(controls)
        content.append(hero)
        if self.library_origin == "local":
            actions = Adw.WrapBox(
                orientation=Gtk.Orientation.HORIZONTAL,
                child_spacing=8,
                line_spacing=8,
                natural_line_length=620,
                wrap_policy=Adw.WrapPolicy.NATURAL,
            )
            add_files = action_button(
                _("Adicionar arquivos"), "document-open-symbolic", role="secondary"
            )
            add_files.connect("clicked", lambda *_: self._add_local_files_dialog())
            actions.append(add_files)
            import_playlist = action_button(
                _("Importar playlist"), "document-open-symbolic", role="secondary"
            )
            import_playlist.connect("clicked", lambda *_: self._import_local_playlist_dialog())
            actions.append(import_playlist)
            create_playlist = action_button(
                _("Nova playlist local"), "list-add-symbolic", role="primary"
            )
            create_playlist.connect("clicked", lambda *_: self._create_local_playlist_dialog())
            actions.append(create_playlist)
            content.append(actions)
        items = self._library_items_for_view()
        if not self.sections and self.library_origin in ("youtube", "uploads", "podcasts"):
            status = Adw.StatusPage(
                icon_name="view-refresh-symbolic",
                title=_("Sincronizando…"),
                description=_("Buscando sua biblioteca no YouTube Music"),
            )
            content.append(status)
        elif not items:
            content.append(
                Adw.StatusPage(
                    icon_name="folder-music-symbolic",
                    title=_("Nada nesta visualização"),
                    description=_("Altere a origem ou adicione conteúdo à biblioteca."),
                )
            )
        else:
            if self.library_filter == "songs":
                content.append(self._song_section(self._library_description(), items, items))
            else:
                section_kind = (
                    "playlists" if self.library_filter == "playlists" else self.library_filter
                )
                content.append(self._section(section_kind, items, limit=len(items)))
        old = self.stack.get_child_by_name("library")
        if old:
            self.stack.remove(old)
        self.stack.add_named(page, "library")
        self.stack.set_visible_child_name("library")

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

    def _section_header(self, title: str, on_all=None) -> Gtk.Widget:
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        heading = Gtk.Label(label=title, xalign=0, hexpand=True)
        heading.add_css_class("section-title")
        header.append(heading)
        if on_all:
            header.append(section_link(_("Mostrar tudo"), on_all))
        return header

    def _section(self, key: str, items: list[LibraryItem], limit: int = 8) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.append(self._section_header(LABELS[key], lambda: self.show_category(key)))
        flow = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            column_spacing=16,
            row_spacing=18,
            min_children_per_line=2,
            max_children_per_line=5,
            homogeneous=False,
        )
        for item in items[:limit]:
            flow.append(
                self._media_card_button(item, 140, lambda selected=item: self.open_item(selected))
            )
        box.append(flow)
        return box

    def _media_card_button(
        self,
        item: LibraryItem,
        size: int,
        activate,
    ) -> Gtk.Button:
        """One card interaction shared by Home, Library and artist shelves."""
        button = Gtk.Button()
        button.add_css_class("media-card-button")
        button.set_halign(Gtk.Align.START)
        button.set_valign(Gtk.Align.START)
        button.set_hexpand(False)
        button.set_size_request(size, -1)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        card.add_css_class("media-card")
        card.set_size_request(size, -1)

        cover = self._square_cover(item, size=size)
        cover.add_css_class("media-card-cover")
        # The labels below can be wider than the artwork.  Keep the overlay on
        # the artwork's exact allocation; otherwise GtkBox stretches it to the
        # card width and a mathematically centred action appears shifted right.
        cover_overlay = Gtk.Overlay(
            halign=Gtk.Align.START,
            valign=Gtk.Align.START,
            hexpand=False,
            vexpand=False,
        )
        cover_overlay.set_size_request(size, size)
        cover_overlay.set_hexpand_set(True)
        cover_overlay.set_vexpand_set(True)
        cover_overlay.set_child(cover)
        hint = Gtk.CenterBox(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        hint.set_size_request(48, 48)
        hint.set_hexpand(False)
        hint.set_vexpand(False)
        hint.add_css_class("home-cover-action")
        hint.add_css_class("media-card-action")
        hint.set_opacity(0)
        hint.set_can_target(False)
        icon_name = (
            "media-playback-start-symbolic"
            if item.kind in ("songs", "videos")
            else "go-next-symbolic"
        )
        action_icon = Gtk.Image.new_from_icon_name(icon_name)
        action_icon.set_pixel_size(26)
        hint.set_center_widget(action_icon)
        cover_overlay.add_overlay(hint)
        card.append(cover_overlay)

        width_chars = 20 if size >= 160 else 17
        title = Gtk.Label(
            label=item.title,
            xalign=0,
            ellipsize=3,
            width_chars=width_chars,
            max_width_chars=width_chars,
        )
        title.add_css_class("card-title")
        card.append(title)
        if item.subtitle:
            subtitle = Gtk.Label(
                label=item.subtitle,
                xalign=0,
                ellipsize=3,
                width_chars=width_chars,
                max_width_chars=width_chars,
            )
            subtitle.add_css_class("card-subtitle")
            card.append(subtitle)
        button.set_child(card)
        hover = Gtk.EventControllerMotion()
        hover.connect("enter", lambda *_args: self._home_card_hover(cover, hint, True))
        hover.connect("leave", lambda *_args: self._home_card_hover(cover, hint, False))
        button.add_controller(hover)
        button.connect("clicked", lambda *_: activate())
        return button

    def _square_cover(self, item: LibraryItem, size: int = 140, fixed: bool = False) -> Gtk.Widget:
        """Create conventional 1:1 music artwork, circular only for artists."""
        # Detail artwork has an exact desktop size.  A plain overlay keeps it
        # from reserving the hero's full cross-axis size, while cards continue
        # to use AspectFrame so their 1:1 ratio survives responsive layouts.
        frame = Gtk.Overlay() if fixed else Gtk.AspectFrame(ratio=1.0, obey_child=False)
        frame.set_size_request(size, size)
        frame.set_halign(Gtk.Align.START)
        frame.set_valign(Gtk.Align.START)
        if fixed:
            frame.set_hexpand(False)
            frame.set_hexpand_set(True)
            frame.set_vexpand(False)
            frame.set_vexpand_set(True)
        frame.set_overflow(Gtk.Overflow.HIDDEN)
        frame.add_css_class("artist-cover" if item.kind == "artists" else "square-cover")
        overlay = Gtk.Overlay(hexpand=True, vexpand=True)
        placeholder = Gtk.Image.new_from_icon_name(ICONS.get(item.kind, "audio-x-generic-symbolic"))
        placeholder.set_pixel_size(42)
        placeholder.add_css_class("cover-placeholder")
        overlay.set_child(placeholder)
        if item.thumbnail:
            picture = Gtk.Picture(
                content_fit=Gtk.ContentFit.COVER, can_shrink=True, hexpand=True, vexpand=True
            )
            picture.add_css_class("cover-art")
            overlay.add_overlay(picture)
            self._load_artwork(item.thumbnail, picture, size=max(256, size * 2))
        frame.set_child(overlay)
        return frame

    def _song_section(
        self, title: str, items: list[LibraryItem], source: list[LibraryItem]
    ) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.append(self._section_header(title, lambda: self.show_category("songs")))
        listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        listing.add_css_class("boxed-list")
        for item in items:
            row = Adw.ActionRow()
            row.add_css_class("media-row")
            row.set_use_markup(False)
            row.set_title(item.title)
            row.set_subtitle(item.subtitle)
            row.add_css_class("song-row")
            row.set_activatable(True)
            thumb = Gtk.Picture(content_fit=Gtk.ContentFit.COVER)
            thumb.set_size_request(52, 52)
            thumb.set_can_shrink(True)
            thumb.set_overflow(Gtk.Overflow.HIDDEN)
            thumb.add_css_class("row-cover")
            if item.thumbnail:
                self._load_artwork(item.thumbnail, thumb, size=128)
            row.add_prefix(thumb)
            if self.library_origin == "local":
                remove = icon_button(
                    "user-trash-symbolic",
                    _("Remover da biblioteca local"),
                    size="sm",
                    destructive=True,
                )
                remove.connect(
                    "clicked",
                    lambda _button, selected=item: GLib.idle_add(
                        self._remove_local_library_item, selected
                    ),
                )
                row.add_suffix(remove)
            elif self.library_origin == "downloads":
                remove = icon_button(
                    "user-trash-symbolic", _("Excluir download"), size="sm", destructive=True
                )
                remove.connect(
                    "clicked", lambda _button, selected=item: self.downloads.remove(selected.id)
                )
                row.add_suffix(remove)
            elif self.library_origin == "youtube":
                remove = icon_button(LIKED_ICON, _("Remover das músicas marcadas"), size="sm")
                remove.connect(
                    "clicked", lambda _button, selected=item: self._toggle_song(selected, False)
                )
                row.add_suffix(remove)
            row.add_suffix(Gtk.Image.new_from_icon_name("media-playback-start-symbolic"))
            row.connect(
                "activated",
                lambda _row, selected=item, queue=source: self.set_queue(
                    queue, queue.index(selected)
                ),
            )
            listing.append(row)
        box.append(listing)
        return box

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

    @staticmethod
    def _sized_artwork_url(url: str, size: int | None = None) -> str:
        """Request a sharper Google/YouTube thumbnail without changing its asset."""
        if not size or not any(
            domain in url
            for domain in (
                "googleusercontent.com",
                "ggpht.com",
            )
        ):
            return url
        size = max(64, min(1280, int(size)))
        result = re.sub(r"([=-])w\d+(?=-|$)", rf"\1w{size}", url)
        result = re.sub(r"([=-])h\d+(?=-|$)", rf"\1h{size}", result)
        result = re.sub(r"=s\d+(?=-|$)", f"=s{size}", result)
        return result

    def _set_artwork_if_current(
        self,
        picture: Gtk.Picture,
        target: Path,
        request_key: str,
    ) -> bool:
        if self._artwork_requests.get(id(picture)) == request_key and target.exists():
            picture.set_filename(str(target))
        return GLib.SOURCE_REMOVE

    def _load_artwork(
        self,
        url: str,
        picture: Gtk.Picture,
        *,
        size: int | None = None,
    ) -> None:
        request_url = self._sized_artwork_url(url, size)
        target = self.storage.artwork_path(request_url)
        request_key = str(target)
        self._artwork_requests[id(picture)] = request_key
        if target.exists():
            picture.set_filename(str(target))
            return

        def worker():
            try:
                request = urllib.request.Request(request_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(request, timeout=15) as response:
                    data = response.read(12 * 1024 * 1024)
                target.write_bytes(data)
                GLib.idle_add(self._set_artwork_if_current, picture, target, request_key)
            except Exception:
                LOGGER.debug("Não foi possível carregar a arte de %s", request_url, exc_info=True)

        threading.Thread(target=worker, daemon=True).start()

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
            description=_("Buscando {title}").format(title=item.title),
        )
        old = self.stack.get_child_by_name("detail")
        if old:
            self.stack.remove(old)
        self.stack.add_named(status, "detail")
        self.stack.set_visible_child_name("detail")

        def worker():
            try:
                tracks = self.youtube.browse(item)
                GLib.idle_add(self._show_detail, item, tracks, None)
            except Exception as exc:
                GLib.idle_add(self._show_detail, item, None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _show_local_playlist(self, playlist: LocalPlaylist) -> None:
        self.main_view = "local-playlist"
        self.back.set_visible(True)
        old = self.stack.get_child_by_name("local-playlist")
        if old:
            self.stack.remove(old)
        shell = page_shell("reading", spacing=22)
        scroll, content = shell.scroll, shell.content
        play = action_button(_("Reproduzir"), "media-playback-start-symbolic", role="primary")
        play.set_sensitive(bool(playlist.items))
        play.connect("clicked", lambda *_: playlist.items and self.set_queue(playlist.items, 0))
        add = action_button(_("Adicionar arquivos"), "list-add-symbolic", role="secondary")
        add.connect("clicked", lambda *_: self._add_local_files_dialog(playlist))
        export = action_button(_("Exportar"), "document-save-symbolic", role="secondary")
        export.connect("clicked", lambda *_: self._export_local_playlist_dialog(playlist))
        rename = icon_button("document-edit-symbolic", _("Renomear playlist"), size="md")
        rename.connect("clicked", lambda *_: self._rename_local_playlist_dialog(playlist))
        delete = icon_button(
            "user-trash-symbolic", _("Excluir playlist"), size="md", destructive=True
        )
        delete.connect("clicked", lambda *_: self._confirm_delete_local_playlist(playlist))
        track_count = ngettext("{count} faixa", "{count} faixas", len(playlist.items)).format(
            count=len(playlist.items)
        )
        content.append(
            page_header(
                playlist.title,
                _("Playlist local · {tracks}").format(tracks=track_count),
                actions=(play, add, export, rename, delete),
            )
        )
        group = Adw.PreferencesGroup(title=track_count)
        for position, item in enumerate(playlist.items):
            row = Adw.ActionRow()
            row.add_css_class("media-row")
            row.set_use_markup(False)
            row.set_title(item.title)
            row.set_subtitle(item.subtitle)
            row.set_activatable(True)
            row.connect(
                "activated",
                lambda _row, selected=position: self.set_queue(playlist.items, selected),
            )
            controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            up = icon_button("go-up-symbolic", _("Mover para cima"), size="sm")
            down = icon_button("go-down-symbolic", _("Mover para baixo"), size="sm")
            remove = icon_button("list-remove-symbolic", _("Remover"), size="sm")
            for button in (up, down, remove):
                controls.append(button)
            up.set_sensitive(position > 0)
            down.set_sensitive(position + 1 < len(playlist.items))
            up.connect(
                "clicked",
                lambda *_args, selected=position: GLib.idle_add(
                    self._move_local_playlist_item, playlist, selected, -1
                ),
            )
            down.connect(
                "clicked",
                lambda *_args, selected=position: GLib.idle_add(
                    self._move_local_playlist_item, playlist, selected, 1
                ),
            )
            remove.connect(
                "clicked",
                lambda *_args, selected=position: GLib.idle_add(
                    self._remove_local_playlist_item, playlist, selected
                ),
            )
            row.add_suffix(controls)
            group.add(row)
        content.append(group)
        self.stack.add_named(scroll, "local-playlist")
        self.stack.set_visible_child_name("local-playlist")

    def _move_local_playlist_item(
        self, playlist: LocalPlaylist, position: int, direction: int
    ) -> None:
        target = position + direction
        if target < 0 or target >= len(playlist.items):
            return
        playlist.items[position], playlist.items[target] = (
            playlist.items[target],
            playlist.items[position],
        )
        self.storage.save_local_playlist(playlist)
        self._show_local_playlist(playlist)

    def _remove_local_playlist_item(self, playlist: LocalPlaylist, position: int) -> None:
        if 0 <= position < len(playlist.items):
            playlist.items.pop(position)
            self.storage.save_local_playlist(playlist)
            self._show_local_playlist(playlist)

    def _delete_local_playlist(self, playlist: LocalPlaylist) -> None:
        if playlist.id is not None:
            self.storage.delete_local_playlist(playlist.id)
        self.library_origin = "local"
        self.library_filter = "playlists"
        self.show_library()

    def _confirm_delete_local_playlist(self, playlist: LocalPlaylist) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Excluir playlist local?"),
            body=_(
                "“{title}” será removida deste dispositivo. Os arquivos de áudio serão preservados."
            ).format(title=playlist.title),
        )
        dialog.add_response("cancel", _("Cancelar"))
        dialog.add_response("delete", _("Excluir"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect(
            "response",
            lambda _dialog, response: (
                response == "delete" and self._delete_local_playlist(playlist)
            ),
        )
        dialog.present(self)

    def _rename_local_playlist_dialog(self, playlist: LocalPlaylist) -> None:
        dialog = Adw.AlertDialog(heading=_("Renomear playlist local"))
        entry = Gtk.Entry(text=playlist.title)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", _("Cancelar"))
        dialog.add_response("rename", _("Renomear"))
        dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)

        def response(_dialog, name: str) -> None:
            title = entry.get_text().strip()
            if name == "rename" and title:
                playlist.title = title
                self.storage.save_local_playlist(playlist)
                self._show_local_playlist(playlist)

        dialog.connect("response", response)
        dialog.present(self)
