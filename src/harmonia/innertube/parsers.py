"""Pure parsers from InnerTube JSON responses to Harmonia models."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from ..i18n import _
from ..models import (
    AccountProfile,
    ArtistPage,
    ArtistSection,
    ExploreData,
    ExploreDestination,
    HistoryEntry,
    HomeSection,
    LibraryItem,
)
from .protocol import (
    InnerTubeError,
)


def _walk(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _runs_text(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    runs = value.get("runs") or []
    return "".join(str(run.get("text", "")) for run in runs if isinstance(run, dict)).strip()


def _best_thumbnail(renderer: dict[str, Any]) -> str | None:
    candidates: list[dict[str, Any]] = []
    for node in _walk(renderer):
        thumbs = node.get("thumbnails")
        if isinstance(thumbs, list):
            candidates.extend(x for x in thumbs if isinstance(x, dict) and x.get("url"))
    if not candidates:
        return None
    return max(candidates, key=lambda x: int(x.get("width", 0) or 0)).get("url")


def parse_account_profile(payload: dict[str, Any]) -> AccountProfile:
    """Extract the active YouTube Music identity from account/account_menu."""
    for node in _walk(payload):
        renderer = node.get("activeAccountHeaderRenderer")
        if not isinstance(renderer, dict):
            continue
        name = _runs_text(renderer.get("accountName"))
        if not name:
            continue
        return AccountProfile(
            name=name,
            thumbnail=_best_thumbnail(renderer.get("accountPhoto") or {}),
            email=_runs_text(renderer.get("email")),
            channel_handle=_runs_text(renderer.get("channelHandle")),
        )
    raise InnerTubeError(_("O YouTube Music não retornou o perfil da conta ativa."))


def _endpoint(renderer: dict[str, Any]) -> tuple[str, str | None]:
    primary = renderer.get("navigationEndpoint") or renderer.get("onTap") or {}
    if isinstance(primary, dict):
        watch = primary.get("watchEndpoint")
        if isinstance(watch, dict) and watch.get("videoId"):
            return str(watch["videoId"]), watch.get("playlistId")
        browse = primary.get("browseEndpoint")
        if isinstance(browse, dict) and browse.get("browseId"):
            primary_id = str(browse["browseId"])
            if not primary_id.startswith("MPED"):
                return primary_id, None
    browse_id = ""
    playlist_id = None
    video_id = ""
    for node in _walk(renderer):
        browse = node.get("browseEndpoint")
        if isinstance(browse, dict) and browse.get("browseId") and not browse_id:
            browse_id = str(browse["browseId"])
        watch = node.get("watchEndpoint")
        if isinstance(watch, dict):
            video_id = video_id or str(watch.get("videoId", ""))
            playlist_id = playlist_id or watch.get("playlistId")
    return video_id or browse_id, playlist_id


_ARTIST_PAGES = {"MUSIC_PAGE_TYPE_ARTIST", "MUSIC_PAGE_TYPE_USER_CHANNEL"}
_ALBUM_PAGES = {"MUSIC_PAGE_TYPE_ALBUM", "MUSIC_PAGE_TYPE_AUDIOBOOK"}


def _linked_pages(renderer: dict[str, Any]) -> dict[str, str]:
    """Return the linked credits of a byline: the first artist and album, plus all links."""
    containers = [renderer.get("subtitle"), renderer.get("longBylineText")]
    for column in renderer.get("flexColumns", [])[1:]:
        if isinstance(column, dict):
            containers.append(
                column.get("musicResponsiveListItemFlexColumnRenderer", {}).get("text")
            )
    links: dict = {}
    credits: list[tuple[str, str, str]] = []
    for container in containers:
        runs = container.get("runs", []) if isinstance(container, dict) else []
        for run in runs:
            browse = ((run or {}).get("navigationEndpoint") or {}).get("browseEndpoint") or {}
            page_type = (
                (browse.get("browseEndpointContextSupportedConfigs") or {})
                .get("browseEndpointContextMusicConfig", {})
                .get("pageType")
            )
            browse_id, text = browse.get("browseId"), str(run.get("text", "")).strip()
            if not browse_id or not text:
                continue
            kind = (
                "artist"
                if page_type in _ARTIST_PAGES
                else "album"
                if page_type in _ALBUM_PAGES
                else None
            )
            if not kind or any(credit[2] == browse_id for credit in credits):
                continue
            credits.append((kind, text, str(browse_id)))
            if kind == "artist" and "artist_id" not in links:
                links.update(artist=text, artist_id=str(browse_id))
            elif kind == "album" and "album_id" not in links:
                links.update(album=text, album_id=str(browse_id))
    if credits:
        links["links"] = tuple(credits)
    return links


def _is_explicit(renderer: dict[str, Any]) -> bool:
    """Whether the renderer carries YouTube Music's explicit-content badge."""
    badges = [renderer.get("badges"), renderer.get("subtitleBadges")]
    return any(
        (node.get("icon") or {}).get("iconType") == "MUSIC_EXPLICIT_BADGE" for node in _walk(badges)
    )


