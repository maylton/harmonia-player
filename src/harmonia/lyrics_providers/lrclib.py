"""LRCLIB: community lyrics, timed by line (sometimes by word, as enhanced LRC)."""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable

from ..lrc import parse_lrc
from ..models import LibraryItem, LyricsDocument
from .common import clean_title, get_json, lyrics_metadata


class LrcLibClient:
    API = "https://lrclib.net/api"
    NAME = "LRCLIB"

    def __init__(self, opener: Callable[..., object] = urllib.request.urlopen) -> None:
        self.opener = opener

    def lyrics(self, item: LibraryItem, duration_ms: int = 0) -> LyricsDocument | None:
        artist, album = lyrics_metadata(item)
        params = {
            "track_name": clean_title(item.title),
            "artist_name": artist,
        }
        if album:
            params["album_name"] = album
        if duration_ms > 0:
            params["duration"] = str(round(duration_ms / 1000))
        payload = self._request("get", params, allow_not_found=True)
        if payload is None:
            results = self._request("search", {"q": f"{params['track_name']} {artist}"}) or []
            payload = self._closest(results, duration_ms)
        return self._document(payload)

    def _request(self, path: str, params: dict[str, str], allow_not_found: bool = False):
        try:
            return get_json(self.opener, f"{self.API}/{path}", params)
        except urllib.error.HTTPError as exc:
            if allow_not_found and exc.code == 404:
                return None
            raise

    @staticmethod
    def _closest(results, duration_ms: int):
        if not isinstance(results, list) or not results:
            return None
        if duration_ms <= 0:
            return results[0]
        duration = duration_ms / 1000
        return min(
            results, key=lambda result: abs(float(result.get("duration") or duration) - duration)
        )

    @classmethod
    def _document(cls, payload) -> LyricsDocument | None:
        if not isinstance(payload, dict):
            return None
        synced = parse_lrc(payload.get("syncedLyrics") or "")
        plain = (payload.get("plainLyrics") or "").strip()
        if not plain and synced:
            plain = "\n".join(line.text for line in synced)
        if not plain and payload.get("instrumental"):
            plain = "♪ Instrumental"
        return LyricsDocument(plain, cls.NAME, synced) if plain else None
