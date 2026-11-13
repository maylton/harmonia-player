"""Lyrics for a track: providers in order, and translation; independent from GTK."""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from .lrc import parse_lrc
from .lyrics_providers import BetterLyricsClient, LrcLibClient, LyricsPlusClient, is_word_synced
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
    """Ask the lyrics services, all at once when choosing automatically.

    Automatic: BetterLyrics, LyricsPlus and LRCLIB are asked together, as
    the first to answer used to wait for a slow one before them. Lyrics timed
    by word win as soon as one arrives, BetterLyrics' first; lyrics timed by
    line wait WORD_GRACE seconds more for one timed by word, then BetterLyrics'
    come first, LRCLIB's and LyricsPlus' after. YouTube Music's own lyrics
    come last.
    Choosing a provider asks only that one, and its errors are reported.
    """

    PREFERENCE = ("betterlyrics", "lyricsplus", "lrclib")  # timed by word
    BY_LINE = ("betterlyrics", "lrclib", "lyricsplus")
    WORD_GRACE = 2.0  # seconds
    DEADLINE = 6.0  # seconds for all of them

    def __init__(
        self,
        native: Callable[[str], str | None],
        lrclib: LrcLibClient | None = None,
        lyricsplus: LyricsPlusClient | None = None,
        betterlyrics: BetterLyricsClient | None = None,
    ) -> None:
        self.native = native
        self.lrclib = lrclib or LrcLibClient()
        self.lyricsplus = lyricsplus or LyricsPlusClient()
        self.betterlyrics = betterlyrics or BetterLyricsClient()

    def fetch(
        self, item: LibraryItem, duration_ms: int = 0, provider: str = "auto"
    ) -> LyricsDocument | None:
        provider = provider.lower()
        if provider in self.PREFERENCE:
            return getattr(self, provider).lyrics(item, duration_ms)
        if provider == "auto":
            return self._first_of_all(item, duration_ms)
        if provider == "youtube":
            return self._youtube(item)
        return None

    def _youtube(self, item: LibraryItem) -> LyricsDocument | None:
        value = self.native(item.id)
        if value:
            return LyricsDocument(value.strip(), "YouTube Music", parse_lrc(value))
        return None

    def _first_of_all(self, item: LibraryItem, duration_ms: int) -> LyricsDocument | None:
        pool = ThreadPoolExecutor(len(self.PREFERENCE) + 1, thread_name_prefix="lyrics")
        pending = {
            pool.submit(self._quietly, getattr(self, name), item, duration_ms): name
            for name in self.PREFERENCE
        }
        # YouTube Music's own lyrics, the last resort, are asked at once too.
        youtube = pool.submit(self._quietly_youtube, item)
        results: dict[str, LyricsDocument | None] = {}
        started = time.monotonic()
        settle_by = started + self.DEADLINE
        try:
            while pending:
                done, _ = wait(pending, timeout=max(0.0, settle_by - time.monotonic()),
                               return_when=FIRST_COMPLETED)  # fmt: skip
                if not done:
                    break
                for future in done:
                    name = pending.pop(future)
                    results[name] = future.result()
                word = self._preferred(results, word_only=True)
                if word is not None:
                    return word
                if any(results.values()):
                    settle_by = min(settle_by, time.monotonic() + self.WORD_GRACE)
            found = self._preferred(results, word_only=False)
            if found is not None:
                return found
            return youtube.result(timeout=max(1.0, settle_by - time.monotonic() + 2))
        except TimeoutError:
            return None
        finally:
            # A slow service finishes on its own, without holding the lyrics.
            pool.shutdown(wait=False, cancel_futures=True)

    def _preferred(self, results, *, word_only: bool) -> LyricsDocument | None:
        """The first in PREFERENCE timed by word; or, when ``word_only`` is off,
        timed at all, then plain."""
        for name in self.PREFERENCE:
            document = results.get(name)
            if document is not None and is_word_synced(document):
                return document
        if word_only:
            return None
        found = [results[name] for name in self.BY_LINE if results.get(name) is not None]
        return next((document for document in found if document.synced), None) or next(
            iter(found), None
        )

    def _quietly_youtube(self, item: LibraryItem) -> LyricsDocument | None:
        try:
            return self._youtube(item)
        except Exception:
            LOGGER.debug("Letra do YouTube Music falhou", exc_info=True)
            return None

    @staticmethod
    def _quietly(client, item: LibraryItem, duration_ms: int) -> LyricsDocument | None:
        try:
            return client.lyrics(item, duration_ms)
        except Exception:
            LOGGER.debug("Provedor de letras falhou: %s", type(client).__name__, exc_info=True)
            return None
