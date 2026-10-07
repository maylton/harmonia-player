"""The header bar: search, back, compact navigation, sync and account."""

from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk

from ..i18n import _
from ..ui import icon_button, menu_action_button, set_icon_selected, style_icon_button
from .navigation import navigation_entries


def build_header(window) -> None:
    window.header = Adw.HeaderBar()
    window.header.set_title_widget(_search_entry(window))
    window.back = icon_button("go-previous-symbolic", _("Voltar"), size="md")
    window.back.connect("clicked", lambda *_: window._go_back())
    window.back.set_visible(False)
    window.header.pack_start(window.back)
    window.compact_menu = _compact_menu(window)
    window.header.pack_start(window.compact_menu)
    refresh = icon_button("view-refresh-symbolic", _("Sincronizar biblioteca"), size="md")
    refresh.connect(
        "clicked", lambda *_: (window.sync(), window.sync_home(), window.sync_explore())
    )
    window.header.pack_start(refresh)
    window.header.pack_end(_account_button(window))
    window.root.append(window.header)


def _search_entry(window) -> Gtk.SearchEntry:
    entry = Gtk.SearchEntry(placeholder_text=_("Pesquisar músicas, álbuns, artistas…"))
    entry.set_size_request(380, -1)
    entry.connect("activate", lambda *_: window.search(entry.get_text()))
    entry.connect("search-changed", window._search_text_changed)
    # Suggestions must never take the keyboard from the entry: an autohide
    # popover grabs focus when it opens, which moved typing into its
    # buttons (spaces activated suggestions and the caret jumped).
    suggestions = Gtk.Popover(autohide=False, has_arrow=False)
    suggestions.set_can_focus(False)
    suggestions.set_parent(entry)
    suggestions.add_css_class("search-suggestions")
    entry.connect("stop-search", lambda *_: suggestions.popdown())
    focus = Gtk.EventControllerFocus()
    focus.connect("leave", lambda *_: suggestions.popdown())
    entry.add_controller(focus)
    window.search_entry = entry
    window.search_suggestions = suggestions
    return entry


def _compact_menu(window) -> Gtk.MenuButton:
    """The navigation as a menu, shown instead of the pane on narrow windows."""
    button = Gtk.MenuButton(icon_name="open-menu-symbolic", tooltip_text=_("Navegação"))
    style_icon_button(button, "md")
    button.set_visible(False)
    menu = Gtk.Popover()
    menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    menu_box.add_css_class("compact-menu")
    for _key, label, icon, callback in navigation_entries(window):
        entry = menu_action_button(label, icon)
        entry.connect("clicked", lambda _button, action=callback: (menu.popdown(), action()))
        menu_box.append(entry)
    menu.set_child(menu_box)
    button.set_popover(menu)
    return button


def _account_button(window) -> Gtk.Button:
    account = Gtk.Button(tooltip_text=_("Conta"))
    style_icon_button(account, "md")
    set_icon_selected(account, True)
    account.add_css_class("account-avatar-button")
    account.set_overflow(Gtk.Overflow.HIDDEN)
    avatar_stack = Gtk.Overlay()
    avatar_stack.set_size_request(30, 30)
    avatar_stack.set_overflow(Gtk.Overflow.HIDDEN)
    avatar_stack.add_css_class("account-avatar-frame")
    window.account_avatar_fallback = Gtk.Image.new_from_icon_name("avatar-default-symbolic")
    window.account_avatar_fallback.set_pixel_size(18)
    avatar_stack.set_child(window.account_avatar_fallback)
    window.account_avatar_picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER)
    window.account_avatar_picture.set_can_shrink(True)
    window.account_avatar_picture.set_hexpand(True)
    window.account_avatar_picture.set_vexpand(True)
    window.account_avatar_picture.set_opacity(0)
    window.account_avatar_picture.add_css_class("account-avatar-picture")
    avatar_stack.add_overlay(window.account_avatar_picture)
    account.set_child(avatar_stack)
    window.account_button = account
    account.connect("clicked", lambda *_: window.login_dialog())
    return account