def _kind_for_id(item_id: str, default: str) -> str:
    if item_id.startswith("MPSP"):
        return "podcasts"
    if item_id.startswith("MPRE"):
        return "albums"
    if item_id.startswith("UC"):
        return "artists"
    if item_id.startswith(("VL", "PL", "OLAK")):
        return "playlists"
    return "songs" if item_id else default


def _set_video_id(renderer: dict[str, Any]) -> str | None:
    for node in _walk(renderer):
        if node.get("playlistSetVideoId"):
            return str(node["playlistSetVideoId"])
    return None


def parse_library_items(payload: dict[str, Any], kind: str = "item") -> list[LibraryItem]:
    """Parse both grid and responsive list renderers from browse responses."""
    items: list[LibraryItem] = []
    seen: set[str] = set()
    renderer_names = (
        "musicTwoRowItemRenderer",
        "musicResponsiveListItemRenderer",
        "musicMultiRowListItemRenderer",
    )
    for node in _walk(payload):
        for name in renderer_names:
            renderer = node.get(name)
            if not isinstance(renderer, dict):
                continue
            title = _runs_text(renderer.get("title")) or _runs_text(
                renderer.get("flexColumns", [{}])[0]
                .get("musicResponsiveListItemFlexColumnRenderer", {})
                .get("text", {})
            )
            if not title:
                continue
            subtitle = _runs_text(renderer.get("subtitle"))
            if not subtitle:
                cols = renderer.get("flexColumns", [])
                texts = [
                    _runs_text(
                        c.get("musicResponsiveListItemFlexColumnRenderer", {}).get("text", {})
                    )
                    for c in cols[1:]
                    if isinstance(c, dict)
                ]
                subtitle = " · ".join(x for x in texts if x)
            fixed = renderer.get("fixedColumns", [])
            duration = " · ".join(
                text
                for column in fixed
                if isinstance(column, dict)
                for text in [
                    _runs_text(
                        column.get("musicResponsiveListItemFixedColumnRenderer", {}).get("text", {})
                    )
                ]
                if text
            )
            if duration and duration not in subtitle:
                subtitle = " · ".join(value for value in (subtitle, duration) if value)
            item_id, playlist_id = _endpoint(renderer)
            if not item_id:
                continue
            stable_id = item_id or f"{kind}:{title}:{subtitle}"
            if stable_id in seen:
                continue
            seen.add(stable_id)
            actual_kind = _kind_for_id(item_id, kind) if kind == "auto" else kind
            items.append(
                LibraryItem(
                    stable_id,
                    title,
                    subtitle,
                    _best_thumbnail(renderer),
                    actual_kind,
                    playlist_id,
                    _set_video_id(renderer),
                    **_linked_pages(renderer),
                    explicit=_is_explicit(renderer),
                )
            )
    return items


def find_continuation(payload: dict[str, Any]) -> str | None:
    for node in _walk(payload):
        command = node.get("continuationCommand")
        if isinstance(command, dict) and command.get("token"):
            return str(command["token"])
        data = node.get("nextContinuationData")
        if isinstance(data, dict) and data.get("continuation"):
            return str(data["continuation"])
    return None


def find_browse_endpoint(payload: dict[str, Any], page_type: str) -> tuple[str, str | None] | None:
    """Find a typed browse endpoint embedded in a watch-next response."""
    for node in _walk(payload):
        endpoint = node.get("browseEndpoint")
        if not isinstance(endpoint, dict) or not endpoint.get("browseId"):
            continue
        config = (endpoint.get("browseEndpointContextSupportedConfigs") or {}).get(
            "browseEndpointContextMusicConfig"
        ) or {}
        if config.get("pageType") == page_type:
            return str(endpoint["browseId"]), endpoint.get("params")
    return None


