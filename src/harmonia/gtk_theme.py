"""Apply Harmonia themes to the GTK frontend at runtime."""

from __future__ import annotations

import logging
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk  # noqa: E402

from . import host  # noqa: E402
from .theming import (  # noqa: E402
    DEFAULT_THEME,
    Theme,
    fluent_accent,
    get_theme,
    render_gtk_css,
)

LOGGER = logging.getLogger(__name__)
STYLESHEET = Path(__file__).with_name("style.css")
COLOR_SCHEMES = {
    "system": Adw.ColorScheme.DEFAULT,
    "light": Adw.ColorScheme.FORCE_LIGHT,
    "dark": Adw.ColorScheme.FORCE_DARK,
}


def supports_css_variables() -> bool:
    """libadwaita 1.6+ on GTK 4.16+ styles itself through CSS custom properties."""
    gtk = (Gtk.get_major_version(), Gtk.get_minor_version())
    return gtk >= (4, 16) and Adw.get_minor_version() >= 6


class GtkThemeController:
    """Owns the application stylesheet and keeps it in sync with the theme."""

    def __init__(self, display, stylesheet: Path = STYLESHEET):
        self.base_css = stylesheet.read_text(encoding="utf-8")
        self.provider = Gtk.CssProvider()
        self.provider.connect("parsing-error", self._parsing_error)
        Gtk.StyleContext.add_provider_for_display(
            display, self.provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self.style_manager = Adw.StyleManager.get_default()
        self.theme: Theme = get_theme(DEFAULT_THEME)
        self.variant = "theme"
        self.accent = "theme"
        self.translucent = False
        self._rendered: tuple | None = None
        self.style_manager.connect("notify::dark", lambda *_: self._render())
        # Fires when the desktop accent changes (Windows reports it to libadwaita).
        self.style_manager.connect("notify::accent-color", lambda *_: self._render())

    def apply(
        self,
        theme_id: str,
        variant: str = "theme",
        accent: str = "theme",
        *,
        translucent: bool = False,
    ) -> None:
        """``translucent``: a window material (Mica, Acrylic) is behind the windows."""
        self.theme = get_theme(theme_id)
        self.variant = variant
        self.accent = accent
        self.translucent = translucent and self.theme.backdrop
        scheme = self.theme.color_scheme(variant)
        self.style_manager.set_color_scheme(COLOR_SCHEMES[scheme])
        self._render()

    def _render(self) -> None:
        dark = self.style_manager.get_dark()
        system_accent = (
            fluent_accent(host.windows_accent_palette(), dark=dark)
            if self.theme.system_accent
            else None
        )
        key = (self.theme.id, dark, self.accent)
        if system_accent:
            key += (system_accent["accent_bg"],)
        if self.translucent:
            key += ("translucent",)
        if key == self._rendered:
            return
        css = render_gtk_css(
            self.theme,
            dark=dark,
            base_css=self.base_css,
            css_variables=supports_css_variables(),
            accent=self.accent,
            system_accent=system_accent,
            translucent=self.translucent,
        )
        if hasattr(self.provider, "load_from_string"):
            self.provider.load_from_string(css)
        else:  # GTK < 4.12
            self.provider.load_from_data(css, -1)
        self._rendered = key
        LOGGER.debug("Tema %s aplicado (%s)", self.theme.id, "escuro" if dark else "claro")

    @staticmethod
    def _parsing_error(_provider, section, error) -> None:
        location = section.get_start_location() if section else None
        line = location.lines + 1 if location else "?"
        LOGGER.warning("CSS do tema, linha %s: %s", line, error.message)
