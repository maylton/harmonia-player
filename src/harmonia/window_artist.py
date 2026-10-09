"""The artist page and its "show all" sections."""

from __future__ import annotations

import threading
from html import escape

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from .i18n import _
from .models import ArtistPage, ArtistSection, LibraryItem
from .ui import action_button, page_header, page_shell, section_link, set_action_role


class WindowArtistMixin:
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
                GLib.idle_add(self._show_artist, item, page, None, status)
            except Exception as exc:
                GLib.idle_add(self._show_artist, item, None, str(exc), status)

        threading.Thread(target=worker, daemon=True, name="artist-page").start()

    def _show_artist(
        self,
        item: LibraryItem,
        artist: ArtistPage | None,
        error: str | None,
        placeholder: Gtk.Widget | None = None,
    ) -> bool:
        show = self._loaded_page_visible("artist", placeholder)
        if show is None:
            return False
        old = self.stack.get_child_by_name("artist")
        if old:
            self.stack.remove(old)
        if error or artist is None:
            page: Gtk.Widget = Adw.StatusPage(
                icon_name="dialog-error-symbolic",
                title=_("Não foi possível abrir o artista"),
                description=escape(error or _("Resposta vazia do YouTube Music")),
            )
        else:
            page = self._artist_page(item, artist)
        self.stack.add_named(page, "artist")
        if show:
            self.stack.set_visible_child_name("artist")
        return False

    def _artist_page(self, item: LibraryItem, artist: ArtistPage) -> Gtk.Widget:
        surface = self._artist_backdrop(artist)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=30)
        content.add_css_class("artist-page")
        content.add_css_class("app-page")
        content.add_css_class("app-page-content")
        content.append(self._artist_hero(item, artist))
        for section in artist.sections or []:
            content.append(self._artist_section_widget(section))
        clamp = Adw.Clamp(maximum_size=1280, tightening_threshold=1050)
        clamp.set_child(content)
        surface.add_overlay(clamp)
        surface.set_measure_overlay(clamp, True)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(surface)
        return scroll

    def _artist_backdrop(self, artist: ArtistPage) -> Gtk.Overlay:
        """The artist's photo, faded behind the top of the page."""
        surface = Gtk.Overlay()
        surface.add_css_class("artist-surface")
        surface.set_child(Gtk.Box(vexpand=True))
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
        return surface

    def _artist_hero(self, item: LibraryItem, artist: ArtistPage) -> Gtk.Widget:
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
        copy.append(self._artist_actions(item, artist))
        hero.append(copy)
        return hero

    def _artist_actions(self, item: LibraryItem, artist: ArtistPage) -> Gtk.Widget:
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        play = action_button(_("Reproduzir"), "media-playback-start-symbolic", role="primary")
        play.set_sensitive(bool(artist.songs))
        play.connect("clicked", lambda *_: artist.songs and self.set_queue(artist.songs, 0))
        actions.append(play)
        radio = action_button(_("Rádio"), "media-playlist-consecutive-symbolic", role="secondary")
        radio.set_sensitive(bool(artist.songs))
        radio.connect("clicked", lambda *_: artist.songs and self.set_queue(artist.songs, 0))
        actions.append(radio)
        subscribed = {"value": artist.subscribed}
        subscribe = action_button(
            label=_("Inscrito") if artist.subscribed else _("Inscrever-se"),
            icon_name="object-select-symbolic" if artist.subscribed else "contact-new-symbolic",
            role="accent" if artist.subscribed else "secondary",
        )
        subscribe.connect(
            "clicked",
            lambda *_: self._toggle_artist_page_subscription(item, subscribe, subscribed),
        )
        actions.append(subscribe)
        return actions

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
            lambda client: self.youtube.set_artist_subscribed(item, subscribed, client),
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
                GLib.idle_add(self._show_artist_section, section, items, None, status)
            except Exception as exc:
                GLib.idle_add(self._show_artist_section, section, None, str(exc), status)

        threading.Thread(target=worker, daemon=True, name="artist-section").start()

    def _show_artist_section(
        self,
        section: ArtistSection,
        items: list[LibraryItem] | None,
        error: str | None,
        placeholder: Gtk.Widget | None = None,
    ) -> bool:
        show = self._loaded_page_visible("artist-section", placeholder)
        if show is None:
            return False
        old = self.stack.get_child_by_name("artist-section")
        if old:
            self.stack.remove(old)
        if error:
            page: Gtk.Widget = Adw.StatusPage(
                icon_name="dialog-error-symbolic",
                title=_("Não foi possível carregar"),
                description=escape(error),
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
        if show:
            self.stack.set_visible_child_name("artist-section")
        return False
