"""Local playlists: a page per playlist, reordering, renaming and deleting."""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from .i18n import _, ngettext
from .models import (
    LocalPlaylist,
)
from .ui import (
    action_button,
    icon_button,
    link_row_subtitle,
    page_header,
    page_shell,
)

LOGGER = logging.getLogger(__name__)


class WindowLocalPlaylistsMixin:
    """Playlists kept only on this computer (storage/local.py)."""

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
            link_row_subtitle(row, item, self.navigate_credit)
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
