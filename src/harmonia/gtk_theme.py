"""Apply Harmonia themes to the GTK frontend at runtime."""

from __future__ import annotations

import logging
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import host, material_scheme  # noqa: E402
from .theming import (  # noqa: E402
    DEFAULT_THEME,
    Theme,
    accent_shades,
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
        # Caelestia Shell's Material scheme (roles, dark), followed live.
        self.desktop_scheme = material_scheme.load_caelestia_scheme()
        self._scheme_monitor = self._watch_desktop_scheme()
        self._scheme_reload = 0
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
        """``translucent``: the Harmonia theme's Mica is behind the windows."""
        self.theme = get_theme(theme_id)
        self.variant = variant
        self.accent = accent
        self.translucent = translucent and self.theme.backdrop
        scheme = self.theme.color_scheme(variant)
        if self.theme.material and self.desktop_scheme and variant == "theme":
            # The desktop's Material scheme is made for one mode: take it.
            scheme = "dark" if self.desktop_scheme[1] else "light"
        self.style_manager.set_color_scheme(COLOR_SCHEMES[scheme])
        self._render()

    def _watch_desktop_scheme(self):
        """Caelestia rewrites its scheme when the wallpaper or scheme changes."""
        monitor = Gio.File.new_for_path(str(material_scheme.caelestia_scheme_path()))
        try:
            watcher = monitor.monitor_file(Gio.FileMonitorFlags.WATCH_MOVES, None)
        except GLib.Error:
            return None
        watcher.connect("changed", lambda *_: self._schedule_scheme_reload())
        return watcher

    def _schedule_scheme_reload(self) -> None:
        # A rewrite arrives as several events; read the file once they settle.
        if self._scheme_reload:
            GLib.source_remove(self._scheme_reload)
        self._scheme_reload = GLib.timeout_add(150, self._reload_desktop_scheme)

    def _reload_desktop_scheme(self) -> bool:
        self._scheme_reload = 0
        scheme = material_scheme.load_caelestia_scheme()
        if scheme != self.desktop_scheme:
            self.desktop_scheme = scheme
            if self.theme.material:
                self.apply(self.theme.id, self.variant, self.accent, translucent=self.translucent)
            elif self.theme.system_accent:
                self._render()
        return GLib.SOURCE_REMOVE

    def _desktop_roles(self, dark: bool) -> dict[str, str] | None:
        """The desktop's Material roles, when made for the mode on screen."""
        if self.desktop_scheme and self.desktop_scheme[1] == dark:
            return self.desktop_scheme[0]
        return None

    def _render(self) -> None:
        dark = self.style_manager.get_dark()
        system_accent = (
            fluent_accent(self._system_accent_palette(), dark=dark)
            if self.theme.system_accent
            else None
        )
        desktop_roles = self._desktop_roles(dark) if self.theme.material else None
        key = (self.theme.id, dark, self.accent)
        if system_accent:
            key += (system_accent["accent_bg"],)
        if desktop_roles:
            key += (tuple(desktop_roles.values()),)
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
            desktop_roles=desktop_roles,
        )
        if hasattr(self.provider, "load_from_string"):
            self.provider.load_from_string(css)
        else:  # GTK < 4.12
            self.provider.load_from_data(css, -1)
        self._rendered = key
        LOGGER.debug("Tema %s aplicado (%s)", self.theme.id, "escuro" if dark else "claro")

    def _system_accent_palette(self) -> list[str] | None:
        """The desktop's accent shades, or None to keep the theme's own accent.

        Windows reports the exact shades. Other desktops report one accent
        colour through libadwaita (GNOME's Appearance settings), or Caelestia
        Shell through its Material scheme; without one (older libadwaita,
        desktops with no accent setting) the theme keeps its own.
        """
        if host.IS_WINDOWS:
            return host.windows_accent_palette()
        manager = self.style_manager
        supported = getattr(manager, "get_system_supports_accent_colors", None)
        if supported is None or not supported():
            desktop_scheme = getattr(self, "desktop_scheme", None)
            if desktop_scheme:
                return accent_shades(desktop_scheme[0]["primaryContainer"])
            return None
        rgba = manager.get_accent_color_rgba()
        channels = (round(value * 255) for value in (rgba.red, rgba.green, rgba.blue))
        return accent_shades("#" + "".join(f"{channel:02x}" for channel in channels))

    @staticmethod
    def _parsing_error(_provider, section, error) -> None:
        location = section.get_start_location() if section else None
        line = location.lines + 1 if location else "?"
        LOGGER.warning("CSS do tema, linha %s: %s", line, error.message)
