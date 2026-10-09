"""An album or playlist page: loading, the tracklist and per-track actions."""

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
from .track_rows import TRACK_COVER_SIZE, DetailTrackRow

LOGGER = logging.getLogger(__name__)


def radio_queue(seed: LibraryItem, items: list[LibraryItem]) -> list[LibraryItem]:
    """Start the radio with its seed track, without repeating it."""
    return [seed, *(item for item in items if item.id != seed.id)]


class WindowDetailMixin:
    def _loaded_page_visible(self, name: str, placeholder: Gtk.Widget | None) -> bool | None:
        """Decide what an asynchronous page load may do when its result arrives.

        None: a newer load replaced the placeholder, so this result is stale.
        False: the user moved to another page; update this one without
        switching to it, so a late reply never pulls them back.
        True: the placeholder is still on screen; show the result.
        """
        if placeholder is None:
            return True
        if self.stack.get_child_by_name(name) is not placeholder:
            return None
        return self.stack.get_visible_child() is placeholder

    def _open_home_item(self, item: LibraryItem, section_items: list[LibraryItem]) -> None:
        if item.kind != "songs":
            self.open_item(item)
            return
        playable = [candidate for candidate in section_items if candidate.kind == "songs"]
        self.set_queue(playable, playable.index(item) if item in playable else 0)

    def _show_detail(
        self,
        item: LibraryItem,
        tracks: list[LibraryItem] | None,
        error: str | None,
        placeholder: Gtk.Widget | None = None,
    ):
        show = self._loaded_page_visible("detail", placeholder)
        if show is None:
            return False
        old = self.stack.get_child_by_name("detail")
        if old:
            self.stack.remove(old)
        self.detail_track_rows = []
        if error:
            page = Adw.StatusPage(
                icon_name="dialog-error-symbolic",
                title=_("Não foi possível abrir"),
                description=escape(error),
            )
        else:
            page = self._detail_page(item, tracks or [])
        self.stack.add_named(page, "detail")
        if show:
            self.stack.set_visible_child_name("detail")
        self._refresh_detail_track_states()
        return False

    def _detail_page(self, item: LibraryItem, tracks: list[LibraryItem]) -> Gtk.Widget:
        for track in tracks:
            if not track.thumbnail and item.thumbnail:
                track.thumbnail = item.thumbnail
        surface = self._detail_backdrop(item)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=28, hexpand=True)
        content.add_css_class("detail-page")
        content.add_css_class("app-page")
        content.add_css_class("app-page-content")
        content.set_valign(Gtk.Align.START)
        content.append(self._detail_hero(item, tracks))
        content.append(self._detail_tracklist(item, tracks))
        clamp = Adw.Clamp(maximum_size=1120, tightening_threshold=900)
        clamp.set_hexpand(True)
        clamp.set_child(content)
        surface.add_overlay(clamp)
        surface.set_measure_overlay(clamp, True)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(surface)
        return scroll

    def _detail_backdrop(self, item: LibraryItem) -> Gtk.Overlay:
        """The collection's cover, faded behind the whole page."""
        surface = Gtk.Overlay(hexpand=True)
        surface.add_css_class("detail-surface")
        background = Gtk.Box(hexpand=True, vexpand=True)
        background.add_css_class("detail-background")
        surface.set_child(background)
        if item.thumbnail:
            backdrop = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
            backdrop.set_hexpand(True)
            backdrop.set_vexpand(True)
            backdrop.set_opacity(0.13)
            backdrop.set_can_target(False)
            backdrop.add_css_class("detail-backdrop")
            self._load_artwork(item.thumbnail, backdrop, size=1280)
            surface.add_overlay(backdrop)
        shade = Gtk.Box(hexpand=True, vexpand=True)
        shade.set_can_target(False)
        shade.add_css_class("detail-backdrop-shade")
        surface.add_overlay(shade)
        return surface

    def _detail_tracklist(self, item: LibraryItem, tracks: list[LibraryItem]) -> Gtk.Widget:
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
        return tracklist

    @staticmethod
    def _detail_track_header() -> Gtk.Widget:
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.add_css_class("detail-track-header")
        number = Gtk.Label(label=_("#"), width_chars=3, xalign=1)
        header.append(number)
        header.append(Gtk.Box(width_request=TRACK_COVER_SIZE))
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
        row = DetailTrackRow(self, collection, source, track, index)
        self.detail_track_rows.append(row)
        return row.widget

    def _refresh_detail_track_states(self) -> None:
        for row in self.detail_track_rows:
            row.update()

    def _track_menu(
        self, collection: LibraryItem, track: LibraryItem, popover: Gtk.Popover
    ) -> Gtk.Widget:
        """Per-track actions: the shared item menu, aware of the open collection."""
        return self.item_menu(track, popover, collection=collection)

    def _search_for(self, query: str) -> None:
        self.search_entry.set_text(query)
        self.search(query)

    def _start_track_radio(self, track: LibraryItem) -> None:
        self.toast_overlay.add_toast(
            Adw.Toast(title=_("Preparando a rádio de {title}…").format(title=track.title))
        )

        def done(items: list[LibraryItem], error: str | None) -> bool:
            if error:
                self.toast_overlay.add_toast(
                    Adw.Toast(
                        title=_("Não foi possível iniciar a rádio: {error}").format(error=error)
                    )
                )
                return False
            self.set_queue(radio_queue(track, items), 0)
            return False

        def worker() -> None:
            try:
                items = self.youtube.radio(track.id)
            except Exception as exc:
                GLib.idle_add(done, [], str(exc))
                return
            GLib.idle_add(done, items, None)

        threading.Thread(target=worker, daemon=True, name="track-radio").start()
