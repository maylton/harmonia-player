"""Artwork: covers loaded off the main thread, cached on disk and sized per use."""

from __future__ import annotations

import logging
import re
import threading
import urllib.request
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk

from . import blur_textures
from .models import (
    LibraryItem,
)
from .window_constants import ICONS

LOGGER = logging.getLogger(__name__)
ARTWORK_DOWNLOADS = threading.BoundedSemaphore(6)


class WindowArtworkMixin:
    """Covers for every page; at most six download at once."""

    def _square_cover(self, item: LibraryItem, size: int = 140, fixed: bool = False) -> Gtk.Widget:
        """Create conventional 1:1 music artwork, circular only for artists."""
        # Detail artwork has an exact desktop size.  A plain overlay keeps it
        # from reserving the hero's full cross-axis size, while cards continue
        # to use AspectFrame so their 1:1 ratio survives responsive layouts.
        frame = Gtk.Overlay() if fixed else Gtk.AspectFrame(ratio=1.0, obey_child=False)
        frame.set_size_request(size, size)
        frame.set_halign(Gtk.Align.START)
        frame.set_valign(Gtk.Align.START)
        if fixed:
            frame.set_hexpand(False)
            frame.set_hexpand_set(True)
            frame.set_vexpand(False)
            frame.set_vexpand_set(True)
        frame.set_overflow(Gtk.Overflow.HIDDEN)
        frame.add_css_class("artist-cover" if item.kind == "artists" else "square-cover")
        overlay = Gtk.Overlay(hexpand=True, vexpand=True)
        placeholder = Gtk.Image.new_from_icon_name(ICONS.get(item.kind, "audio-x-generic-symbolic"))
        placeholder.set_pixel_size(min(42, max(16, size // 2)))
        placeholder.add_css_class("cover-placeholder")
        overlay.set_child(placeholder)
        if item.thumbnail:
            picture = Gtk.Picture(
                content_fit=Gtk.ContentFit.COVER, can_shrink=True, hexpand=True, vexpand=True
            )
            picture.add_css_class("cover-art")
            overlay.add_overlay(picture)
            # Thumbnails in track lists only need a small image.
            self._load_artwork(
                item.thumbnail, picture, size=size * 3 if size < 64 else max(256, size * 2)
            )
        frame.set_child(overlay)
        return frame

    @staticmethod
    def _sized_artwork_url(url: str, size: int | None = None) -> str:
        """Request a sharper Google/YouTube thumbnail without changing its asset."""
        if not size or not any(
            domain in url
            for domain in (
                "googleusercontent.com",
                "ggpht.com",
            )
        ):
            return url
        size = max(64, min(1280, int(size)))
        result = re.sub(r"([=-])w\d+(?=-|$)", rf"\1w{size}", url)
        result = re.sub(r"([=-])h\d+(?=-|$)", rf"\1h{size}", result)
        result = re.sub(r"=s\d+(?=-|$)", f"=s{size}", result)
        return result

    def _set_artwork_if_current(
        self,
        picture: Gtk.Picture,
        target: Path,
        request_key: str,
    ) -> bool:
        if self._artwork_requests.get(id(picture)) == request_key and target.exists():
            self._show_artwork_file(picture, target)
        return GLib.SOURCE_REMOVE

    @staticmethod
    def _show_artwork_file(picture: Gtk.Picture, target: Path) -> None:
        if not blur_textures.show(picture, str(target)):
            picture.set_filename(str(target))

    def _load_artwork(
        self,
        url: str,
        picture: Gtk.Picture,
        *,
        size: int | None = None,
    ) -> None:
        request_url = self._sized_artwork_url(url, size)
        target = self.storage.artwork_path(request_url)
        request_key = str(target)
        self._artwork_requests[id(picture)] = request_key
        if target.exists():
            self._show_artwork_file(picture, target)
            return

        def worker():
            try:
                request = urllib.request.Request(request_url, headers={"User-Agent": "Mozilla/5.0"})
                # Long track lists request many covers at once; cap the
                # parallel downloads instead of opening one connection each.
                with ARTWORK_DOWNLOADS, urllib.request.urlopen(request, timeout=15) as response:
                    data = response.read(12 * 1024 * 1024)
                target.write_bytes(data)
                GLib.idle_add(self._set_artwork_if_current, picture, target, request_key)
            except Exception:
                LOGGER.debug("Não foi possível carregar a arte de %s", request_url, exc_info=True)

        threading.Thread(target=worker, daemon=True).start()