def find_video_counterpart(payload: dict[str, Any]) -> str | None:
    """Return YouTube Music's linked official music video, when present.

    The ``next`` response for an audio track can contain a ``counterpart``
    renderer. Its watch endpoint carries ``MUSIC_VIDEO_TYPE_OMV`` for the
    official music video, so this relationship is authoritative and does not
    require guessing from a title or a search result.
    """
    for node in _walk(payload):
        counterpart = node.get("counterpartRenderer")
        if not isinstance(counterpart, dict):
            continue
        renderer = counterpart.get("playlistPanelVideoRenderer")
        if not isinstance(renderer, dict):
            continue
        video_id = renderer.get("videoId")
        endpoint = (renderer.get("navigationEndpoint") or {}).get("watchEndpoint") or {}
        music_config = (endpoint.get("watchEndpointMusicSupportedConfigs") or {}).get(
            "watchEndpointMusicConfig"
        ) or {}
        if video_id and music_config.get("musicVideoType") == "MUSIC_VIDEO_TYPE_OMV":
            return str(video_id)
    return None


def parse_lyrics(payload: dict[str, Any]) -> str | None:
    """Extract the plain lyrics returned by a YouTube Music lyrics tab."""
    for node in _walk(payload):
        renderer = node.get("musicDescriptionShelfRenderer")
        if not isinstance(renderer, dict):
            continue
        lyrics = _runs_text(renderer.get("description"))
        if lyrics:
            return lyrics
    return None


def parse_search_suggestions(payload: dict[str, Any]) -> list[str]:
    """Extract query suggestions while ignoring recommended media rows."""
    suggestions: list[str] = []
    seen: set[str] = set()
    for node in _walk(payload):
        renderer = node.get("searchSuggestionRenderer")
        if not isinstance(renderer, dict):
            continue
        value = _runs_text(renderer.get("suggestion")).strip()
        folded = value.casefold()
        if value and folded not in seen:
            seen.add(folded)
            suggestions.append(value)
    return suggestions


def parse_watch_queue(payload: dict[str, Any], audio_only: bool = True) -> list[LibraryItem]:
    """Parse the playable queue returned by the watch-next radio endpoint."""
    items: list[LibraryItem] = []
    seen: set[str] = set()
    for node in _walk(payload):
        renderer = node.get("playlistPanelVideoRenderer")
        if not isinstance(renderer, dict):
            continue
        video_id = renderer.get("videoId")
        title = _runs_text(renderer.get("title"))
        endpoint = (renderer.get("navigationEndpoint") or {}).get("watchEndpoint") or {}
        music_config = (endpoint.get("watchEndpointMusicSupportedConfigs") or {}).get(
            "watchEndpointMusicConfig"
        ) or {}
        music_type = music_config.get("musicVideoType")
        if not video_id or not title or video_id in seen:
            continue
        if audio_only and music_type and music_type != "MUSIC_VIDEO_TYPE_ATV":
            continue
        seen.add(str(video_id))
        subtitle = _runs_text(renderer.get("longBylineText")) or _runs_text(
            renderer.get("shortBylineText")
        )
        items.append(
            LibraryItem(
                str(video_id),
                title,
                subtitle,
                _best_thumbnail(renderer),
                "songs",
                **_linked_pages(renderer),
                explicit=_is_explicit(renderer),
            )
        )
    return items


def parse_home_sections(payload: dict[str, Any]) -> list[HomeSection]:
    sections: list[HomeSection] = []
    seen: set[str] = set()
    for node in _walk(payload):
        renderer = node.get("musicCarouselShelfRenderer") or node.get("musicShelfRenderer")
        if not isinstance(renderer, dict):
            continue
        header = (renderer.get("header") or {}).get("musicCarouselShelfBasicHeaderRenderer", {})
        title = _runs_text(header.get("title")) or _runs_text(renderer.get("title"))
        if not title or title in seen:
            continue
        contents = renderer.get("contents") or []
        items: list[LibraryItem] = []
        for content in contents:
            items.extend(parse_library_items(content, "auto"))
        if items:
            seen.add(title)
            sections.append(HomeSection(title, items))
    return sections


