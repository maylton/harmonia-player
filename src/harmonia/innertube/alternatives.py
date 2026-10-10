"""Another publication of the same song, for tracks YouTube age-restricts.

YouTube refuses an age-restricted track to every client that returns a direct
stream, even signed in. The same recording is often also published without
the restriction (the artist's own upload of the music video, for example), so
Harmonia plays that one instead: same title, same artists, same length to
within two seconds, and never a live take, cover or edit (song_match.py).
"""

from __future__ import annotations

from typing import Any

from ..i18n import _
from ..song_match import same_recording
from .protocol import InnerTubeError

# Search results checked, per category, for a matching publication.
CANDIDATES_PER_SEARCH = 6


def substitute_notice() -> str:
    """What both frontends say when another publication plays."""
    return _("Faixa com restrição de idade: tocando outra publicação da mesma música")


def song_details(payload: dict[str, Any]) -> tuple[str, str, int | None] | None:
    """(title, artists, seconds) of a /player response's videoDetails."""
    details = payload.get("videoDetails") or {}
    title = str(details.get("title") or "").strip()
    if not title:
        return None
    try:
        seconds = int(details.get("lengthSeconds") or 0) or None
    except (TypeError, ValueError):
        seconds = None
    return title, str(details.get("author") or "").strip(), seconds


def alternative_ids(client, details: tuple[str, str, int | None], exclude: str) -> list[str]:
    """Ids of results that are the same recording, songs before videos."""
    title, artists, seconds = details
    query = f"{title} {artists}".strip()
    found: list[str] = []
    for category in ("songs", "videos"):
        try:
            items = client.search_category(query, category).items[:CANDIDATES_PER_SEARCH]
        except (InnerTubeError, ValueError):  # a failed search only means fewer candidates
            continue
        for item in items:
            fresh = item.id and item.id != exclude and item.id not in found
            if fresh and same_recording(title, artists, seconds, item):
                found.append(item.id)
    return found
