"""What every lyrics provider needs: the track's title and artist, and JSON over HTTP."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections.abc import Callable

from ..models import LibraryItem

USER_AGENT = "Harmonia/0.1 (+https://github.com/maylton/harmonia-player)"


def clean_title(title: str) -> str:
    return re.sub(
        r"\s*[\[(](?:official|lyrics?|audio|video|visuali[sz]er|remaster(?:ed)?).*?[\])]\s*",
        " ",
        title,
        flags=re.IGNORECASE,
    ).strip()


def lyrics_metadata(item: LibraryItem) -> tuple[str, str | None]:
    """The artist and album a track's subtitle names, as lyrics services expect them."""
    parts = [part.strip() for part in re.split(r"\s*[·•]\s*", item.subtitle or "") if part.strip()]
    noise = re.compile(r"^(?:música|music|vídeo|video|podcast|\d+(?::\d+){1,2})$", re.IGNORECASE)
    useful = [part for part in parts if not noise.match(part) and "visualiza" not in part.lower()]
    artist = useful[0] if useful else ""
    album = useful[-1] if len(useful) > 1 else None
    return artist, album


def get_json(
    opener: Callable[..., object], url: str, params: dict[str, str], *, timeout: float = 8
):
    request = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with opener(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))
