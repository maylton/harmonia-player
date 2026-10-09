"""Find the desktop wallpaper, which the simulated Mica on Linux is made of."""

from __future__ import annotations

import configparser
import logging
import os
import xml.etree.ElementTree as ET
from pathlib import Path

LOGGER = logging.getLogger(__name__)
GNOME_SCHEMA = "org.gnome.desktop.background"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".jxl", ".avif", ".bmp"}


def wallpaper_path(*, dark: bool) -> Path | None:
    """The current wallpaper image (the dark variant in dark mode), or None."""
    for finder in (gnome_wallpaper, kde_wallpaper):
        try:
            path = finder(dark=dark)
        except Exception:
            LOGGER.debug(
                "Não foi possível ler o papel de parede (%s)", finder.__name__, exc_info=True
            )
            continue
        if path is not None and path.is_file():
            return path
    return None


def local_path(uri: str) -> Path | None:
    """A file:// URI or a plain path as a Path; None for anything else."""
    if uri.startswith("file://"):
        from urllib.parse import urlsplit
        from urllib.request import url2pathname

        return Path(url2pathname(urlsplit(uri).path))
    path = Path(uri) if uri else None
    return path if path is not None and path.is_absolute() else None


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
            candidate = Path((element.text or "").strip())
            if candidate.is_file():
                return candidate
        return None
    return path if path.suffix.lower() in IMAGE_SUFFIXES else None


def gnome_wallpaper(*, dark: bool) -> Path | None:
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio

    source = Gio.SettingsSchemaSource.get_default()
    schema = source.lookup(GNOME_SCHEMA, True) if source is not None else None
    if schema is None:
        return None
    settings = Gio.Settings.new(GNOME_SCHEMA)
    keys = ["picture-uri-dark", "picture-uri"] if dark else ["picture-uri"]
    for key in keys:
        if not schema.has_key(key):
            continue
        path = local_path(settings.get_string(key))
        if path is not None and path.exists():
            return resolve_image(path, dark=dark)
    return None


def kde_wallpaper(*, dark: bool) -> Path | None:
    """The image of Plasma's first desktop with the image wallpaper plugin."""
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    config = config_home / "plasma-org.kde.plasma.desktop-appletsrc"
    if not config.is_file():
        return None
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read(config, encoding="utf-8")
    for section in parser.sections():
        # configparser drops the outer brackets of "[Containments][1][...]".
        if f"[{section}]".endswith("[Wallpaper][org.kde.image][General]"):
            path = local_path(parser.get(section, "Image", fallback=""))
            if path is not None and path.exists():
                return resolve_image(path, dark=dark)
    return None
