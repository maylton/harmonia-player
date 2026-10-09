"""Mica and Acrylic for the GTK frontend on Linux.

No Linux compositor offers Windows' materials to applications, so:

- Mica, the desktop wallpaper blurred and tinted behind the window, is drawn
  by Harmonia: the wallpaper is blurred once into a small image, which becomes
  the window's CSS background under a tint of the theme's window colour. Unlike
  Windows it does not shift as the window moves, since Wayland does not tell
  applications where their windows are.
- Acrylic shows what is behind the window, blurred, which only the compositor
  can do: the window turns translucent under a tint that keeps it readable,
  and the compositor's blur does the rest where there is one (KWin's blur with
  the Force Blur script, GNOME Shell with the Blur my Shell extension).

Out of focus, windows11.css turns the window opaque as on Windows.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

from . import desktop_wallpaper, host  # noqa: E402
from .i18n import _  # noqa: E402
from .theming import get_theme  # noqa: E402
from .ui import set_css_class  # noqa: E402

LOGGER = logging.getLogger(__name__)
CSS_CLASS = "harmonia-backdrop"  # the translucent rules of windows11.css
LINUX_CSS_CLASS = "harmonia-backdrop-linux"
# Opacity of the window colour over the material, per colour scheme: Mica
# keeps the wallpaper a soft hint, Acrylic stays readable without a blur.
TINT = {
    "mica": {"dark": 0.78, "light": 0.68},
    "acrylic": {"dark": 0.72, "light": 0.65},
}
MICA_SHRINK = 14  # pixels of the longest side the wallpaper is reduced to
MICA_SIZE = 640  # size of the smoothed image the window scales to cover


def load_scaled(wallpaper: Path, size: int = 320) -> GdkPixbuf.Pixbuf:
    """The image at most ``size`` pixels wide or tall.

    GdkPixbuf opens what its installed loaders know (JPEG XL, WebP and AVIF
    need extra packages); GTK's own decoder is tried after it.
    """
    try:
        return GdkPixbuf.Pixbuf.new_from_file_at_scale(str(wallpaper), size, size, True)
    except GLib.Error:
        texture = Gdk.Texture.new_from_filename(str(wallpaper))
        loader = GdkPixbuf.PixbufLoader.new_with_type("png")
        loader.set_size(*_fit(texture.get_width(), texture.get_height(), size))
        loader.write_bytes(texture.save_to_png_bytes())
        loader.close()
        return loader.get_pixbuf()


def _fit(width: int, height: int, size: int) -> tuple[int, int]:
    scale = min(1.0, size / max(width, height, 1))
    return max(1, round(width * scale)), max(1, round(height * scale))


def mica_image(wallpaper: Path, cache: Path) -> Path:
    """The wallpaper heavily blurred, cached by path and modification time."""
    stamp = f"{wallpaper}:{wallpaper.stat().st_mtime_ns}"
    target = cache / f"mica-{hashlib.sha1(stamp.encode()).hexdigest()[:16]}.png"
    if target.is_file():
        return target
    source = load_scaled(wallpaper)
    width, height = source.get_width(), source.get_height()
    scale = MICA_SHRINK / max(width, height)
    tiny = source.scale_simple(
        max(2, round(width * scale)), max(2, round(height * scale)), GdkPixbuf.InterpType.HYPER
    )
    scale = MICA_SIZE / max(tiny.get_width(), tiny.get_height())
    smooth = tiny.scale_simple(
        round(tiny.get_width() * scale),
        round(tiny.get_height() * scale),
        GdkPixbuf.InterpType.BILINEAR,
    )
    cache.mkdir(parents=True, exist_ok=True)
    for old in cache.glob("mica-*.png"):
        old.unlink(missing_ok=True)
    smooth.savev(str(target), "png", [], [])
    return target


FORMAT_PACKAGES = {".jxl": "JPEG XL", ".webp": "WebP", ".avif": "AVIF"}


def unreadable_reason(wallpaper: Path) -> str:
    image_format = FORMAT_PACKAGES.get(wallpaper.suffix.lower())
    if image_format:
        return _(
            "O papel de parede é {format} e falta o suporte a esse formato "
            "(pacote do gdk-pixbuf para {format})"
        ).format(format=image_format)
    return _("Não foi possível abrir o papel de parede {name}").format(name=wallpaper.name)


def rgba(color: str, alpha: float) -> str:
    red, green, blue = (int(color.lstrip("#")[index : index + 2], 16) for index in (0, 2, 4))
    return f"rgba({red}, {green}, {blue}, {alpha})"


def material_css(kind: str, tint: str, image: Path | None) -> str:
    """The window background of ``kind``; ``image`` is Mica's blurred wallpaper."""
    selector = f"window.{CSS_CLASS}.{LINUX_CSS_CLASS}"
    if kind == "mica" and image is not None:
        uri = Gio.File.new_for_path(str(image)).get_uri()
        return (
            f"{selector} {{\n"
            f'  background-image: linear-gradient({tint}, {tint}), url("{uri}");\n'
            "  background-size: cover;\n"
            "  background-position: center;\n"
            "  background-repeat: no-repeat;\n"
            "}\n"
        )
    if kind == "acrylic":
        return f"{selector} {{ background-color: {tint}; background-image: none; }}\n"
    return ""


