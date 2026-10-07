"""The navigation pane."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from ..i18n import _
from .navigation import YOUR_MUSIC_STARTS_AT, navigation_entries


def build_sidebar(window) -> None:
    window.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    window.sidebar.add_css_class("sidebar")
    window.sidebar.set_size_request(230, -1)
    window.sidebar.set_hexpand(False)
    window.sidebar.set_halign(Gtk.Align.START)
    # The navigation list scrolls so the sidebar never dictates the window's
    # minimum height; the player bar stays visible on short screens.
    nav = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    nav_scroll = Gtk.ScrolledWindow(
        hscrollbar_policy=Gtk.PolicyType.NEVER,
        vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
        vexpand=True,
    )
    nav_scroll.add_css_class("sidebar-scroll")
    nav_scroll.set_child(nav)
    window.sidebar_scroll = nav_scroll
    nav.append(_brand())
    window.nav_buttons: dict[str, Gtk.Button] = {}
    for key, label, icon, callback in navigation_entries(window):
        if key == YOUR_MUSIC_STARTS_AT:
            heading = Gtk.Label(label=_("SUAS MÚSICAS"), xalign=0)
            heading.add_css_class("sidebar-heading")
            nav.append(heading)
        nav.append(_sidebar_button(window, key, label, icon, callback))
    window.sidebar.append(nav_scroll)
    create = Gtk.Button(label=_("Nova playlist"), icon_name="list-add-symbolic")
    create.add_css_class("sidebar-create")
    create.connect("clicked", lambda *_: window.create_playlist_dialog())
    window.sidebar.append(create)
    window.main_shell.append(window.sidebar)
    window.sidebar_separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
    window.sidebar_separator.set_hexpand(False)
    window.main_shell.append(window.sidebar_separator)


def _brand() -> Gtk.Widget:
    brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    brand.add_css_class("sidebar-brand")
    logo = Gtk.Image.new_from_icon_name("audio-headphones-symbolic")
    logo.set_pixel_size(24)
    brand.append(logo)
    name = Gtk.Label(label=_("Harmonia"), xalign=0)
    name.add_css_class("sidebar-brand-title")
    brand.append(name)
    return brand


def _sidebar_button(window, key: str, label: str, icon: str, callback) -> Gtk.Button:
    button = Gtk.Button()
    button.add_css_class("sidebar-item")
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    row.append(Gtk.Image.new_from_icon_name(icon))
    text = Gtk.Label(label=label, xalign=0, hexpand=True)
    row.append(text)
    button.set_child(row)
    button.connect("clicked", lambda *_: callback())
    window.nav_buttons[key] = button
    return button
