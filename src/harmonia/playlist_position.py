"""Where a track goes when added to a playlist: the end, or the start.

YouTube Music always appends. For the start, the edit's answer gives the new
entry's setVideoId, and a second edit moves it before the playlist's first
entry. Local playlists just insert at the front.
"""

from __future__ import annotations

from typing import Any

from .models import LibraryItem

POSITIONS = ("end", "start")
DEFAULT_POSITION = "end"


def with_item(items: list[LibraryItem], item: LibraryItem, position: str) -> list[LibraryItem]:
    """The playlist with ``item`` added; a track already in it is left where it is."""
    if any(existing.id == item.id for existing in items):
        return list(items)
    return [item, *items] if position == "start" else [*items, item]


def added_set_video_id(payload: Any, video_id: str) -> str | None:
    """The setVideoId YouTube gave the entry just added for ``video_id``."""
    for result in (payload or {}).get("playlistEditResults") or []:
        data = (result or {}).get("playlistEditVideoAddedResultData") or {}
        if data.get("videoId") == video_id and data.get("setVideoId"):
            return str(data["setVideoId"])
    return None


def move_before_action(set_video_id: str, successor_set_video_id: str) -> dict[str, str]:
    return {
        "action": "ACTION_MOVE_VIDEO_BEFORE",
        "setVideoId": set_video_id,
        "movedSetVideoIdSuccessor": successor_set_video_id,
    }
