"""Find the desktop wallpaper, which the simulated Mica on Linux is made of.

In the Flatpak the desktop's files are seen through the manifest's read-only
permissions: the system's under /run/host, the user's config and data at
their real paths (not the sandbox's XDG folders), and GNOME's settings
through the host dconf.
"""

from __future__ import annotations

import configparser
import logging
import os
import xml.etree.ElementTree as ET
from pathlib import Path

LOGGER = logging.getLogger(__name__)
GNOME_SCHEMA = "org.gnome.desktop.background"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".jxl", ".avif", ".bmp"}
# Plasma's own wallpaper when the look-and-feel package names none.
PLASMA_DEFAULT_WALLPAPER = "Next"
HOST_ROOT = Path("/run/host")


def in_flatpak() -> bool:
    return Path("/.flatpak-info").exists()


def configured_wallpapers(*, dark: bool) -> list[Path]:
    """The images the desktop settings name, reachable or not, dark first in dark mode.

    The light variant follows the dark one: if the image loaders cannot open
    one (GNOME's are JPEG XL), the other may still do.
    """
    found: list[Path] = []
    for finder in (gnome_wallpapers, kde_wallpapers):
        try:
            paths = finder(dark=dark)
        except Exception:
            LOGGER.debug(
                "Não foi possível ler o papel de parede (%s)", finder.__name__, exc_info=True
            )
            continue
        found.extend(path for path in paths if path not in found)
    return found


def host_path(path: Path) -> Path:
    """A system path as the Flatpak sees it, under /run/host."""
    posix = path.as_posix()
    if not in_flatpak() or path.exists() or not posix.startswith(("/usr/", "/etc/", "/opt/")):
        return path
    mapped = HOST_ROOT / posix.lstrip("/")
    return mapped if mapped.exists() else path


def config_home() -> Path:
    if in_flatpak():
        return Path(os.environ.get("HOST_XDG_CONFIG_HOME") or Path.home() / ".config")
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def local_path(uri: str) -> Path | None:
    """A file:// URI or a plain path as a Path; None for anything else."""
    if uri.startswith("file://"):
        from urllib.parse import urlsplit
        from urllib.request import url2pathname

        return host_path(Path(url2pathname(urlsplit(uri).path)))
    path = Path(uri) if uri else None
    return host_path(path) if path is not None and path.is_absolute() else None


def resolve_image(path: Path, *, dark: bool) -> Path | None:
    """The image a wallpaper setting points to.

    GNOME slideshows are XML files listing images; KDE wallpaper packages are
    directories with contents/images (and contents/images_dark).
    """
    if path.is_dir():
        folders = ["images_dark", "images"] if dark else ["images"]
        for folder in folders:
            images = [
                image
                for image in (path / "contents" / folder).glob("*")
                if image.suffix.lower() in IMAGE_SUFFIXES
            ]
            if images:
                return max(images, key=lambda image: image.stat().st_size)
        return None
    if path.suffix.lower() == ".xml":
        for element in ET.parse(path).iter("file"):
            candidate = host_path(Path((element.text or "").strip()))
            if candidate.is_file():
                return candidate
        return None
    return path if path.suffix.lower() in IMAGE_SUFFIXES else None


def gnome_wallpapers(*, dark: bool) -> list[Path]:
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio

    source = Gio.SettingsSchemaSource.get_default()
    schema = source.lookup(GNOME_SCHEMA, True) if source is not None else None
    if schema is None:
        return []
    settings = Gio.Settings.new(GNOME_SCHEMA)
    keys = ["picture-uri-dark", "picture-uri"] if dark else ["picture-uri", "picture-uri-dark"]
    found = []
    for key in keys:
        if not schema.has_key(key):
            continue
        value = settings.get_string(key)
        if in_flatpak() and settings.get_user_value(key) is None:
            # Never changed: the default is the distribution's, which the
            # sandbox's schemas do not have.
            value = host_schema_default(GNOME_SCHEMA, key) or value
        path = local_path(value)
        if path is not None:
            found.append(_image_or_path(path, dark=dark))
    return [path for path in found if path is not None]


def _image_or_path(path: Path, *, dark: bool) -> Path | None:
    """The image behind a setting, or the setting's own path when it is not reachable."""
    return resolve_image(path, dark=dark) if path.exists() else path


def host_schema_default(schema: str, key: str) -> str | None:
    """A key's default as the host's schema overrides set it (Ubuntu's wallpaper, say).

    Override files apply in name order, and sections for the current desktop
    ("schema:ubuntu") win over plain ones.
    """
    folder = HOST_ROOT / "usr" / "share" / "glib-2.0" / "schemas"
    desktops = [
        name.strip().lower()
        for name in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":")
        if name.strip()
    ]
    sections = [schema, *(f"{schema}:{desktop}" for desktop in reversed(desktops))]
    value = None
    for override in sorted(folder.glob("*.gschema.override")):
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            parser.read(override, encoding="utf-8")
        except configparser.Error:
            continue
        for section in sections:
            if parser.has_option(section, key):
                value = parser.get(section, key)
    return value.strip().strip("'\"") if value else None


def kde_wallpapers(*, dark: bool) -> list[Path]:
    """Plasma's first image wallpaper, or the look-and-feel's default one."""
    config = config_home() / "plasma-org.kde.plasma.desktop-appletsrc"
    if config.is_file():
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read(config, encoding="utf-8")
        for section in parser.sections():
            # configparser drops the outer brackets of "[Containments][1][...]".
            if f"[{section}]".endswith("[Wallpaper][org.kde.image][General]"):
                path = local_path(parser.get(section, "Image", fallback=""))
                image = _image_or_path(path, dark=dark) if path is not None else None
                if image is not None:
                    return [image]
    if config.is_file() or "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
        # A wallpaper never changed is not written to the config at all.
        default = plasma_default_wallpaper(config_home())
        image = resolve_image(default, dark=dark) if default is not None else None
        return [image] if image is not None else []
    return []


def _data_dirs() -> list[Path]:
    if in_flatpak():
        home = os.environ.get("HOST_XDG_DATA_HOME") or Path.home() / ".local" / "share"
        return [Path(home), HOST_ROOT / "usr" / "local" / "share", HOST_ROOT / "usr" / "share"]
    home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    system = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [home, *(Path(value) for value in system.split(":") if value)]


def plasma_default_wallpaper(config_home: Path) -> Path | None:
    """The wallpaper package Plasma shows before the user picks one."""
    globals_ = configparser.ConfigParser(interpolation=None, strict=False)
    globals_.read(config_home / "kdeglobals", encoding="utf-8")
    package = globals_.get("KDE", "LookAndFeelPackage", fallback="org.kde.breeze.desktop")
    name = PLASMA_DEFAULT_WALLPAPER
    for data in _data_dirs():
        defaults = data / "plasma" / "look-and-feel" / package / "contents" / "defaults"
        if defaults.is_file():
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            parser.read(defaults, encoding="utf-8")
            name = parser.get("Wallpaper", "Image", fallback=name) or name
            break
    for data in _data_dirs():
        candidate = data / "wallpapers" / name
        if candidate.exists():
            return candidate
    return None
