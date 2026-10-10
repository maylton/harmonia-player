"""Small native port of Metrolist's authenticated InnerTube library client.

It deliberately uses only Python's standard library. This module browses and
searches; the session, the streams and the account changes have their own.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..accounts import YouTubeIdentity, parse_identities, same_login
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
    SearchGroup,
)
from .edits import EditsMixin
from .parsers import (
    find_browse_endpoint,
    find_continuation,
    find_video_counterpart,
    parse_account_profile,
    parse_artist_page,
    parse_explore,
    parse_home_sections,
    parse_library_items,
    parse_lyrics,
    parse_remote_history,
    parse_search_suggestions,
    parse_watch_queue,
)
from .protocol import (
    LIBRARIES,
    SEARCH_FILTER_SONGS,
    SEARCH_FILTERS,
    SEARCH_TITLES,
)
from .restricted import RestrictedStreamsMixin
from .session import InnerTubeSession
from .streams import _STREAM_CACHE, StreamsMixin

__all__ = ["_STREAM_CACHE", "InnerTubeClient"]


class InnerTubeClient(StreamsMixin, RestrictedStreamsMixin, EditsMixin, InnerTubeSession):
    """The InnerTube API as Harmonia uses it: browsing and search here, the
    session (session.py), streams (streams.py, restricted.py) and account
    changes (edits.py) in their own modules."""

    def account_profile(self) -> AccountProfile:
        return parse_account_profile(self._api_post("account/account_menu", {}))

    def identities(self) -> list[YouTubeIdentity]:
        """The channels of this login the session can act as (accounts.py)."""
        payload = self._api_post(
            "account/accounts_list",
            {
                "requestType": "ACCOUNTS_LIST_REQUEST_TYPE_CHANNEL_SWITCHER",
                "callCircumstance": "SWITCHING_USERS_FULL",
            },
            as_identity=False,
        )
        return same_login(parse_identities(payload), self.session_data_sync_id)

    def search(self, query: str) -> list[LibraryItem]:
        query = query.strip()
        if not query:
            return []
        payload = self._api_post(
            "search", {"query": query, "params": SEARCH_FILTER_SONGS}, authenticated=False
        )
        return parse_library_items(payload, "songs")

    def search_category(
        self,
        query: str,
        category: str,
        continuation: str | None = None,
    ) -> SearchGroup:
        if category not in SEARCH_FILTERS:
            raise ValueError(
                _("Categoria de busca desconhecida: {category}").format(category=category)
            )
        query = query.strip()
        if not query:
            return SearchGroup(category, SEARCH_TITLES[category], [])
        body: dict[str, Any] = {"query": query, "params": SEARCH_FILTERS[category]}
        endpoint = "search"
        if continuation:
            token = urllib.parse.quote(continuation, safe="")
            endpoint = f"search?continuation={token}&ctoken={token}"
        payload = self._api_post(endpoint, body, authenticated=False)
        items = parse_library_items(payload, category)
        # Filtered search occasionally carries navigation renderers from a
        # neighbouring shelf.  Preserve videos as playable while keeping each
        # non-playable group semantically strict.
        if category in ("songs", "videos"):
            for item in items:
                item.kind = category
        else:
            items = [item for item in items if item.kind == category]
        return SearchGroup(category, SEARCH_TITLES[category], items, find_continuation(payload))

    def search_suggestions(self, query: str) -> list[str]:
        query = query.strip()
        if len(query) < 2:
            return []
        payload = self._api_post(
            "music/get_search_suggestions",
            {"input": query},
            authenticated=False,
        )
        return parse_search_suggestions(payload)

    def home(self, all_pages: bool = True, max_pages: int = 10) -> list[HomeSection]:
        """Load every personalized Home shelf, including continuation pages."""
        payload = self._post({"browseId": "FEmusic_home"})
        result: list[HomeSection] = []
        by_title: dict[str, HomeSection] = {}
        seen_tokens: set[str] = set()
        pages = 0
        while True:
            pages += 1
            for incoming in parse_home_sections(payload):
                section = by_title.get(incoming.title)
                if section is None:
                    section = HomeSection(incoming.title, [])
                    by_title[incoming.title] = section
                    result.append(section)
                known = {item.id for item in section.items}
                section.items.extend(item for item in incoming.items if item.id not in known)
            continuation = find_continuation(payload)
            if (
                not all_pages
                or not continuation
                or continuation in seen_tokens
                or pages >= max_pages
            ):
                break
            seen_tokens.add(continuation)
            payload = self._post({"continuation": continuation})
        return result

    def explore(self) -> ExploreData:
        return parse_explore(self._post({"browseId": "FEmusic_explore"}))

    def discovery(self, destination: ExploreDestination) -> ExploreData:
        body = {"browseId": destination.browse_id}
        if destination.params:
            body["params"] = destination.params
        return parse_explore(self._post(body))

    def artist(self, artist_id: str) -> ArtistPage:
        if not artist_id:
            raise ValueError(_("O artista não possui um identificador"))
        return parse_artist_page(self._post({"browseId": artist_id}), artist_id)

    def artist_section(self, section: ArtistSection) -> list[LibraryItem]:
        if not section.browse_id:
            return list(section.items)
        body: dict[str, Any] = {"browseId": section.browse_id}
        if section.params:
            body["params"] = section.params
        return parse_library_items(self._post(body), "auto")

    def history(self, max_pages: int = 3) -> list[HistoryEntry]:
        payload = self._post({"browseId": "FEmusic_history"})
        entries = parse_remote_history(payload)
        seen_tokens: set[str] = set()
        pages = 1
        continuation = find_continuation(payload)
        while continuation and continuation not in seen_tokens and pages < max_pages:
            seen_tokens.add(continuation)
            payload = self._post({"continuation": continuation})
            entries.extend(parse_remote_history(payload))
            continuation = find_continuation(payload)
            pages += 1
        unique: dict[tuple[str, str], HistoryEntry] = {}
        for entry in entries:
            unique[(entry.group, entry.item.id)] = entry
        return list(unique.values())

    def remove_history_item(self, feedback_token: str) -> None:
        if not feedback_token:
            raise ValueError(_("O YouTube Music não forneceu um token de remoção"))
        self._api_post("feedback", {"feedbackTokens": [feedback_token]})

    def lyrics(self, video_id: str) -> str | None:
        """Load the native YouTube Music lyrics tab for a track."""
        if not video_id:
            return None
        next_payload = self._api_post("next", {"videoId": video_id}, authenticated=True)
        endpoint = find_browse_endpoint(next_payload, "MUSIC_PAGE_TYPE_TRACK_LYRICS")
        if endpoint is None:
            return None
        browse_id, params = endpoint
        body = {"browseId": browse_id}
        if params:
            body["params"] = params
        return parse_lyrics(self._post(body))

    def video_counterpart(self, video_id: str) -> str | None:
        """Return the official music-video counterpart linked to an audio track."""
        if not video_id:
            return None
        payload = self._api_post("next", {"videoId": video_id}, authenticated=True)
        return find_video_counterpart(payload)

    def watch_item(self, video_id: str) -> LibraryItem | None:
        """The track or video behind a video id, as the player's queue shows it."""
        if not video_id:
            return None
        payload = self._api_post("next", {"videoId": video_id}, authenticated=self.authenticated)
        return next(
            (item for item in parse_watch_queue(payload, audio_only=False) if item.id == video_id),
            None,
        )

    def radio(self, video_id: str, limit: int = 50) -> list[LibraryItem]:
        """Build YouTube Music's automatic radio queue from a seed track."""
        if not video_id:
            return []
        payload = self._api_post(
            "next",
            {"videoId": video_id, "playlistId": f"RDAMVM{video_id}", "params": "wAEB"},
            authenticated=True,
        )
        items = parse_watch_queue(payload, audio_only=True)
        if not items:
            items = parse_watch_queue(payload, audio_only=False)
        return items[:limit]

    def library(
        self, category: str, all_pages: bool = True, max_pages: int = 10
    ) -> list[LibraryItem]:
        return self.library_listing(category, all_pages, max_pages)[0]

    def library_listing(
        self, category: str, all_pages: bool = True, max_pages: int = 10
    ) -> tuple[list[LibraryItem], bool]:
        """The category's items, and whether every page was read."""
        if category not in LIBRARIES:
            raise ValueError(_("Categoria desconhecida: {category}").format(category=category))
        payload = self._post({"browseId": LIBRARIES[category]})
        parse_kind = {
            "uploads": "songs",
            "uploaded-albums": "albums",
            "podcasts": "podcasts",
            "podcast-episodes": "auto",
        }.get(category, category)
        result = parse_library_items(payload, parse_kind)
        continuation = find_continuation(payload)
        pages = 1
        while all_pages and continuation and pages < max_pages:
            payload = self._post({"continuation": continuation})
            result.extend(parse_library_items(payload, parse_kind))
            continuation = find_continuation(payload)
            pages += 1
        unique = {item.id: item for item in result}
        return list(unique.values()), not continuation

    def browse(
        self, browse_id: str, kind: str = "songs", all_pages: bool = True, max_pages: int = 10
    ) -> list[LibraryItem]:
        """Load the tracks/items behind a library card."""
        if not browse_id:
            return []
        if kind == "playlists" and not browse_id.startswith("VL"):
            browse_id = f"VL{browse_id}"
        payload = self._post({"browseId": browse_id})
        result = parse_library_items(payload, "songs")
        continuation = find_continuation(payload)
        pages = 1
        while all_pages and continuation and pages < max_pages:
            payload = self._post({"continuation": continuation})
            result.extend(parse_library_items(payload, "songs"))
            continuation = find_continuation(payload)
            pages += 1
        unique = {item.id: item for item in result}
        return list(unique.values())
