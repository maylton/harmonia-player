"""Mica and Acrylic for the GTK frontend on Linux.

Both blur what is behind the window, as on Windows, when the compositor can:
the window turns translucent under a tint of the theme's window colour
(stronger for Mica) and the compositor blurs behind it. KWin does it on
request (kwin_blur.py); on GNOME only the Blur my Shell extension can, for
the applications in its list (gnome_blur.py).

Without a compositor blur, Mica is drawn by Harmonia from the desktop
wallpaper, blurred once into a small image that becomes the window's
background (it cannot follow the window, which Wayland does not place), and
Acrylic is the translucent window alone.

Out of focus, windows11.css turns the window opaque as on Windows.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

from . import desktop_wallpaper, gnome_blur, host, kwin_blur  # noqa: E402
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
CORNER_RADIUS = 8  # windows11.css's window.csd corners, outside the blur
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
FLATPAK_ID = "io.github.harmonia.Harmonia"


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


def material_css(kind: str, tint: str, image: Path | None, *, blurred: bool = False) -> str:
    """The window background of ``kind``; ``image`` is Mica's blurred wallpaper.

    With the compositor blurring behind the window, both are the tint alone.
    """
    selector = f"window.{CSS_CLASS}.{LINUX_CSS_CLASS}"
    if blurred and kind in ("mica", "acrylic"):
        return f"{selector} {{ background-color: {tint}; background-image: none; }}\n"
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
        # The wallpaper Mica is made of, for Preferences.
        self.wallpaper: Path | None = None
        # Who blurs behind the window: "kwin", "blur-my-shell" or "" (nobody).
        self.blur = ""
        # Blur my Shell is on but does not blur Harmonia: Preferences offer it.
        self.blur_my_shell_offer = False
        self._kwin = None
        self._kwin_display = None
        self._kwin_surfaces: dict[int, int] = {}
        self._waiting_realize = False
        self._window: Gtk.Window | None = None
        self._provider = Gtk.CssProvider()
        self._provider_display = None
        self._timer = 0
        self._style = Adw.StyleManager.get_default()
        self._style.connect("notify::dark", lambda *_: self._refresh())
        self._wallpaper_settings = self._watch_gnome_wallpaper()
        self._color_scheme_signal = self._watch_desktop_color_scheme()

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

    def _watch_desktop_color_scheme(self) -> int:
        """The desktop switching light and dark switches its wallpaper too."""
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error:
            return 0

        def changed(_bus, _sender, _path, _interface, _signal, parameters):
            namespace, key, _value = parameters.unpack()
            scheme = (namespace, key) == ("org.freedesktop.appearance", "color-scheme")
            if scheme and self.kind == "mica":
                self._refresh()

        return bus.signal_subscribe(
            desktop_wallpaper.PORTAL_NAME,
            desktop_wallpaper.PORTAL_SETTINGS,
            "SettingChanged",
            desktop_wallpaper.PORTAL_PATH,
            None,
            Gio.DBusSignalFlags.NONE,
            changed,
        )

    def _schedule_slideshow_refresh(self) -> None:
        """A timed wallpaper changes by itself: refresh when its image does."""
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        seconds = desktop_wallpaper.seconds_until_change()
        if self.kind != "mica" or seconds is None:
            return

        def tick() -> bool:
            self._timer = 0
            self._refresh()
            return GLib.SOURCE_REMOVE

        # A second after the change, and at least every hour in case the clock jumps.
        self._timer = GLib.timeout_add_seconds(int(min(seconds, 3600)) + 1, tick)

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
        self.blur = self._compositor_blur(window) if self.kind != "none" else ""
        if self.blur != "kwin":
            self._release_kwin_blur()
        if self.kind == "mica" and not self.blur:
            # The variant the desktop shows, whatever Harmonia's own style is.
            desktop_dark = desktop_wallpaper.desktop_prefers_dark()
            image, self.reason = self._mica(dark if desktop_dark is None else desktop_dark)
        else:
            self.wallpaper = None
            image, self.reason = None, self._no_blur_reason() if self.kind == "acrylic" else ""
        self._schedule_slideshow_refresh()
        css = (
            material_css(self.kind, self._tint(dark), image, blurred=bool(self.blur))
            if self.kind != "none"
            else ""
        )
        self._provider.load_from_string(css)
        applied = bool(css)
        set_css_class(window, CSS_CLASS, applied)
        set_css_class(window, LINUX_CSS_CLASS, applied)
        self.active = applied
        return applied

    def _mica(self, dark: bool) -> tuple[Path | None, str]:
        """The blurred wallpaper, or None and why there is none."""
        self.wallpaper = None
        configured = desktop_wallpaper.configured_wallpapers(dark=dark)
        candidates = [path for path in configured if path.is_file()]
        for wallpaper in candidates:
            try:
                image = mica_image(wallpaper, host.cache_dir() / "mica")
            except (GLib.Error, OSError):
                LOGGER.warning(
                    "Não foi possível abrir o papel de parede %s", wallpaper, exc_info=True
                )
                continue
            self.wallpaper = wallpaper
            return image, ""
        if candidates:
            return None, unreadable_reason(candidates[0])
        if configured and desktop_wallpaper.in_flatpak():
            # The setting names a file outside what the manifest lets it read.
            return None, _(
                "O Flatpak não pode ler o papel de parede. Libere a pasta dele com: "
                "flatpak override --user --filesystem={folder}:ro {app}"
            ).format(folder=configured[0].parent, app=FLATPAK_ID)
        if configured:
            return None, _("O papel de parede {name} não foi encontrado").format(
                name=configured[0].name
            )
        return None, _("Papel de parede do GNOME ou do Plasma não encontrado")

    # --- Compositor blur ----------------------------------------------------

    def _compositor_blur(self, window: Gtk.Window) -> str:
        """Who blurs behind the window now; asks KWin for it on the way."""
        self.blur_my_shell_offer = False
        if "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
            app = window.get_application()
            state = gnome_blur.state(app.get_application_id() if app else FLATPAK_ID)
            self.blur_my_shell_offer = state.enabled and not state.blurs_app
            return "blur-my-shell" if state.blurs_app else ""
        kwin = self._kwin_for(window)
        if kwin is None:
            return ""
        self._request_kwin_blur(window)
        return "kwin"

    def _no_blur_reason(self) -> str:
        if "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
            if self.blur_my_shell_offer:
                return _("O Blur my Shell está ativo, mas não borra o Harmonia")
            return _("No GNOME, o borrado por trás da janela precisa da extensão Blur my Shell")
        return _("Ative o efeito Desfoque do KWin para borrar o que está atrás da janela")

    def include_in_blur_my_shell(self) -> bool:
        """Add Harmonia to Blur my Shell's application blur, then use it."""
        window = self._window
        app = window.get_application() if window is not None else None
        done = gnome_blur.include(app.get_application_id() if app else FLATPAK_ID)
        if done:
            self._refresh()
        return done

    def _kwin_for(self, window: Gtk.Window):
        display = window.get_display()
        if display is not self._kwin_display:
            self._kwin_display = display
            self._kwin = kwin_blur.connect(display) if display is not None else None
        return self._kwin

    def _request_kwin_blur(self, window: Gtk.Window) -> None:
        """Blur behind the window's visible area, kept in step with its size."""
        surface = window.get_surface()
        if surface is None:
            if not self._waiting_realize:
                self._waiting_realize = True
                window.connect("realize", lambda *_: self.kind != "none" and self._refresh())
            return
        handle = kwin_blur.surface_handle(surface)
        if handle is None:
            return
        if handle not in self._kwin_surfaces:
            self._kwin_surfaces[handle] = surface.connect(
                "layout", lambda *_: self.blur == "kwin" and self._update_kwin_region()
            )
            window.connect(
                "notify::maximized", lambda *_: self.blur == "kwin" and self._update_kwin_region()
            )
            window.connect("unrealize", lambda *_: self._forget_kwin_surface(handle))
        self._update_kwin_region()

    def _update_kwin_region(self) -> bool:
        window = self._window
        surface = window.get_surface() if window is not None else None
        handle = kwin_blur.surface_handle(surface) if surface is not None else None
        if handle is None or self._kwin is None:
            return False
        x, y = window.get_surface_transform()
        flat = window.is_maximized() or window.is_fullscreen()
        rects = kwin_blur.rounded_rect_region(
            round(x),
            round(y),
            window.get_width(),
            window.get_height(),
            0 if flat else CORNER_RADIUS,
        )
        if isinstance(self._kwin, kwin_blur.X11Blur):
            # X11 counts device pixels.
            scale = surface.get_scale_factor()
            rects = [tuple(value * scale for value in rect) for rect in rects]
        self._kwin.set_region(handle, rects)
        window.queue_draw()  # the request takes effect on the surface's next commit
        return False

    def _forget_kwin_surface(self, handle: int) -> None:
        self._kwin_surfaces.pop(handle, None)
        if self._kwin is not None:
            self._kwin.unset(handle)

    def _release_kwin_blur(self) -> None:
        if self._kwin is not None:
            for handle in list(self._kwin_surfaces):
                self._kwin.unset(handle)

    def _install_provider(self, window: Gtk.Window) -> None:
        display = window.get_display() or Gdk.Display.get_default()
        if display is None or display is self._provider_display:
            return
        # Above the theme, whose "window" rule paints the window colour.
        Gtk.StyleContext.add_provider_for_display(
            display, self._provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
        )
        self._provider_display = display
