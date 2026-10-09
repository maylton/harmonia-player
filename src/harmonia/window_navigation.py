"""Top-level page switching: the active navigation entry and going back."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk


class WindowNavigationMixin:
    def _set_active_nav(self, key: str) -> None:
        viewport = self.sidebar_scroll.get_child()
        for name, button in self.nav_buttons.items():
            if name == key:
                button.add_css_class("sidebar-active")
                # Keep the active entry visible when the navigation list scrolls.
                if isinstance(viewport, Gtk.Viewport) and hasattr(viewport, "scroll_to"):
                    viewport.scroll_to(button, None)
            else:
                button.remove_css_class("sidebar-active")

    def show_library(self) -> None:
        self.main_view = "library"
        self.back.set_visible(False)
        self._render()
        self.stack.set_visible_child_name("library")
        self._set_active_nav("library")

    def _go_back(self) -> None:
        if self.main_view == "home":
            self.show_home()
        elif self.main_view.startswith("explore"):
            self.show_explore()
        elif self.main_view == "history" or self.main_view == "insights":
            self.show_home()
        elif self.main_view == "downloads":
            self.show_library()
        elif self.main_view == "settings":
            self.show_home()
        elif self.main_view == "artist-section" and self._artist_current_item:
            self._open_artist(self._artist_current_item)
        else:
            self.show_library()

    def show_home(self) -> None:
        self.main_view = "home"
        self.back.set_visible(False)
        self._render_home()
        self.stack.set_visible_child_name("home")
        self._set_active_nav("home")
