"""The header of an album or playlist page: metadata, actions and saving."""

from __future__ import annotations

import random
import re
from dataclasses import replace

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .i18n import _, ngettext
from .models import LibraryItem
from .ui import (
    CreditsLabel,
    icon_button,
    item_credits,
    media_play_button,
    menu_action_button,
    set_icon_selected,
    style_icon_button,
)


class WindowDetailHeaderMixin:
    def _detail_hero(self, item: LibraryItem, tracks: list[LibraryItem]) -> Gtk.Widget:
        # Keep a stable editorial gutter instead of letting short titles
        # drift right according to their natural width.
        hero = Adw.WrapBox(
            orientation=Gtk.Orientation.HORIZONTAL,
            child_spacing=76,
            line_spacing=24,
            natural_line_length=920,
            wrap_policy=Adw.WrapPolicy.NATURAL,
        )
        hero.add_css_class("detail-hero")
        hero.add_css_class("app-page-header")
        art = self._square_cover(item, size=240, fixed=True)
        art.add_css_class("detail-hero-cover")
        hero.append(art)

        copy = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=9,
            valign=Gtk.Align.END,
            hexpand=True,
        )
        copy.add_css_class("detail-hero-copy")
        kind_name = {
            "albums": _("ÁLBUM"),
            "playlists": _("PLAYLIST"),
            "artists": _("ARTISTA"),
        }.get(item.kind, _("COLEÇÃO"))
        eyebrow = Gtk.Label(label=kind_name, xalign=0)
        eyebrow.add_css_class("detail-eyebrow")
        copy.append(eyebrow)
        title = Gtk.Label(label=item.title, xalign=0, wrap=True)
        title.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        title.add_css_class("detail-title")
        copy.append(title)
        copy.append(self._detail_metadata(item, tracks))
        copy.append(self._detail_actions(item, tracks))
        hero.append(copy)
        return hero

    @staticmethod
    def _duration_text(item: LibraryItem) -> str:
        match = re.search(r"(?<!\d)(?:(?:\d+):)?[0-5]?\d:[0-5]\d(?!\d)", item.subtitle or "")
        return match.group(0) if match else "—"

    @classmethod
    def _duration_seconds(cls, item: LibraryItem) -> int:
        value = cls._duration_text(item)
        if value == "—":
            return 0
        parts = [int(part) for part in value.split(":")]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        return parts[0] * 60 + parts[1]

    @staticmethod
    def _duration_summary(seconds: int) -> str:
        if seconds <= 0:
            return ""
        hours, remainder = divmod(seconds, 3600)
        minutes = remainder // 60
        if hours:
            return ngettext(
                "{hours} hora {minutes} min", "{hours} horas {minutes} min", hours
            ).format(hours=hours, minutes=minutes)
        return _("{minutes} min").format(minutes=minutes)

    def _detail_metadata(self, item: LibraryItem, tracks: list[LibraryItem]) -> Gtk.Widget:
        raw_parts = [
            part.strip()
            for part in re.split(r"\s*[\u2022·]\s*", item.subtitle or "")
            if part.strip()
        ]
        ignored = {"álbum", "album", "playlist", "playlist automática"}
        parts = [
            part
            for part in raw_parts
            if part.casefold() not in ignored
            and not re.search(r"\b(?:itens?|músicas?)\b", part, re.IGNORECASE)
        ]
        creator = parts[0] if parts else (item.subtitle or "YouTube Music")
        extras = parts[1:]
        initials = "".join(word[0] for word in creator.split()[:2] if word)[:2].upper() or "YT"

        meta = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        meta.add_css_class("detail-metadata")
        avatar = Gtk.Label(label=initials, width_chars=2)
        avatar.add_css_class("detail-avatar")
        meta.append(avatar)
        creator_label = CreditsLabel(self.navigate_credit, ellipsize=3)
        # Albums credit their artist; playlists credit their owner, not a link.
        if item.kind == "albums" and not item_credits(item) and creator:
            item = replace(item, links=(("search", creator, creator),))
        creator_label.show_item(item if item.kind != "playlists" else None, creator)
        creator_label.add_css_class("detail-creator")
        meta.append(creator_label)

        count = len(tracks)
        summary = ngettext("{count} música", "{count} músicas", count).format(count=count)
        duration = self._duration_summary(sum(self._duration_seconds(track) for track in tracks))
        for value in [*extras, summary, duration]:
            if not value:
                continue
            dot = Gtk.Label(label=_("•"))
            dot.add_css_class("detail-meta-muted")
            meta.append(dot)
            label = Gtk.Label(label=value, ellipsize=3)
            label.add_css_class("detail-meta-muted")
            meta.append(label)
        return meta

    def _detail_actions(self, item: LibraryItem, tracks: list[LibraryItem]) -> Gtk.Widget:
        actions = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            column_spacing=10,
            row_spacing=8,
            min_children_per_line=1,
            max_children_per_line=5,
            homogeneous=False,
            halign=Gtk.Align.START,
        )
        actions.add_css_class("detail-actions")

        play = media_play_button(_("Reproduzir"), size="lg")
        play.set_sensitive(bool(tracks))
        play.connect("clicked", lambda *_: tracks and self.set_queue(tracks, 0))
        actions.append(play)

        shuffle = icon_button(
            "media-playlist-shuffle-symbolic", _("Reproduzir em ordem aleatória"), size="lg"
        )
        shuffle.set_sensitive(bool(tracks))
        shuffle.connect("clicked", lambda *_: self._play_shuffled(tracks))
        actions.append(shuffle)

        saved = any(saved_item.id == item.id for saved_item in self.sections.get(item.kind, []))
        save_state = {"saved": saved}
        save = icon_button(
            "object-select-symbolic" if saved else "bookmark-new-symbolic",
            _("Salvo na biblioteca") if saved else _("Salvar na biblioteca"),
            size="lg",
        )
        set_icon_selected(save, saved)
        save.connect(
            "clicked",
            lambda *_: self._toggle_detail_collection(item, tracks, save, save_state),
        )
        actions.append(save)

        download = icon_button("folder-download-symbolic", _("Baixar"), size="lg")
        download.set_sensitive(bool(tracks))
        download.connect("clicked", lambda *_: self._download_items(tracks))
        actions.append(download)
        actions.append(self._detail_more_button(item, tracks))
        return actions

    def _detail_more_button(self, item: LibraryItem, tracks: list[LibraryItem]) -> Gtk.Widget:
        """Queue the collection, or manage the playlist or subscription."""
        more = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text=_("Mais opções"))
        style_icon_button(more, "lg")
        menu = Gtk.Popover()
        menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        menu_box.add_css_class("detail-menu")
        if tracks and item.kind in ("albums", "playlists"):
            for label, icon, next_up in (
                (_("Tocar a seguir"), "media-skip-forward-symbolic", True),
                (_("Adicionar à fila"), "view-list-symbolic", False),
            ):
                queue = menu_action_button(label, icon)
                queue.connect(
                    "clicked",
                    lambda *_, first=next_up: (menu.popdown(), self.enqueue(tracks, next_up=first)),
                )
                menu_box.append(queue)
        if item.kind == "playlists":
            menu_box.append(Gtk.Separator())
            rename = menu_action_button(_("Renomear playlist"), "document-edit-symbolic")
            rename.connect(
                "clicked", lambda *_: (menu.popdown(), self.rename_playlist_dialog(item))
            )
            menu_box.append(rename)
            delete = menu_action_button(
                _("Excluir playlist"), "user-trash-symbolic", destructive=True
            )
            delete.connect(
                "clicked", lambda *_: (menu.popdown(), self.delete_playlist_dialog(item))
            )
            menu_box.append(delete)
        elif item.kind == "artists":
            unsubscribe = menu_action_button(_("Cancelar inscrição"), "contact-new-symbolic")
            unsubscribe.connect(
                "clicked", lambda *_: (menu.popdown(), self._toggle_artist(item, False))
            )
            menu_box.append(unsubscribe)
        menu.set_child(menu_box)
        more.set_popover(menu)
        more.set_visible(menu_box.get_first_child() is not None)
        return more

    def _toggle_detail_collection(
        self,
        item: LibraryItem,
        tracks: list[LibraryItem],
        button: Gtk.Button,
        state: dict,
    ) -> None:
        save = not state["saved"]

        def completed() -> None:
            state["saved"] = save
            button.set_icon_name("object-select-symbolic" if save else "bookmark-new-symbolic")
            button.set_tooltip_text(_("Salvo na biblioteca") if save else _("Salvar na biblioteca"))
            set_icon_selected(button, save)

        self.save_collection(item, tracks, save, completed)

    def save_collection(
        self, item: LibraryItem, tracks: list[LibraryItem], save: bool, completed=None
    ) -> None:
        """Save an album or playlist to the library, or remove it."""
        playlist_id = item.playlist_id or next(
            (track.playlist_id for track in tracks if track.playlist_id), None
        )
        if item.kind == "playlists":
            playlist_id = playlist_id or item.id
        if not playlist_id:
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=_("O YouTube Music não informou como salvar este item"),
                    timeout=4,
                )
            )
            return
        message = _("Adicionado à biblioteca") if save else _("Removido da biblioteca")

        def done(_result) -> None:
            if completed:
                completed()
            self.sync()

        self._mutate(
            "like-collection" if save else "unlike-collection",
            playlist_id,
            lambda client: self.youtube.set_collection_saved(item, playlist_id, save, client),
            message,
            done,
        )

    def _play_shuffled(self, tracks: list[LibraryItem]) -> None:
        if not tracks:
            return
        shuffled = list(tracks)
        random.shuffle(shuffled)
        self.set_queue(shuffled, 0)

    def _download_items(self, tracks: list[LibraryItem]) -> None:
        playable = [
            track
            for track in tracks
            if track.kind in ("songs", "videos") and not track.id.startswith("local:")
        ]
        if not playable:
            self.toast_overlay.add_toast(
                Adw.Toast(title=_("Nenhuma faixa disponível para download"))
            )
            return
        for track in playable:
            self.downloads.start(track)
        self.toast_overlay.add_toast(
            Adw.Toast(
                title=ngettext(
                    "{count} download iniciado",
                    "{count} downloads adicionados à fila",
                    len(playable),
                ).format(count=len(playable))
            )
        )
