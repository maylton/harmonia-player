"""Shelves of media cards and song lists, as the library, home and explore show them."""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from .i18n import _
from .models import (
    LibraryItem,
)
from .ui import (
    CreditsLabel,
    icon_button,
    link_row_subtitle,
    section_link,
    style_icon_button,
)
from .window_constants import LABELS, LIKED_ICON

LOGGER = logging.getLogger(__name__)


def _fixed_width(widget: Gtk.Widget, size: int) -> None:
    widget.set_halign(Gtk.Align.START)
    widget.set_valign(Gtk.Align.START)
    widget.set_hexpand(False)
    widget.set_size_request(size, -1)


def _cover_with_action_hint(
    cover: Gtk.Widget, item: LibraryItem, size: int
) -> tuple[Gtk.Overlay, Gtk.Widget]:
    """The artwork with the play (or open) hint shown on hover."""
    # The labels below can be wider than the artwork.  Keep the overlay on
    # the artwork's exact allocation; otherwise GtkBox stretches it to the
    # card width and a mathematically centred action appears shifted right.
    overlay = Gtk.Overlay(
        halign=Gtk.Align.START, valign=Gtk.Align.START, hexpand=False, vexpand=False
    )
    overlay.set_size_request(size, size)
    overlay.set_hexpand_set(True)
    overlay.set_vexpand_set(True)
    overlay.set_child(cover)
    hint = Gtk.CenterBox(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
    hint.set_size_request(48, 48)
    hint.set_hexpand(False)
    hint.set_vexpand(False)
    hint.add_css_class("home-cover-action")
    hint.add_css_class("media-card-action")
    hint.set_opacity(0)
    hint.set_can_target(False)
    playable = item.kind in ("songs", "videos")
    icon = Gtk.Image.new_from_icon_name(
        "media-playback-start-symbolic" if playable else "go-next-symbolic"
    )
    icon.set_pixel_size(26)
    hint.set_center_widget(icon)
    overlay.add_overlay(hint)
    return overlay, hint


def _card_labels(item: LibraryItem, size: int, navigate) -> tuple[Gtk.Label, Gtk.Widget | None]:
    """The card's title, and its credits with links (None without a subtitle)."""
    width_chars = 20 if size >= 160 else 17
    title = Gtk.Label(
        label=item.title,
        xalign=0,
        ellipsize=3,
        width_chars=width_chars,
        max_width_chars=width_chars,
    )
    title.add_css_class("card-title")
    if not item.subtitle:
        return title, None
    subtitle = CreditsLabel(
        navigate, xalign=0, ellipsize=3, width_chars=width_chars, max_width_chars=width_chars
    )
    subtitle.show_item(item)
    subtitle.add_css_class("card-subtitle")
    return title, subtitle


class WindowShelvesMixin:
    """Section headers, card shelves and song sections built from library items."""

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
    ) -> Gtk.Widget:
        """One card interaction shared by Home, Library and artist shelves.

        The subtitle sits below the button, not inside it: GtkButton claims
        clicks in the capture phase, so links inside it could never be used.
        """
        button = Gtk.Button()
        button.add_css_class("media-card-button")
        _fixed_width(button, size)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        card.add_css_class("media-card")
        card.set_size_request(size, -1)
        cover = self._square_cover(item, size=size)
        cover.add_css_class("media-card-cover")
        cover_overlay, hint = _cover_with_action_hint(cover, item, size)
        card.append(cover_overlay)
        title, subtitle = _card_labels(item, size, self.navigate_credit)
        card.append(title)
        button.set_child(card)
        button.connect("clicked", lambda *_: activate())
        # The options button overlays the card instead of living inside it,
        # because GtkButton would swallow its clicks. Hover is tracked on the
        # overlay, so moving onto the options button keeps the card hovered.
        surface = Gtk.Overlay(halign=Gtk.Align.START, valign=Gtk.Align.START)
        surface.set_child(button)
        options = self._media_card_options(item)
        if options:
            surface.add_overlay(options)

        def hovered(state: bool) -> None:
            active = bool(options and options.get_active())
            self._home_card_hover(cover, hint, state or active)
            if options:
                options.set_opacity(1.0 if state or active else 0.0)
                options.set_can_target(state or active)

        hover = Gtk.EventControllerMotion()
        hover.connect("enter", lambda *_args: hovered(True))
        hover.connect("leave", lambda *_args: hovered(False))
        surface.add_controller(hover)
        if options:
            options.connect("notify::active", lambda *_: hovered(hover.contains_pointer()))
            hovered(False)
        shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        shell.add_css_class("media-card-shell")
        _fixed_width(shell, size)
        shell.append(surface)
        if subtitle:
            shell.append(subtitle)
        return shell

    def _media_card_options(self, item: LibraryItem, *, on_cover: bool = True):
        """The shared item menu as a card overlay or as a list-row suffix."""
        options = self.item_options_button(item)
        if options is None:
            return None
        if on_cover:
            options.set_halign(Gtk.Align.END)
            options.set_valign(Gtk.Align.START)
            options.set_margin_top(8)
            options.set_margin_end(8)
            options.add_css_class("media-card-menu")
        else:
            options.set_valign(Gtk.Align.CENTER)
            style_icon_button(options, "sm")
        return options

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
            link_row_subtitle(row, item, self.navigate_credit)
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
