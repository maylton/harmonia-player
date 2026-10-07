"""Keep a Windows window material (Mica, Acrylic) behind every Harmonia window."""

from __future__ import annotations

import logging

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from . import host  # noqa: E402
from .ui import set_css_class  # noqa: E402

LOGGER = logging.getLogger(__name__)
# Windows with a material drop GTK's client-side shadow (see windows11.css):
# DWM draws the native shadow and rounded corners instead, and a GTK shadow
# would show as a band of material around the window.
CSS_CLASS = "harmonia-backdrop"
POPOVER_CSS_CLASS = "harmonia-backdrop-popover"


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

    def attach_popover(self, popover: Gtk.Popover) -> None:
        """Give a popover the window's material while it is shown.

        Popovers are native windows of their own on Windows, so the material
        behind the main window does not reach them. They drop the arrow and
        GTK's shadow while a material is on, so the material covers exactly
        the popover and DWM draws the rounded corners and the shadow.
        """
        if not host.WINDOW_BACKDROPS:
            return
        popover.connect("map", self._apply_popover)

    def _apply_popover(self, popover: Gtk.Popover) -> None:
        from . import windows_backdrop

        hwnd = self._hwnd(popover)
        applied = False
        if hwnd is not None and self.kind != "none" and self.active:
            try:
                applied = windows_backdrop.apply(
                    hwnd, windows_backdrop.TRANSIENT, self._style.get_dark()
                )
            except OSError:
                LOGGER.debug("O DWM recusou o material do popover", exc_info=True)
        popover.set_has_arrow(not applied)
        set_css_class(popover, POPOVER_CSS_CLASS, applied)

    def _watch_toplevels(self) -> None:
        for index in range(self._toplevels.get_n_items()):
            window = self._toplevels.get_item(index)
            if id(window) in self._windows:
                continue
            self._windows.add(id(window))
            window.connect("realize", self._apply)
            window.connect("unrealize", self._unwatch)
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
            windows_backdrop.watch(
                hwnd,
                lambda message, wparam: self._on_message(window, message, wparam),
                LOGGER.debug if LOGGER.isEnabledFor(logging.DEBUG) else None,
            )
        else:
            window.remove_css_class(CSS_CLASS)
        return applied

    def _on_message(self, window: Gtk.Window, message: int, wparam: int) -> None:
        from . import windows_backdrop

        if message in windows_backdrop.RESET_MESSAGES:
            # Composition or display changes (fullscreen games) leave DWM's
            # material stuck until the window's visual is rebuilt.
            window._harmonia_needs_rebuild = True
        if windows_backdrop.needs_reapply(message, wparam):
            self._schedule_restore(window)
        elif message == windows_backdrop.WM_ACTIVATE:
            self._watch_cloaking(window)

    def _watch_cloaking(self, window: Gtk.Window) -> None:
        """While out of focus, notice if Windows hides the window (another desktop)."""
        from . import windows_backdrop

        def check() -> bool:
            hwnd = self._hwnd(window)
            if hwnd is None or window.is_active():
                return GLib.SOURCE_REMOVE
            if windows_backdrop.is_cloaked(hwnd):
                window._harmonia_needs_rebuild = True
            return GLib.SOURCE_CONTINUE

        if not getattr(window, "_harmonia_cloak_watch", 0):
            window._harmonia_cloak_watch = GLib.timeout_add(
                700, lambda: check() or setattr(window, "_harmonia_cloak_watch", 0)
            )

    def _schedule_restore(self, window: Gtk.Window) -> None:
        """Queue one restore for a burst of messages (focus, display, composition)."""
        if self.kind == "none" or getattr(window, "_harmonia_restore_queued", False):
            return
        window._harmonia_restore_queued = True
        GLib.idle_add(self._restore, window)

    def _restore(self, window: Gtk.Window) -> bool:
        """Set the material again and refresh the frame, as minimize and restore would."""
        from . import windows_backdrop

        window._harmonia_restore_queued = False
        if self.kind != "none" and self._apply(window):
            hwnd = self._hwnd(window)
            if hwnd is not None:
                if getattr(window, "_harmonia_needs_rebuild", False):
                    window._harmonia_needs_rebuild = False
                    windows_backdrop.rebuild(hwnd)
                    LOGGER.debug("visual da janela recriado (tela cheia ou outra área de trabalho)")
                windows_backdrop.refresh_frame(hwnd)
                window.queue_draw()
                if LOGGER.isEnabledFor(logging.DEBUG):
                    LOGGER.debug("material restaurado: %s", windows_backdrop.backdrop_state(hwnd))
                    GLib.timeout_add(500, self._log_appearance, window)
        return GLib.SOURCE_REMOVE

    def _log_appearance(self, window: Gtk.Window) -> bool:
        """Diagnostics: DWM state and the window's own colours after a restore."""
        from . import windows_backdrop

        hwnd = self._hwnd(window)
        if hwnd is None:
            return GLib.SOURCE_REMOVE
        state = windows_backdrop.backdrop_state(hwnd)
        colors = (
            windows_backdrop.sample_window(hwnd, ((0.06, 0.5), (0.5, 0.03), (0.6, 0.55)))
            if state["foreground"]
            else "fora do primeiro plano"
        )
        LOGGER.debug("500 ms depois: %s cores (lateral, título, conteúdo)=%s", state, colors)
        return GLib.SOURCE_REMOVE

    def _unwatch(self, window: Gtk.Window) -> None:
        from . import windows_backdrop

        hwnd = self._hwnd(window)
        if hwnd is not None:
            windows_backdrop.unwatch(hwnd)

    def _update_dark(self) -> None:
        from . import windows_backdrop

        dark = self._style.get_dark()
        for index in range(self._toplevels.get_n_items()):
            hwnd = self._hwnd(self._toplevels.get_item(index))
            if hwnd is not None:
                windows_backdrop.set_dark(hwnd, dark)