class LinuxWindowBackdrops:
    """Puts the simulated material behind the main window; see the module docstring.

    ``active`` tells whether the window shows it: Mica needs a wallpaper the
    desktop reports (GNOME or Plasma, outside the Flatpak sandbox).
    """

    def __init__(self) -> None:
        self.kind = "none"
        self.active = False
        # Why the chosen material is not shown, for Preferences; "" when it is.
        self.reason = ""
        self._window: Gtk.Window | None = None
        self._provider = Gtk.CssProvider()
        self._provider_display = None
        self._style = Adw.StyleManager.get_default()
        self._style.connect("notify::dark", lambda *_: self._refresh())
        self._wallpaper_settings = self._watch_gnome_wallpaper()

    def set_kind(self, kind: str, main_window: Gtk.Window) -> bool:
        """Use ``kind`` ("mica", "acrylic" or "none"); True if the window shows it."""
        self.kind = kind
        self._window = main_window
        self.active = self._refresh()
        return self.active

    def attach_popover(self, popover: Gtk.Popover) -> None:
        """Popovers keep their opaque background on Linux."""

    def _watch_gnome_wallpaper(self):
        source = Gio.SettingsSchemaSource.get_default()
        if source is None or source.lookup(desktop_wallpaper.GNOME_SCHEMA, True) is None:
            return None
        settings = Gio.Settings.new(desktop_wallpaper.GNOME_SCHEMA)
        settings.connect("changed", lambda *_: self.kind == "mica" and self._refresh())
        return settings

    def _tint(self, dark: bool) -> str:
        theme = get_theme(getattr(self._window.preferences, "theme", ""))
        variant = "dark" if dark else "light"
        color = theme.palettes.get(variant, {}).get("sidebar_bg", "#202020" if dark else "#f3f3f3")
        return rgba(color, TINT.get(self.kind, TINT["mica"])[variant])

    def _refresh(self) -> bool:
        window = self._window
        if window is None:
            return False
        self._install_provider(window)
        dark = self._style.get_dark()
        image, self.reason = self._mica(dark) if self.kind == "mica" else (None, "")
        css = material_css(self.kind, self._tint(dark), image) if self.kind != "none" else ""
        self._provider.load_from_string(css)
        applied = bool(css)
        set_css_class(window, CSS_CLASS, applied)
        set_css_class(window, LINUX_CSS_CLASS, applied)
        self.active = applied
        return applied

    @staticmethod
    def _mica(dark: bool) -> tuple[Path | None, str]:
        """The blurred wallpaper, or None and why there is none."""
        candidates = desktop_wallpaper.wallpaper_candidates(dark=dark)
        for wallpaper in candidates:
            try:
                return mica_image(wallpaper, host.cache_dir() / "mica"), ""
            except (GLib.Error, OSError):
                LOGGER.warning(
                    "Não foi possível abrir o papel de parede %s", wallpaper, exc_info=True
                )
        if candidates:
            return None, unreadable_reason(candidates[0])
        if desktop_wallpaper.in_flatpak():
            return None, _(
                "O Flatpak não tem acesso ao papel de parede; instale o pacote .deb ou .rpm"
            )
        return None, _("Papel de parede do GNOME ou do Plasma não encontrado")

    def _install_provider(self, window: Gtk.Window) -> None:
        display = window.get_display() or Gdk.Display.get_default()
        if display is None or display is self._provider_display:
            return
        # Above the theme, whose "window" rule paints the window colour.
        Gtk.StyleContext.add_provider_for_display(
            display, self._provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
        )
        self._provider_display = display