def parse_explore(payload: dict[str, Any]) -> ExploreData:
    destinations: list[ExploreDestination] = []
    seen: set[tuple[str, str, str | None]] = set()
    for node in _walk(payload):
        renderer = node.get("musicNavigationButtonRenderer")
        if not isinstance(renderer, dict):
            continue
        title = _runs_text(renderer.get("buttonText")) or _runs_text(renderer.get("text"))
        command = renderer.get("clickCommand") or renderer.get("navigationEndpoint") or {}
        endpoint = command.get("browseEndpoint") if isinstance(command, dict) else None
        if not title or not isinstance(endpoint, dict) or not endpoint.get("browseId"):
            continue
        value = (title, str(endpoint["browseId"]), endpoint.get("params"))
        if value not in seen:
            seen.add(value)
            destinations.append(ExploreDestination(*value))
    genres = [
        item for item in destinations if item.browse_id == "FEmusic_moods_and_genres_category"
    ]
    shortcuts = [item for item in destinations if item not in genres]
    sections = parse_home_sections(payload)
    if not sections:
        items = parse_library_items(payload, "auto")
        if items:
            sections = [HomeSection(_("Músicas"), items)]
    return ExploreData(sections, shortcuts, genres)


def _section_browse_target(renderer: dict[str, Any]) -> tuple[str | None, str | None]:
    candidates = [renderer.get("bottomEndpoint") or {}]
    header = (renderer.get("header") or {}).get("musicCarouselShelfBasicHeaderRenderer") or {}
    candidates.append(header)
    for candidate in candidates:
        for node in _walk(candidate):
            endpoint = node.get("browseEndpoint")
            if isinstance(endpoint, dict) and endpoint.get("browseId"):
                return str(endpoint["browseId"]), endpoint.get("params")
    return None, None


def parse_artist_page(payload: dict[str, Any], artist_id: str) -> ArtistPage:
    """Parse the native artist header and its independently navigable shelves."""
    title = ""
    description = ""
    thumbnail = None
    subscribers = ""
    subscribed = False
    for node in _walk(payload):
        header = node.get("musicImmersiveHeaderRenderer") or node.get("musicVisualHeaderRenderer")
        if not isinstance(header, dict):
            continue
        title = _runs_text(header.get("title"))
        description = _runs_text(header.get("description"))
        thumbnail = _best_thumbnail(header)
        subscribers = _runs_text(header.get("monthlyListenerCount"))
        subscribe = (header.get("subscriptionButton") or {}).get("subscribeButtonRenderer") or {}
        subscribed = bool(subscribe.get("subscribed"))
        break
    if not description:
        for node in _walk(payload):
            shelf = node.get("musicDescriptionShelfRenderer")
            if isinstance(shelf, dict):
                description = _runs_text(shelf.get("description"))
                if description:
                    break

    sections: list[ArtistSection] = []
    seen: set[str] = set()
    for node in _walk(payload):
        renderer = node.get("musicCarouselShelfRenderer") or node.get("musicShelfRenderer")
        if not isinstance(renderer, dict):
            continue
        heading = (renderer.get("header") or {}).get("musicCarouselShelfBasicHeaderRenderer") or {}
        section_title = _runs_text(heading.get("title")) or _runs_text(renderer.get("title"))
        if not section_title or section_title in seen:
            continue
        items = parse_library_items({"contents": renderer.get("contents") or []}, "auto")
        if not items:
            continue
        browse_id, params = _section_browse_target(renderer)
        seen.add(section_title)
        sections.append(ArtistSection(section_title, items, browse_id, params))
    return ArtistPage(
        artist_id,
        title or _("Artista"),
        description,
        thumbnail,
        subscribers,
        subscribed,
        sections,
    )


def parse_remote_history(payload: dict[str, Any]) -> list[HistoryEntry]:
    """Parse account history and retain the feedback token used for removal."""
    entries: list[HistoryEntry] = []
    seen: set[tuple[str, str]] = set()
    for node in _walk(payload):
        shelf = node.get("musicShelfRenderer")
        if not isinstance(shelf, dict):
            continue
        group = _runs_text(shelf.get("title")) or "YouTube Music"
        for content in shelf.get("contents") or []:
            items = parse_library_items(content, "songs")
            if not items:
                continue
            item = items[0]
            key = (group, item.id)
            if key in seen:
                continue
            feedback_token = None
            for inner in _walk(content):
                endpoint = inner.get("feedbackEndpoint")
                actions = endpoint.get("actions") if isinstance(endpoint, dict) else None
                if endpoint and any("hideEnclosingAction" in action for action in (actions or [])):
                    feedback_token = endpoint.get("feedbackToken")
                    break
            seen.add(key)
            entries.append(
                HistoryEntry(
                    None, item, source="remote", group=group, feedback_token=feedback_token
                )
            )
    return entries
