"""Lyrics parsing and network providers, intentionally independent from GTK."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

from .models import LibraryItem, LyricLine, LyricsDocument

_TIMESTAMP = re.compile(
    r"\[(?:(?P<hours>\d+):)?(?P<minutes>\d{1,3}):(?P<seconds>\d{2})(?:[.:](?P<fraction>\d{1,3}))?\]"
)
_METADATA = re.compile(r"^\[(?:ar|al|ti|by|re|ve|length|la):.*\]$", re.IGNORECASE)
_OFFSET = re.compile(r"^\[offset:([+-]?\d+)\]$", re.IGNORECASE)


def parse_lrc(value: str) -> list[LyricLine]:
    """Parse common LRC/enhanced-LRC timestamps and apply the embedded offset."""
    offset_ms = 0
    parsed: list[LyricLine] = []
    for raw_line in (value or "").replace("\r\n", "\n").splitlines():
        line = raw_line.strip()
        offset = _OFFSET.match(line)
        if offset:
            offset_ms = int(offset.group(1))
            continue
        if _METADATA.match(line):
            continue
        matches = list(_TIMESTAMP.finditer(line))
        if not matches:
            continue
        text = _TIMESTAMP.sub("", line).strip()
        if not text:
            text = "♪"
        for match in matches:
            hours = int(match.group("hours") or 0)
            minutes = int(match.group("minutes"))
            seconds = int(match.group("seconds"))
            fraction = match.group("fraction") or "0"
            millis = int(fraction.ljust(3, "0")[:3])
            start_ms = ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis
            parsed.append(LyricLine(max(0, start_ms + offset_ms), text))
    # Several providers emit duplicate timestamp/text pairs.
    unique = {(line.start_ms, line.text): line for line in parsed}
    return sorted(unique.values(), key=lambda entry: entry.start_ms)


def _clean_title(title: str) -> str:
    return re.sub(
        r"\s*[\[(](?:official|lyrics?|audio|video|visuali[sz]er|remaster(?:ed)?).*?[\])]\s*",
        " ",
        title,
        flags=re.IGNORECASE,
    ).strip()


def lyrics_metadata(item: LibraryItem) -> tuple[str, str | None]:
    parts = [part.strip() for part in re.split(r"\s*[·•]\s*", item.subtitle or "") if part.strip()]
    noise = re.compile(r"^(?:música|music|vídeo|video|podcast|\d+(?::\d+){1,2})$", re.IGNORECASE)
    useful = [part for part in parts if not noise.match(part) and "visualiza" not in part.lower()]
    artist = useful[0] if useful else ""
    album = useful[-1] if len(useful) > 1 else None
    return artist, album


class LrcLibClient:
    API = "https://lrclib.net/api"

    def __init__(self, opener: Callable[..., object] = urllib.request.urlopen) -> None:
        self.opener = opener

    def lyrics(self, item: LibraryItem, duration_ms: int = 0) -> LyricsDocument | None:
        artist, album = lyrics_metadata(item)
        params = {
            "track_name": _clean_title(item.title),
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
        url = f"{self.API}/{path}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": "Harmonia/0.1 (Linux GTK4)"})
        try:
            with self.opener(request, timeout=8) as response:
                return json.loads(response.read().decode("utf-8"))
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

    @staticmethod
    def _document(payload) -> LyricsDocument | None:
        if not isinstance(payload, dict):
            return None
        synced_value = payload.get("syncedLyrics") or ""
        synced = parse_lrc(synced_value)
        plain = (payload.get("plainLyrics") or "").strip()
        if not plain and synced:
            plain = "\n".join(line.text for line in synced)
        if not plain and payload.get("instrumental"):
            plain = "♪ Instrumental"
        return LyricsDocument(plain, "LRCLIB", synced) if plain else None


class GoogleTranslationClient:
    """Small no-key translation fallback; the client is injectable for deterministic tests."""

    ENDPOINT = "https://translate.googleapis.com/translate_a/single"

    def __init__(self, opener: Callable[..., object] = urllib.request.urlopen) -> None:
        self.opener = opener

    def translate(self, lines: list[str], target: str = "pt") -> list[str]:
        if not lines:
            return []
        chunks: list[list[str]] = []
        current: list[str] = []
        size = 0
        for line in lines:
            if current and size + len(line) + 1 > 3500:
                chunks.append(current)
                current, size = [], 0
            current.append(line)
            size += len(line) + 1
        if current:
            chunks.append(current)
        translated: list[str] = []
        for chunk in chunks:
            params = urllib.parse.urlencode(
                {
                    "client": "gtx",
                    "sl": "auto",
                    "tl": target,
                    "dt": "t",
                    "q": "\n".join(chunk),
                }
            )
            request = urllib.request.Request(
                f"{self.ENDPOINT}?{params}", headers={"User-Agent": "Harmonia/0.1"}
            )
            with self.opener(request, timeout=12) as response:
                payload = json.loads(response.read().decode("utf-8"))
            text = "".join(segment[0] for segment in payload[0] if segment and segment[0])
            result = text.splitlines()
            if len(result) != len(chunk):
                # Never attach a translation to the wrong timestamp.
                result = [text] if len(chunk) == 1 else [""] * len(chunk)
            translated.extend(result)
        return translated


class LyricsResolver:
    def __init__(
        self, native: Callable[[str], str | None], lrclib: LrcLibClient | None = None
    ) -> None:
        self.native = native
        self.lrclib = lrclib or LrcLibClient()

    def fetch(
        self, item: LibraryItem, duration_ms: int = 0, provider: str = "auto"
    ) -> LyricsDocument | None:
        provider = provider.lower()
        if provider in {"auto", "lrclib"}:
            try:
                alternative = self.lrclib.lyrics(item, duration_ms)
                if alternative:
                    return alternative
            except Exception:
                if provider == "lrclib":
                    raise
        if provider in {"auto", "youtube"}:
            value = self.native(item.id)
            if value:
                synced = parse_lrc(value)
                return LyricsDocument(value.strip(), "YouTube Music", synced)
        return None
