"""Artwork: covers loaded off the main thread, cached on disk and sized per use."""

from __future__ import annotations

import logging
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk

from .models import (
    LibraryItem,
)
from .window_constants import ICONS

LOGGER = logging.getLogger(__name__)
ARTWORK_DOWNLOADS = threading.BoundedSemaphore(6)
# Video thumbnails (i.ytimg.com), largest first: YouTube Music sends 400x225
# ones, blurry in the expanded player. Not every video has the 1280x720 ones,
# so each is tried in turn before the one sent; the 4:3 sizes in between are
# letterboxed, and their bars would show in the square crop.
YOUTUBE_THUMBNAILS = ("maxresdefault.jpg", "hq720.jpg")
YOUTUBE_THUMBNAIL = re.compile(r"^https://i\d?\.ytimg\.com/vi(?:_webp)?/([\w-]{11})/")
LARGE_ARTWORK = 512  # sizes from here on (the expanded player) look for them


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
        size = max(64, min(2048, int(size)))
        result = re.sub(r"([=-])w\d+(?=-|$)", rf"\1w{size}", url)
        result = re.sub(r"([=-])h\d+(?=-|$)", rf"\1h{size}", result)
        result = re.sub(r"=s\d+(?=-|$)", f"=s{size}", result)
        return result

    @staticmethod
    def _artwork_candidates(url: str, size: int | None = None) -> list[str]:
        """The addresses to try for ``url`` at ``size``, sharpest first."""
        video = YOUTUBE_THUMBNAIL.match(url)
        if video and size and size >= LARGE_ARTWORK:
            folder = f"https://i.ytimg.com/vi/{video[1]}/"
            return [folder + name for name in YOUTUBE_THUMBNAILS] + [url]
        return [WindowArtworkMixin._sized_artwork_url(url, size)]

    def _set_artwork_if_current(
        self,
        picture: Gtk.Picture,
        target: Path,
        request_key: str,
    ) -> bool:
        if self._artwork_requests.get(id(picture)) == request_key and target.exists():
            picture.set_filename(str(target))
        return GLib.SOURCE_REMOVE

    def _load_artwork(
        self,
        url: str,
        picture: Gtk.Picture,
        *,
        size: int | None = None,
    ) -> None:
        candidates = self._artwork_candidates(url, size)
        target = self.storage.artwork_path(candidates[0])
        request_key = str(target)
        self._artwork_requests[id(picture)] = request_key
        if target.exists():
            picture.set_filename(str(target))
            return

        def worker():
            for request_url in candidates:
                try:
                    request = urllib.request.Request(
                        request_url, headers={"User-Agent": "Mozilla/5.0"}
                    )
                    # Long track lists request many covers at once; cap the
                    # parallel downloads instead of opening one connection each.
                    with ARTWORK_DOWNLOADS, urllib.request.urlopen(request, timeout=15) as response:
                        data = response.read(12 * 1024 * 1024)
                except urllib.error.HTTPError as error:
                    if error.code == 404:  # this video has no thumbnail that large
                        continue
                    LOGGER.debug(
                        "Não foi possível carregar a arte de %s", request_url, exc_info=True
                    )
                    return
                except Exception:
                    LOGGER.debug(
                        "Não foi possível carregar a arte de %s", request_url, exc_info=True
                    )
                    return
                target.write_bytes(data)
                GLib.idle_add(self._set_artwork_if_current, picture, target, request_key)
                return

        threading.Thread(target=worker, daemon=True).start()
