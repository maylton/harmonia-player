from __future__ import annotations

from datetime import datetime
from typing import Any

from .insights import PlaybackInsights
from .models import ExploreDestination, HistoryEntry, LibraryItem

CATEGORY_LABELS = {
    "songs": "Músicas curtidas",
    "albums": "Álbuns",
    "artists": "Artistas",
    "playlists": "Playlists",
    "uploads": "Uploads",
    "uploaded-albums": "Álbuns enviados",
    "podcasts": "Podcasts",
    "podcast-episodes": "Episódios",
}
MONTH_NAMES = ("Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez")


def item_map(item: LibraryItem, *, index: int = -1, liked: bool = False) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "subtitle": item.subtitle,
        "thumbnail": item.thumbnail or "",
        "kind": item.kind,
        "playlistId": item.playlist_id or "",
        "setVideoId": item.set_video_id or "",
        "index": index,
        "liked": liked,
    }


def destination_map(item: ExploreDestination, *, index: int = -1) -> dict[str, Any]:
    return {
        "title": item.title,
        "browseId": item.browse_id,
        "params": item.params or "",
        "index": index,
    }


def unique_items(items: list[LibraryItem]) -> list[LibraryItem]:
    result: list[LibraryItem] = []
    seen: set[str] = set()
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        result.append(item)
    return result


def section_map(
    title: str,
    items: list[LibraryItem],
    liked_ids: set[str],
    *,
    limit: int = 12,
) -> dict[str, Any]:
    unique = unique_items(items)
    song_section = bool(unique) and all(item.kind == "songs" for item in unique)
    selected = unique[: max(limit, 24) if song_section else limit]
    mapped = [
        item_map(item, index=index, liked=item.id in liked_ids)
        for index, item in enumerate(selected)
    ]
    columns = [mapped[index : index + 4] for index in range(0, len(mapped), 4)]
    return {
        "title": title,
        "songSection": song_section,
        "items": mapped,
        "columns": columns if song_section else [],
    }


def history_map(entries: list[HistoryEntry], liked_ids: set[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if entry.source == "local" and entry.played_at:
            played = datetime.fromtimestamp(entry.played_at)
            group = played.strftime("%d/%m/%Y")
            played_label = played.strftime("%H:%M")
        else:
            group = entry.group or "YouTube Music"
            played_label = "YouTube Music" if entry.source == "remote" else ""
        result.append(
            {
                **item_map(entry.item, index=index, liked=entry.item.id in liked_ids),
                "entryId": entry.id if entry.id is not None else -1,
                "source": entry.source,
                "group": group,
                "playedLabel": played_label,
                "canRemove": entry.source == "local" or bool(entry.feedback_token),
            }
        )
    return result


def insights_map(data: PlaybackInsights, liked_ids: set[str]) -> dict[str, Any]:
    minutes = data.listened_minutes
    if minutes >= 60:
        hours, remainder = divmod(minutes, 60)
        listened_label = f"{hours} h {remainder} min" if remainder else f"{hours} h"
    else:
        listened_label = f"{minutes} min"
    maximum = max(data.monthly_plays) or 1
    return {
        "year": data.year,
        "totalPlays": data.total_plays,
        "uniqueTracks": data.unique_tracks,
        "listenedMinutes": minutes,
        "listenedLabel": listened_label,
        "topTracks": [
            {
                **item_map(ranked.item, index=index, liked=ranked.item.id in liked_ids),
                "plays": ranked.plays,
                "listenedMs": ranked.listened_ms,
            }
            for index, ranked in enumerate(data.top_tracks)
        ],
        "topArtists": [{"name": ranked.name, "plays": ranked.plays} for ranked in data.top_artists],
        "months": [
            {"label": label, "plays": plays, "ratio": plays / maximum}
            for label, plays in zip(MONTH_NAMES, data.monthly_plays, strict=True)
        ],
    }
