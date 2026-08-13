from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from .i18n import _
from .models import (
    LibraryItem,
    LocalPlaylist,
)
from .ui import (
    set_icon_selected,
)

LOGGER = logging.getLogger(__name__)


class WindowActionsMixin:
    def _mutate(
        self, action: str, target: str | None, operation, success_message: str, on_success=None
    ) -> None:
        self.toast_overlay.add_toast(
            Adw.Toast(title=_("Enviando alteração ao YouTube Music…"), timeout=2)
        )

        def worker():
            try:
                result = self.youtube.mutate(operation)
                self.storage.log_action(action, target, "completed")
                GLib.idle_add(done, result, None)
            except Exception as exc:
                self.storage.log_action(action, target, "failed", str(exc))
                GLib.idle_add(done, None, str(exc))

        def done(result, error):
            if error:
                self.toast_overlay.add_toast(
                    Adw.Toast(
                        title=_("Alteração não aplicada: {error}").format(error=error),
                        timeout=6,
                    )
                )
            else:
                self.toast_overlay.add_toast(Adw.Toast(title=success_message))
                if on_success:
                    on_success(result)
            return False

        threading.Thread(target=worker, daemon=True).start()

    def _toggle_song(self, item: LibraryItem, liked: bool) -> None:
        verb = "like-song" if liked else "unlike-song"
        message = (
            _("Música adicionada à biblioteca") if liked else _("Música removida da biblioteca")
        )
        self._mutate(
            verb,
            item.id,
            lambda client: client.like_song(item.id, liked),
            message,
            lambda _r: self.sync(),
        )

    def _refresh_current_like_from_library(self) -> None:
        item = getattr(self, "current_item", None)
        self.current_liked = bool(
            item and any(song.id == item.id for song in self.sections.get("songs", []))
        )
        self._refresh_current_like_buttons()

    def _refresh_current_like_buttons(self) -> None:
        for button in self.like_buttons:
            button.set_icon_name(
                "starred-symbolic" if self.current_liked else "non-starred-symbolic"
            )
            button.set_tooltip_text(
                _("Remover das músicas curtidas") if self.current_liked else _("Curtir música")
            )
            if self.current_liked:
                set_icon_selected(button, True)
            else:
                set_icon_selected(button, False)

    def _toggle_current_song_like(self) -> None:
        item = getattr(self, "current_item", None)
        if item is None:
            return
        self.current_liked = not self.current_liked
        self._refresh_current_like_buttons()
        self._toggle_song(item, self.current_liked)

    def _toggle_artist(self, item: LibraryItem, subscribed: bool) -> None:
        message = _("Inscrição realizada") if subscribed else _("Inscrição cancelada")
        self._mutate(
            "subscribe-artist" if subscribed else "unsubscribe-artist",
            item.id,
            lambda client: client.subscribe_artist(item.id, subscribed),
            message,
            lambda _r: self.sync(),
        )

    def create_playlist_dialog(self) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Nova playlist"),
            body=_("Ela será criada como privada na sua conta do YouTube Music."),
        )
        entry = Gtk.Entry(placeholder_text=_("Nome da playlist"))
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", _("Cancelar"))
        dialog.add_response("create", _("Criar"))
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect(
            "response",
            lambda _d, response: (
                response == "create"
                and entry.get_text().strip()
                and self._mutate(
                    "create-playlist",
                    None,
                    lambda client: client.create_playlist(entry.get_text()),
                    _("Playlist criada"),
                    lambda _r: self.sync(),
                )
            ),
        )
        dialog.present(self)

    def _create_local_playlist_dialog(self) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Nova playlist local"),
            body=_("A playlist ficará somente neste computador."),
        )
        entry = Gtk.Entry(placeholder_text=_("Nome da playlist"))
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", _("Cancelar"))
        dialog.add_response("create", _("Criar"))
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)

        def response(_dialog, name: str) -> None:
            title = entry.get_text().strip()
            if name == "create" and title:
                playlist_id = self.storage.create_local_playlist(title)
                playlist = self.storage.get_local_playlist(playlist_id)
                if playlist:
                    self._show_local_playlist(playlist)

        dialog.connect("response", response)
        dialog.present(self)

    @staticmethod
    def _audio_file_filter() -> Gtk.FileFilter:
        file_filter = Gtk.FileFilter(name=_("Arquivos de áudio"))
        file_filter.add_mime_type("audio/*")
        for pattern in ("*.mp3", "*.m4a", "*.aac", "*.ogg", "*.opus", "*.flac", "*.wav", "*.wma"):
            file_filter.add_pattern(pattern)
        return file_filter

    def _add_local_files_dialog(self, playlist: LocalPlaylist | None = None) -> None:
        dialog = Gtk.FileDialog(title=_("Adicionar arquivos de áudio"))
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(self._audio_file_filter())
        dialog.set_filters(filters)

        def selected(file_dialog: Gtk.FileDialog, result) -> None:
            try:
                files = file_dialog.open_multiple_finish(result)
                paths = [files.get_item(index).get_path() for index in range(files.get_n_items())]
                items = self.storage.add_local_files([path for path in paths if path])
                if playlist is not None:
                    known = {item.id for item in playlist.items}
                    playlist.items.extend(item for item in items if item.id not in known)
                    self.storage.save_local_playlist(playlist)
                    self._show_local_playlist(playlist)
                else:
                    self.library_origin = "local"
                    self.library_filter = "songs"
                    self._render()
            except GLib.Error:
                return

        dialog.open_multiple(self, None, selected)

    def _import_local_playlist_dialog(self) -> None:
        dialog = Gtk.FileDialog(title=_("Importar playlist"))
        file_filter = Gtk.FileFilter(name=_("Playlists M3U ou JSON"))
        for pattern in ("*.m3u", "*.m3u8", "*.json"):
            file_filter.add_pattern(pattern)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(file_filter)
        dialog.set_filters(filters)

        def selected(file_dialog: Gtk.FileDialog, result) -> None:
            try:
                source = file_dialog.open_finish(result)
                path = Path(source.get_path())
                title = path.stem
                items: list[LibraryItem] = []
                if path.suffix.casefold() == ".json":
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    title = str(payload.get("title") or title)
                    for value in payload.get("items") or []:
                        local_path = value.get("path")
                        if local_path:
                            items.extend(self.storage.add_local_files([local_path]))
                        elif value.get("id"):
                            items.append(
                                LibraryItem(
                                    str(value["id"]),
                                    str(value.get("title") or value["id"]),
                                    str(value.get("subtitle") or ""),
                                    value.get("thumbnail"),
                                    str(value.get("kind") or "songs"),
                                    value.get("playlist_id"),
                                    value.get("set_video_id"),
                                )
                            )
                else:
                    paths = []
                    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        candidate = Path(line)
                        paths.append(
                            str(candidate if candidate.is_absolute() else path.parent / candidate)
                        )
                    items = self.storage.add_local_files(paths)
                playlist_id = self.storage.create_local_playlist(title, items)
                playlist = self.storage.get_local_playlist(playlist_id)
                if playlist:
                    self._show_local_playlist(playlist)
            except (GLib.Error, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                self.toast_overlay.add_toast(
                    Adw.Toast(
                        title=_("Não foi possível importar: {error}").format(error=exc),
                        timeout=5,
                    )
                )

        dialog.open(self, None, selected)

    def _export_local_playlist_dialog(self, playlist: LocalPlaylist) -> None:
        dialog = Gtk.FileDialog(title=_("Exportar playlist"), initial_name=f"{playlist.title}.m3u8")

        def selected(file_dialog: Gtk.FileDialog, result) -> None:
            try:
                target_file = file_dialog.save_finish(result)
                target = Path(target_file.get_path())
                if target.suffix.casefold() == ".json":
                    values = []
                    for item in playlist.items:
                        local_path = (
                            self.storage.local_media_path(item.id)
                            if item.id.startswith("local:")
                            else None
                        )
                        values.append(
                            {
                                "id": item.id,
                                "title": item.title,
                                "subtitle": item.subtitle,
                                "thumbnail": item.thumbnail,
                                "kind": item.kind,
                                "playlist_id": item.playlist_id,
                                "set_video_id": item.set_video_id,
                                "path": str(local_path) if local_path else None,
                            }
                        )
                    target.write_text(
                        json.dumps(
                            {"title": playlist.title, "items": values}, ensure_ascii=False, indent=2
                        ),
                        encoding="utf-8",
                    )
                else:
                    lines = ["#EXTM3U"]
                    for item in playlist.items:
                        local_path = (
                            self.storage.local_media_path(item.id)
                            if item.id.startswith("local:")
                            else None
                        )
                        if local_path:
                            lines.extend((f"#EXTINF:-1,{item.title}", str(local_path)))
                    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
                self.toast_overlay.add_toast(Adw.Toast(title=_("Playlist exportada")))
            except (GLib.Error, OSError) as exc:
                self.toast_overlay.add_toast(
                    Adw.Toast(
                        title=_("Não foi possível exportar: {error}").format(error=exc),
                        timeout=5,
                    )
                )

        dialog.save(self, None, selected)

    def rename_playlist_dialog(self, item: LibraryItem) -> None:
        dialog = Adw.AlertDialog(heading=_("Renomear playlist"))
        entry = Gtk.Entry(text=item.title)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", _("Cancelar"))
        dialog.add_response("rename", _("Renomear"))
        dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect(
            "response",
            lambda _d, response: (
                response == "rename"
                and entry.get_text().strip()
                and self._mutate(
                    "rename-playlist",
                    item.id,
                    lambda client: client.rename_playlist(item.id, entry.get_text()),
                    _("Playlist renomeada"),
                    lambda _r: self.sync(),
                )
            ),
        )
        dialog.present(self)

    def delete_playlist_dialog(self, item: LibraryItem) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Excluir playlist?"),
            body=_("“{title}” será removida permanentemente da sua conta.").format(
                title=item.title
            ),
        )
        dialog.add_response("cancel", _("Cancelar"))
        dialog.add_response("delete", _("Excluir"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect(
            "response",
            lambda _d, response: (
                response == "delete"
                and self._mutate(
                    "delete-playlist",
                    item.id,
                    lambda client: client.delete_playlist(item.id),
                    _("Playlist excluída"),
                    lambda _r: (self.show_library(), self.sync()),
                )
            ),
        )
        dialog.present(self)

    def add_to_playlist_dialog(self, song: LibraryItem) -> None:
        playlists = self.sections.get("playlists", [])
        local_playlists = self.storage.load_local_playlists()
        if not playlists and not local_playlists:
            self.toast_overlay.add_toast(Adw.Toast(title=_("Crie uma playlist primeiro")))
            return
        dialog = Adw.AlertDialog(heading=_("Adicionar à playlist"), body=song.title)
        choices = [("remote", item) for item in playlists] + [
            ("local", item) for item in local_playlists
        ]
        dropdown = Gtk.DropDown.new_from_strings(
            [
                item.title if source == "remote" else f"{item.title} · local"
                for source, item in choices
            ]
        )
        dialog.set_extra_child(dropdown)
        dialog.add_response("cancel", _("Cancelar"))
        dialog.add_response("add", _("Adicionar"))
        dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)

        def response(_dialog, name):
            if name == "add":
                source, playlist = choices[dropdown.get_selected()]
                if source == "local":
                    if all(item.id != song.id for item in playlist.items):
                        playlist.items.append(song)
                        self.storage.save_local_playlist(playlist)
                    self.toast_overlay.add_toast(
                        Adw.Toast(title=_("Adicionada a {title}").format(title=playlist.title))
                    )
                else:
                    self._mutate(
                        "add-to-playlist",
                        song.id,
                        lambda client: client.add_to_playlist(playlist.id, song.id),
                        _("Adicionada a {title}").format(title=playlist.title),
                    )

        dialog.connect("response", response)
        dialog.present(self)

    def _remove_track(self, playlist: LibraryItem, song: LibraryItem) -> None:
        self._mutate(
            "remove-from-playlist",
            song.id,
            lambda client: client.remove_from_playlist(
                playlist.id, song.id, song.set_video_id or ""
            ),
            _("Faixa removida da playlist"),
            lambda _r: self.open_item(playlist),
        )
