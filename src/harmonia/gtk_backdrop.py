"""Keep a Windows window material (Mica, Acrylic) behind every Harmonia window."""

from __future__ import annotations

import logging

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk  # noqa: E402

from . import host  # noqa: E402

LOGGER = logging.getLogger(__name__)
# Windows with a material drop GTK's client-side shadow (see windows11.css):
# DWM draws the native shadow and rounded corners instead, and a GTK shadow
# would show as a band of material around the window.
CSS_CLASS = "harmonia-backdrop"


class GtkWindowBackdrops:
    """Applies the chosen material to each toplevel as it is realized.

    ``active`` tells whether the main window got it; when it did not
    (Windows 10, older Windows 11 builds) the theme must stay opaque.
    """

    def __init__(self) -> None:
        self.kind = "none"
        self.active = False
        self._windows: set[int] = set()
        if not host.WINDOW_BACKDROPS:
            return
        self._toplevels = Gtk.Window.get_toplevels()
        self._toplevels.connect("items-changed", lambda *_: self._watch_toplevels())
        self._style = Adw.StyleManager.get_default()
        self._style.connect("notify::dark", lambda *_: self._update_dark())

    def set_kind(self, kind: str, main_window: Gtk.Window) -> bool:
        """Use ``kind`` ("mica", "acrylic" or "none"); True if the main window shows it."""
        if not host.WINDOW_BACKDROPS:
            return False
        self.kind = kind
        self._watch_toplevels()
        self.active = self._apply(main_window)
        return self.active

    def _watch_toplevels(self) -> None:
        for index in range(self._toplevels.get_n_items()):
            window = self._toplevels.get_item(index)
            if id(window) in self._windows:
                continue
            self._windows.add(id(window))
            window.connect("realize", self._apply)
            window.connect("destroy", lambda window: self._windows.discard(id(window)))
            if window.get_realized():
                self._apply(window)

    def _hwnd(self, window: Gtk.Window) -> int | None:
        from .gtk_win32 import window_handle

        return window_handle(window)

    def _apply(self, window: Gtk.Window) -> bool:
        from . import windows_backdrop

        hwnd = self._hwnd(window)
        if hwnd is None:
            return False
        applied = False
        if self.kind != "none":
            try:
                applied = windows_backdrop.apply(hwnd, self.kind, self._style.get_dark())
            except OSError:
                LOGGER.debug("O DWM recusou o material da janela", exc_info=True)
        else:
            windows_backdrop.remove(hwnd)
        if applied:
            window.add_css_class(CSS_CLASS)
        else:
            window.remove_css_class(CSS_CLASS)
        return applied

    def _update_dark(self) -> None:
        from . import windows_backdrop

        dark = self._style.get_dark()
        for index in range(self._toplevels.get_n_items()):
            hwnd = self._hwnd(self._toplevels.get_item(index))
            if hwnd is not None:
                windows_backdrop.set_dark(hwnd, dark)
