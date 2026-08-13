from __future__ import annotations

import logging
import random
import re
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from .i18n import _, ngettext
from .models import (
    ArtistPage,
    ArtistSection,
    LibraryItem,
)
from .ui import (
    action_button,
    icon_button,
    media_play_button,
    menu_action_button,
    page_header,
    page_shell,
    section_link,
    set_action_role,
    set_icon_selected,
    style_icon_button,
)

LOGGER = logging.getLogger(__name__)


class WindowDetailMixin:
    def _open_artist(self, item: LibraryItem) -> None:
        self.main_view = "artist"
        self._artist_current_item = item
        self.back.set_visible(True)
        self._set_active_nav("artists")
        status = Adw.StatusPage(
            icon_name="view-refresh-symbolic",
            title=_("Carregando {title}…").format(title=item.title),
            description=_("Buscando a página completa do artista"),
        )
        old = self.stack.get_child_by_name("artist")
        if old:
            self.stack.remove(old)
        self.stack.add_named(status, "artist")
        self.stack.set_visible_child_name("artist")

        def worker() -> None:
            try:
                page = self.youtube.artist(item.id)
                GLib.idle_add(self._show_artist, item, page, None)
            except Exception as exc:
                GLib.idle_add(self._show_artist, item, None, str(exc))

        threading.Thread(target=worker, daemon=True, name="artist-page").start()

    def _show_artist(
        self,
        item: LibraryItem,
        artist: ArtistPage | None,
        error: str | None,
    ) -> bool:
        old = self.stack.get_child_by_name("artist")
        if old:
            self.stack.remove(old)
        if error or artist is None:
            page: Gtk.Widget = Adw.StatusPage(
                icon_name="dialog-error-symbolic",
                title=_("Não foi possível abrir o artista"),
                description=error or "Resposta vazia do YouTube Music",
            )
        else:
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            surface = Gtk.Overlay()
            surface.add_css_class("artist-surface")
            base = Gtk.Box(vexpand=True)
            surface.set_child(base)
            if artist.thumbnail:
                backdrop = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
                backdrop.set_size_request(-1, 430)
                backdrop.set_valign(Gtk.Align.START)
                backdrop.set_opacity(0.18)
                backdrop.add_css_class("artist-backdrop")
                self._load_artwork(artist.thumbnail, backdrop, size=1280)
                surface.add_overlay(backdrop)
            shade = Gtk.Box(height_request=430, valign=Gtk.Align.START, hexpand=True)
            shade.add_css_class("artist-backdrop-shade")
            shade.set_can_target(False)
            surface.add_overlay(shade)

            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=30)
            content.add_css_class("artist-page")
            content.add_css_class("app-page")
            content.add_css_class("app-page-content")
            hero = Adw.WrapBox(
                orientation=Gtk.Orientation.HORIZONTAL,
                child_spacing=34,
                line_spacing=24,
                natural_line_length=940,
                wrap_policy=Adw.WrapPolicy.NATURAL,
                valign=Gtk.Align.END,
            )
            hero.add_css_class("app-page-header")
            portrait_item = LibraryItem(
                item.id, artist.title, thumbnail=artist.thumbnail, kind="artists"
            )
            portrait = self._square_cover(portrait_item, size=230, fixed=True)
            portrait.add_css_class("artist-portrait")
            hero.append(portrait)
            copy = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL, spacing=10, hexpand=True, valign=Gtk.Align.END
            )
            eyebrow = Gtk.Label(label=_("ARTISTA"), xalign=0)
            eyebrow.add_css_class("detail-eyebrow")
            copy.append(eyebrow)
            title = Gtk.Label(label=artist.title, xalign=0, wrap=True)
            title.add_css_class("artist-title")
            copy.append(title)
            if artist.subscribers:
                listeners = Gtk.Label(label=artist.subscribers, xalign=0)
                listeners.add_css_class("artist-listeners")
                copy.append(listeners)
            if artist.description:
                description = Gtk.Label(
                    label=artist.description, xalign=0, wrap=True, lines=3, ellipsize=3
                )
                description.add_css_class("artist-description")
                copy.append(description)
            actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            play = action_button(_("Reproduzir"), "media-playback-start-symbolic", role="primary")
            play.set_sensitive(bool(artist.songs))
            play.connect("clicked", lambda *_: artist.songs and self.set_queue(artist.songs, 0))
            actions.append(play)
            radio = action_button(
                _("Rádio"), "media-playlist-consecutive-symbolic", role="secondary"
            )
            radio.set_sensitive(bool(artist.songs))
            radio.connect("clicked", lambda *_: artist.songs and self.set_queue(artist.songs, 0))
            actions.append(radio)
            subscribed = {"value": artist.subscribed}
            subscribe = action_button(
                label=_("Inscrito") if artist.subscribed else "Inscrever-se",
                icon_name="object-select-symbolic" if artist.subscribed else "contact-new-symbolic",
                role="accent" if artist.subscribed else "secondary",
            )
            subscribe.connect(
                "clicked",
                lambda *_: self._toggle_artist_page_subscription(item, subscribe, subscribed),
            )
            actions.append(subscribe)
            copy.append(actions)
            hero.append(copy)
            content.append(hero)
            for section in artist.sections or []:
                content.append(self._artist_section_widget(section))
            clamp = Adw.Clamp(maximum_size=1280, tightening_threshold=1050)
            clamp.set_child(content)
            surface.add_overlay(clamp)
            surface.set_measure_overlay(clamp, True)
            scroll.set_child(surface)
            page = scroll
        self.stack.add_named(page, "artist")
        self.stack.set_visible_child_name("artist")
        return False

    def _toggle_artist_page_subscription(
        self, item: LibraryItem, button: Gtk.Button, state: dict
    ) -> None:
        subscribed = not state["value"]

        def completed(_result) -> None:
            state["value"] = subscribed
            button.set_label(_("Inscrito") if subscribed else _("Inscrever-se"))
            button.set_icon_name("object-select-symbolic" if subscribed else "contact-new-symbolic")
            set_action_role(button, "accent" if subscribed else "secondary")
            self.sync()

        self._mutate(
            "subscribe-artist" if subscribed else "unsubscribe-artist",
            item.id,
            lambda client: client.subscribe_artist(item.id, subscribed),
            _("Inscrição realizada") if subscribed else _("Inscrição cancelada"),
            completed,
        )

    def _artist_section_widget(self, section: ArtistSection) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        if section.browse_id:
            show_all = section_link(_("Mostrar tudo"), lambda: self._open_artist_section(section))
            show_all.set_halign(Gtk.Align.END)
            box.append(show_all)
        box.append(self._home_section(section.title, section.items, limit=12))
        return box

    def _open_artist_section(self, section: ArtistSection) -> None:
        self.main_view = "artist-section"
        status = Adw.StatusPage(
            icon_name="view-refresh-symbolic",
            title=_("Carregando {title}…").format(title=section.title),
        )
        old = self.stack.get_child_by_name("artist-section")
        if old:
            self.stack.remove(old)
        self.stack.add_named(status, "artist-section")
        self.stack.set_visible_child_name("artist-section")

        def worker() -> None:
            try:
                items = self.youtube.artist_section(section)
                GLib.idle_add(self._show_artist_section, section, items, None)
            except Exception as exc:
                GLib.idle_add(self._show_artist_section, section, None, str(exc))

        threading.Thread(target=worker, daemon=True, name="artist-section").start()

    def _show_artist_section(
        self, section: ArtistSection, items: list[LibraryItem] | None, error: str | None
    ) -> bool:
        old = self.stack.get_child_by_name("artist-section")
        if old:
            self.stack.remove(old)
        if error:
            page: Gtk.Widget = Adw.StatusPage(
                icon_name="dialog-error-symbolic",
                title=_("Não foi possível carregar"),
                description=error,
            )
        else:
            shell = page_shell("content", spacing=20)
            scroll, content = shell.scroll, shell.content
            content.append(page_header(section.title))
            content.append(
                self._home_section(section.title, items or [], limit=max(24, len(items or [])))
            )
            page = scroll
        self.stack.add_named(page, "artist-section")
        self.stack.set_visible_child_name("artist-section")
        return False

    def _open_home_item(self, item: LibraryItem, section_items: list[LibraryItem]) -> None:
        if item.kind != "songs":
            self.open_item(item)
            return
        playable = [candidate for candidate in section_items if candidate.kind == "songs"]
        self.set_queue(playable, playable.index(item) if item in playable else 0)

    def _show_detail(self, item: LibraryItem, tracks: list[LibraryItem] | None, error: str | None):
        old = self.stack.get_child_by_name("detail")
        if old:
            self.stack.remove(old)
        self.detail_track_rows = []
        if error:
            page = Adw.StatusPage(
                icon_name="dialog-error-symbolic",
                title=_("Não foi possível abrir"),
                description=error,
            )
        else:
            tracks = tracks or []
            for track in tracks:
                if not track.thumbnail and item.thumbnail:
                    track.thumbnail = item.thumbnail
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            surface = Gtk.Overlay(hexpand=True)
            surface.add_css_class("detail-surface")

            background = Gtk.Box(hexpand=True, vexpand=True)
            background.add_css_class("detail-background")
            surface.set_child(background)
            if item.thumbnail:
                backdrop = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
                backdrop.set_size_request(-1, 390)
                backdrop.set_valign(Gtk.Align.START)
                backdrop.set_opacity(0.13)
                backdrop.set_can_target(False)
                backdrop.add_css_class("detail-backdrop")
                self._load_artwork(item.thumbnail, backdrop, size=1280)
                surface.add_overlay(backdrop)
            shade = Gtk.Box(height_request=390, valign=Gtk.Align.START, hexpand=True)
            shade.set_can_target(False)
            shade.add_css_class("detail-backdrop-shade")
            surface.add_overlay(shade)

            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=28, hexpand=True)
            content.add_css_class("detail-page")
            content.add_css_class("app-page")
            content.add_css_class("app-page-content")
            content.set_valign(Gtk.Align.START)

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
            content.append(hero)

            tracklist = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
            tracklist.add_css_class("detail-tracklist")
            tracklist.append(self._detail_track_header())
            for index, track in enumerate(tracks, 1):
                tracklist.append(self._detail_track_row(item, tracks, track, index))
            if not tracks:
                empty = Adw.StatusPage(
                    icon_name="audio-x-generic-symbolic",
                    title=_("Nenhuma faixa"),
                    description=_("Esta coleção ainda não possui músicas disponíveis."),
                )
                empty.set_size_request(-1, 220)
                tracklist.append(empty)
            content.append(tracklist)

            clamp = Adw.Clamp(maximum_size=1120, tightening_threshold=900)
            clamp.set_hexpand(True)
            clamp.set_child(content)
            surface.add_overlay(clamp)
            surface.set_measure_overlay(clamp, True)
            scroll.set_child(surface)
            page = scroll
        self.stack.add_named(page, "detail")
        self.stack.set_visible_child_name("detail")
        self._refresh_detail_track_states()
        return False

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
            return f"{hours} {'hora' if hours == 1 else 'horas'} {minutes} min"
        return f"{minutes} min"

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
        creator_label = Gtk.Label(label=creator, ellipsize=3)
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

        download = icon_button("folder-download-symbolic", _("Fazer download"), size="lg")
        download.set_sensitive(bool(tracks))
        download.connect("clicked", lambda *_: self._download_items(tracks))
        actions.append(download)

        more = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text=_("Mais opções"))
        style_icon_button(more, "lg")
        menu = Gtk.Popover()
        menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        menu_box.add_css_class("detail-menu")
        if item.kind == "playlists":
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
        else:
            info = Gtk.Label(label=_("Mais ações para álbuns em breve"), xalign=0)
            info.add_css_class("detail-menu-note")
            menu_box.append(info)
        menu.set_child(menu_box)
        more.set_popover(menu)
        actions.append(more)
        return actions

    def _toggle_detail_collection(
        self,
        item: LibraryItem,
        tracks: list[LibraryItem],
        button: Gtk.Button,
        state: dict,
    ) -> None:
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

        save = not state["saved"]
        message = _("Adicionado à biblioteca") if save else _("Removido da biblioteca")

        def completed(_result) -> None:
            state["saved"] = save
            button.set_icon_name("object-select-symbolic" if save else "bookmark-new-symbolic")
            button.set_tooltip_text(_("Salvo na biblioteca") if save else _("Salvar na biblioteca"))
            set_icon_selected(button, save)
            self.sync()

        self._mutate(
            "like-collection" if save else "unlike-collection",
            playlist_id,
            lambda client: client.like_playlist(playlist_id, save),
            message,
            completed,
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

    @staticmethod
    def _detail_track_header() -> Gtk.Widget:
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.add_css_class("detail-track-header")
        number = Gtk.Label(label=_("#"), width_chars=3, xalign=1)
        header.append(number)
        title = Gtk.Label(label=_("TÍTULO"), xalign=0, hexpand=True)
        header.append(title)
        heart_space = Gtk.Box(width_request=36)
        header.append(heart_space)
        clock = Gtk.Image.new_from_icon_name("preferences-system-time-symbolic")
        clock.set_size_request(52, -1)
        header.append(clock)
        menu_space = Gtk.Box(width_request=36)
        header.append(menu_space)
        return header

    def _detail_track_row(
        self,
        collection: LibraryItem,
        source: list[LibraryItem],
        track: LibraryItem,
        index: int,
    ) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add_css_class("detail-track-row")
        row.add_css_class("media-row")
        row.add_css_class("media-row-detailed")
        row.set_cursor_from_name("pointer")

        leading = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        leading.set_size_request(36, 36)
        number = Gtk.Label(label=str(index), width_chars=3, xalign=1)
        number.add_css_class("detail-track-number")
        leading.add_named(number, "number")
        active_icon = Gtk.Image.new_from_icon_name("audio-volume-high-symbolic")
        active_icon.add_css_class("detail-track-accent")
        leading.add_named(active_icon, "active")
        play = Gtk.Button(
            icon_name="media-playback-start-symbolic",
            tooltip_text=_("Reproduzir {title}").format(title=track.title),
        )
        style_icon_button(play, "sm")
        play.add_css_class("detail-track-play")
        leading.add_named(play, "play")
        row.append(leading)

        title = Gtk.Label(label=track.title, xalign=0, ellipsize=3, hexpand=True)
        title.add_css_class("detail-track-title")
        row.append(title)

        liked_ids = {song.id for song in self.sections.get("songs", [])}
        liked = track.id in liked_ids
        like = Gtk.Button(
            icon_name="starred-symbolic" if liked else "non-starred-symbolic",
            tooltip_text=_("Remover das músicas curtidas") if liked else _("Curtir música"),
        )
        style_icon_button(like, "sm")
        like.add_css_class("detail-track-action")
        if liked:
            like.add_css_class("detail-track-accent")
        row.append(like)

        duration = Gtk.Label(label=self._duration_text(track), width_chars=6, xalign=1)
        duration.add_css_class("detail-track-duration")
        row.append(duration)

        options = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text=_("Opções da faixa"))
        style_icon_button(options, "sm")
        options.add_css_class("detail-track-action")
        popover = Gtk.Popover()
        option_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        option_box.add_css_class("detail-menu")
        add = menu_action_button(_("Adicionar à playlist"), "list-add-symbolic")
        add.connect("clicked", lambda *_: (popover.popdown(), self.add_to_playlist_dialog(track)))
        option_box.append(add)
        download = menu_action_button(_("Baixar"), "folder-download-symbolic")
        download.connect("clicked", lambda *_: (popover.popdown(), self._download_items([track])))
        option_box.append(download)
        if collection.kind == "playlists" and track.set_video_id:
            remove = menu_action_button(_("Remover desta playlist"), "list-remove-symbolic")
            remove.connect(
                "clicked", lambda *_: (popover.popdown(), self._remove_track(collection, track))
            )
            option_box.append(remove)
        popover.set_child(option_box)
        options.set_popover(popover)
        row.append(options)

        state = {
            "row": row,
            "track": track,
            "source": source,
            "leading": leading,
            "play": play,
            "title": title,
            "like": like,
            "liked": liked,
            "duration": duration,
            "options": options,
            "hovered": False,
        }
        self.detail_track_rows.append(state)

        play.connect("clicked", lambda *_: self._activate_detail_track(state))
        like.connect("clicked", lambda *_: self._toggle_detail_track_like(state))
        options.connect("notify::active", lambda *_: self._update_detail_track_row(state))
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: self._set_detail_track_hover(state, True))
        motion.connect("leave", lambda *_: self._set_detail_track_hover(state, False))
        row.add_controller(motion)
        click = Gtk.GestureClick(button=1)
        click.connect(
            "released", lambda _gesture, _press, _x, _y: self._activate_detail_track(state)
        )
        row.add_controller(click)
        self._update_detail_track_row(state)
        return row

    def _set_detail_track_hover(self, state: dict, hovered: bool) -> None:
        state["hovered"] = hovered
        self._update_detail_track_row(state)

    def _activate_detail_track(self, state: dict) -> None:
        track = state["track"]
        active = (
            getattr(self, "current_item", None) is not None and self.current_item.id == track.id
        )
        if active and self._stream_ready:
            self._toggle_player()
            return
        source = state["source"]
        self.set_queue(source, source.index(track))

    def _toggle_detail_track_like(self, state: dict) -> None:
        state["liked"] = not state["liked"]
        self._update_detail_track_row(state)
        self._toggle_song(state["track"], state["liked"])

    def _update_detail_track_row(self, state: dict) -> None:
        track = state["track"]
        active = (
            getattr(self, "current_item", None) is not None and self.current_item.id == track.id
        )
        playing = active and self.player.playing
        hovered = state["hovered"]
        if active:
            state["row"].add_css_class("detail-track-current")
            state["title"].add_css_class("detail-track-accent")
            state["duration"].add_css_class("detail-track-accent")
        else:
            state["row"].remove_css_class("detail-track-current")
            state["title"].remove_css_class("detail-track-accent")
            state["duration"].remove_css_class("detail-track-accent")
        state["leading"].set_visible_child_name(
            "play" if hovered else ("active" if active else "number")
        )
        state["play"].set_icon_name(
            "media-playback-pause-symbolic" if playing else "media-playback-start-symbolic"
        )
        state["like"].set_icon_name(
            "starred-symbolic" if state["liked"] else "non-starred-symbolic"
        )
        if state["liked"]:
            state["like"].add_css_class("detail-track-accent")
        else:
            state["like"].remove_css_class("detail-track-accent")
        show_like = hovered or state["liked"]
        show_options = hovered or state["options"].get_active()
        state["like"].set_opacity(1.0 if show_like else 0.0)
        state["like"].set_can_target(show_like)
        state["options"].set_opacity(1.0 if show_options else 0.0)
        state["options"].set_can_target(show_options)

    def _refresh_detail_track_states(self) -> None:
        for state in self.detail_track_rows:
            self._update_detail_track_row(state)
