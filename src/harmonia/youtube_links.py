"""YouTube and YouTube Music links pasted in the search, as what they point to."""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass

from .models import LibraryItem

_HOSTS = {"youtube.com", "music.youtube.com", "m.youtube.com", "www.youtube.com", "youtu.be"}
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_ID = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True, slots=True)
class YouTubeLink:
    """``kind`` is "songs" (``id`` a video), "playlists", "albums" or "artists"."""

    kind: str
    id: str

    def as_item(self, title: str) -> LibraryItem:
        """The page to open for a playlist, album or artist link."""
        return LibraryItem(self.id, title, kind=self.kind)


def parse_link(text: str) -> YouTubeLink | None:
    """What a pasted link points to, or None for anything that is not one."""
    value = (text or "").strip()
    if " " in value or "." not in value:
        return None
    if "://" not in value:
        value = f"https://{value}"
    parts = urllib.parse.urlsplit(value)
    host = (parts.hostname or "").lower()
    if host not in _HOSTS:
        return None
    query = urllib.parse.parse_qs(parts.query)
    segments = [segment for segment in parts.path.split("/") if segment]

    video = (query.get("v") or [""])[0]
    if host == "youtu.be" and segments:
        video = segments[0]
    elif len(segments) == 2 and segments[0] in {"shorts", "embed", "live"}:
        video = segments[1]
    if _VIDEO_ID.match(video):
        return YouTubeLink("songs", video)

    playlist = (query.get("list") or [""])[0]
    if playlist and _ID.match(playlist):
        # OLAK5uy_ playlists are albums; they open as playlists all the same.
        return YouTubeLink("playlists", playlist)
    if len(segments) == 2 and _ID.match(segments[1]):
        if segments[0] == "browse" and segments[1].startswith("MPREb_"):
            return YouTubeLink("albums", segments[1])
        if segments[0] == "channel" and segments[1].startswith("UC"):
            return YouTubeLink("artists", segments[1])
    return None
