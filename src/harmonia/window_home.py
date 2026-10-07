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
    ExploreData,
    ExploreDestination,
    LibraryItem,
)
from .track_rows import HomeSongRow
from .ui import (
    page_header,
    page_shell,
)
from .window_constants import EXPLORE_ICON

LOGGER = logging.getLogger(__name__)


class WindowHomeMixin:
    def show_explore(self) -> None:
        self.main_view = "explore"
        self.back.set_visible(False)
        page = self._explore_page(
            _("Explorar"),
            _("Lançamentos, paradas e sons para cada momento."),
            self.explore_data,
        )
        old = self.stack.get_child_by_name("explore")
        if old:
            self.stack.remove(old)
        self.stack.add_named(page, "explore")
        self.stack.set_visible_child_name("explore")
        self._set_active_nav("explore")

    def _explore_page(
        self, title: str, description: str, data: ExploreData, full_sections: bool = False
    ) -> Gtk.Widget:
        shell = page_shell("content", spacing=24)
        content = shell.content
        content.append(page_header(title, description))
        if data.shortcuts:
            content.append(self._destination_section(_("Descubra"), data.shortcuts, prominent=True))
        for section in data.sections:
            limit = len(section.items) if full_sections else 12
            content.append(self._home_section(section.title, section.items, limit=limit))
        if data.genres:
            content.append(self._destination_section(_("Momentos e gêneros"), data.genres))
        if not data.sections and not data.shortcuts and not data.genres:
            content.append(
                Adw.StatusPage(
                    icon_name="view-refresh-symbolic",
                    title=_("Preparando o Explorar…"),
                    description=_("Buscando novidades no YouTube Music"),
                )
            )
        return shell.scroll

    def _destination_section(
        self, title: str, destinations: list[ExploreDestination], prominent: bool = False
    ) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.append(self._section_header(title))
        flow = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            column_spacing=12,
            row_spacing=10,
            min_children_per_line=2,
            max_children_per_line=4,
            homogeneous=True,
        )
        icons = {
            "FEmusic_new_releases": "media-optical-symbolic",
            "FEmusic_charts": "view-list-symbolic",
            "FEmusic_moods_and_genres": "applications-multimedia-symbolic",
            "FEmusic_non_music_audio": "audio-headphones-symbolic",
        }
        for destination in destinations:
            button = Gtk.Button()
            button.add_css_class("explore-shortcut" if prominent else "genre-chip")
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            if prominent:
                icon = Gtk.Image.new_from_icon_name(icons.get(destination.browse_id, EXPLORE_ICON))
                icon.set_pixel_size(22)
                row.append(icon)
            row.append(Gtk.Label(label=destination.title, xalign=0, hexpand=True, ellipsize=3))
            row.append(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            button.set_child(row)
            button.connect(
                "clicked", lambda _button, selected=destination: self.open_destination(selected)
            )
            flow.append(button)
        box.append(flow)
        return box

    def open_destination(self, destination: ExploreDestination) -> None:
        self.main_view = "explore-detail"
        self.back.set_visible(True)
        self._set_active_nav("explore")
        status = Adw.StatusPage(
            icon_name="view-refresh-symbolic",
            title=_("Carregando {title}…").format(title=destination.title),
            description=_("Consultando o YouTube Music"),
        )
        old = self.stack.get_child_by_name("discovery")
        if old:
            self.stack.remove(old)
        self.stack.add_named(status, "discovery")
        self.stack.set_visible_child_name("discovery")

        def worker():
            try:
                data = self.youtube.discovery(destination)
                GLib.idle_add(self._destination_loaded, destination, data, None, status)
            except Exception as exc:
                GLib.idle_add(self._destination_loaded, destination, None, str(exc), status)

        threading.Thread(target=worker, daemon=True).start()

    def _destination_loaded(
        self,
        destination: ExploreDestination,
        data: ExploreData | None,
        error: str | None,
        placeholder: Gtk.Widget | None = None,
    ):
        show = self._loaded_page_visible("discovery", placeholder)
        if show is None:
            return False
        old = self.stack.get_child_by_name("discovery")
        if old:
            self.stack.remove(old)
        if error:
            page = Adw.StatusPage(
                icon_name="dialog-error-symbolic",
                title=_("Não foi possível abrir"),
                description=escape(error),
            )
        else:
            page = self._explore_page(
                destination.title,
                _("Seleção atualizada pelo YouTube Music."),
                data or ExploreData([], [], []),
                full_sections=True,
            )
        self.stack.add_named(page, "discovery")
        if show:
            self.stack.set_visible_child_name("discovery")
        return False

    def _render_home(self) -> None:
        self.home_song_rows = []
        shell = page_shell("content", spacing=30, css_classes=("home-content",))
        page, content = shell.scroll, shell.content
        content.append(page_header(_("Início"), _("Escolhas feitas para você pelo YouTube Music")))
        if not self.home_sections:
            content.append(
                Adw.StatusPage(
                    icon_name="view-refresh-symbolic",
                    title=_("Preparando sua música…"),
                    description=_("Carregando recomendações personalizadas"),
                )
            )
        for section in self.home_sections:
            if section.items:
                content.append(self._home_section(section.title, section.items))
        old = self.stack.get_child_by_name("home")
        if old:
            self.stack.remove(old)
        self.stack.add_named(page, "home")

    def _home_section(self, title: str, items: list[LibraryItem], limit: int = 12) -> Gtk.Widget:
        unique_items = list({item.id: item for item in items}.values())
        if unique_items and all(item.kind == "songs" for item in unique_items):
            return self._home_song_section(title, unique_items[: max(limit, 24)])
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.add_css_class("home-shelf")
        box.set_vexpand(False)
        box.set_valign(Gtk.Align.START)
        scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.EXTERNAL,
            vscrollbar_policy=Gtk.PolicyType.NEVER,
            min_content_width=1,
            min_content_height=218,
            propagate_natural_width=False,
        )
        scroll.set_kinetic_scrolling(True)
        scroll.set_vexpand(False)
        scroll.set_valign(Gtk.Align.START)
        shelf = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        shelf.add_css_class("home-shelf-row")
        shelf.set_vexpand(False)
        shelf.set_valign(Gtk.Align.START)
        for item in items[:limit]:
            button = self._media_card_button(
                item,
                168,
                lambda selected=item, source=items: self._open_home_item(selected, source),
            )
            button.add_css_class("home-media-card-button")
            shelf.append(button)
        scroll.set_child(shelf)
        box.append(self._home_shelf_header(title, scroll))
        box.append(scroll)
        return box

    def _home_song_section(self, title: str, items: list[LibraryItem]) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.add_css_class("home-shelf")
        box.add_css_class("home-song-shelf")
        box.set_vexpand(False)
        box.set_valign(Gtk.Align.START)
        scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.EXTERNAL,
            vscrollbar_policy=Gtk.PolicyType.NEVER,
            min_content_width=1,
            min_content_height=256,
            propagate_natural_width=False,
        )
        scroll.set_kinetic_scrolling(True)
        scroll.set_vexpand(False)
        scroll.set_valign(Gtk.Align.START)
        grid = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        grid.add_css_class("home-song-grid")
        grid.set_vexpand(False)
        grid.set_valign(Gtk.Align.START)
        columns: list[Gtk.Box] = []
        for start in range(0, len(items), 4):
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            column.add_css_class("home-song-column")
            column.set_vexpand(False)
            column.set_size_request(420, -1)
            columns.append(column)
            for track in items[start : start + 4]:
                column.append(self._home_song_row(track, items))
            grid.append(column)
        scroll.set_child(grid)
        box.append(self._home_shelf_header(title, scroll, lambda: self.set_queue(items, 0)))
        box.append(scroll)

        last_width = {"value": 0}

        def resize_columns(widget: Gtk.Widget):
            viewport = widget.get_width()
            if viewport <= 1 or viewport == last_width["value"]:
                return
            last_width["value"] = viewport
            width = self._home_song_column_width(viewport)
            for column in columns:
                column.set_size_request(width, -1)

        def follow_allocation(widget: Gtk.Widget, _clock) -> bool:
            resize_columns(widget)
            return GLib.SOURCE_CONTINUE

        scroll.add_tick_callback(follow_allocation)
        return box

    @staticmethod
    def _home_song_column_width(viewport: int, gap: int = 14) -> int:
        if (viewport - gap * 2) / 3 >= 320:
            visible_columns = 3
        elif (viewport - gap) / 2 >= 320:
            visible_columns = 2
        else:
            visible_columns = 1
        if visible_columns == 1:
            return max(280, int(viewport * 0.9))
        return int((viewport - gap * (visible_columns - 1)) / visible_columns)

    def _home_song_row(self, track: LibraryItem, source: list[LibraryItem]) -> Gtk.Widget:
        row = HomeSongRow(self, track, source)
        self.home_song_rows.append(row)
        return row.widget

    def _refresh_home_song_rows(self) -> None:
        for row in self.home_song_rows:
            row.update()

    @staticmethod
    def _home_card_hover(cover: Gtk.Widget, hint: Gtk.Widget, hovered: bool) -> None:
        cover.set_opacity(0.68 if hovered else 1.0)
        hint.set_opacity(1.0 if hovered else 0.0)

    def _home_shelf_header(
        self,
        title: str,
        scroll: Gtk.ScrolledWindow,
        on_play_all=None,
    ) -> Gtk.Widget:
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("home-shelf-header")
        heading = Gtk.Label(label=title, xalign=0, hexpand=True)
        heading.add_css_class("section-title")
        if on_play_all:
            header.add_css_class("home-song-shelf-header")
            heading.add_css_class("home-song-section-title")
        header.append(heading)
        if on_play_all:
            play_all = Gtk.Button(
                label=_("Tocar tudo"),
                tooltip_text=_("Reproduzir tudo em {title}").format(title=title),
            )
            play_all.add_css_class("pill")
            play_all.add_css_class("home-play-all")
            play_all.set_valign(Gtk.Align.CENTER)
            play_all.connect("clicked", lambda *_: on_play_all())
            header.append(play_all)
        previous = Gtk.Button(
            icon_name="go-previous-symbolic",
            tooltip_text=_("Voltar em {title}").format(title=title),
        )
        next_button = Gtk.Button(
            icon_name="go-next-symbolic",
            tooltip_text=_("Avançar em {title}").format(title=title),
        )
        for button in (previous, next_button):
            button.set_valign(Gtk.Align.CENTER)
            button.add_css_class("flat")
            button.add_css_class("circular")
            button.add_css_class("home-shelf-control")
            button.add_css_class("home-shelf-nav")
            header.append(button)
        previous.connect("clicked", lambda *_: self._scroll_home_shelf(scroll, -1))
        next_button.connect("clicked", lambda *_: self._scroll_home_shelf(scroll, 1))

        adjustment = scroll.get_hadjustment()

        def update_actions(*_args):
            value = adjustment.get_value()
            upper = adjustment.get_upper()
            page_size = adjustment.get_page_size()
            previous.set_sensitive(value > adjustment.get_lower() + 1)
            next_button.set_sensitive(value + page_size < upper - 1)

        adjustment.connect("changed", update_actions)
        adjustment.connect("value-changed", update_actions)
        GLib.idle_add(update_actions)
        return header

    @staticmethod
    def _scroll_home_shelf(scroll: Gtk.ScrolledWindow, direction: int) -> None:
        adjustment = scroll.get_hadjustment()
        step = max(360.0, adjustment.get_page_size() * 0.82)
        target = adjustment.get_value() + direction * step
        maximum = max(adjustment.get_lower(), adjustment.get_upper() - adjustment.get_page_size())
        adjustment.set_value(max(adjustment.get_lower(), min(target, maximum)))

    def _initial_sync(self):
        self.show_home()
        self.sync()
        self.sync_home()
        self.sync_explore()
        return False
