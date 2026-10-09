"""Lyrics for a track: providers in order, and translation; independent from GTK."""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from collections.abc import Callable

from .lrc import parse_lrc
from .lyrics_providers import LrcLibClient, LyricsPlusClient, is_word_synced
from .models import LibraryItem, LyricsDocument

__all__ = ["GoogleTranslationClient", "LrcLibClient", "LyricsResolver", "parse_lrc"]
LOGGER = logging.getLogger(__name__)


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
    """Ask the providers in order.

    Automatic: LyricsPlus when it has the lyrics timed by word, then LRCLIB,
    then whatever LyricsPlus had by line, then YouTube Music's own lyrics.
    Choosing a provider asks only that one, and its errors are reported.
    """

    def __init__(
        self,
        native: Callable[[str], str | None],
        lrclib: LrcLibClient | None = None,
        lyricsplus: LyricsPlusClient | None = None,
    ) -> None:
        self.native = native
        self.lrclib = lrclib or LrcLibClient()
        self.lyricsplus = lyricsplus or LyricsPlusClient()

    def fetch(
        self, item: LibraryItem, duration_ms: int = 0, provider: str = "auto"
    ) -> LyricsDocument | None:
        provider = provider.lower()
        if provider == "lyricsplus":
            return self.lyricsplus.lyrics(item, duration_ms)
        if provider == "lrclib":
            return self.lrclib.lyrics(item, duration_ms)
        if provider == "auto":
            by_line = self._quietly(self.lyricsplus, item, duration_ms)
            if by_line is not None and is_word_synced(by_line):
                return by_line
            found = self._quietly(self.lrclib, item, duration_ms) or by_line
            if found is not None:
                return found
        if provider in {"auto", "youtube"}:
            value = self.native(item.id)
            if value:
                return LyricsDocument(value.strip(), "YouTube Music", parse_lrc(value))
        return None

    @staticmethod
    def _quietly(client, item: LibraryItem, duration_ms: int) -> LyricsDocument | None:
        try:
            return client.lyrics(item, duration_ms)
        except Exception:
            LOGGER.debug("Provedor de letras falhou: %s", type(client).__name__, exc_info=True)
            return None
