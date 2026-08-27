"""Application services shared by GTK views.

The window owns presentation state; this module owns orchestration of network
and persistence operations. Keeping it free of GTK makes the important flows
cheap to test and reusable by future windows or background jobs.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from .innertube import InnerTubeClient
from .models import (
    AccountProfile,
    ArtistPage,
    ArtistSection,
    ExploreData,
    ExploreDestination,
    HistoryEntry,
    HomeSection,
    LibraryItem,
    SearchGroup,
    SearchResults,
    StreamInfo,
)
from .preferences import Preferences
from .storage import Storage
from .stream_extractor import InnerTubeStreamExtractor, StreamExtractionError
from .video import VideoStreamInfo, resolve_video_stream

SEARCH_ORDER = ("songs", "videos", "albums", "artists", "playlists")


class YouTubeMusicService:
    def __init__(
        self,
        storage: Storage,
        client_factory: Callable[[str], InnerTubeClient] = InnerTubeClient,
    ) -> None:
        self.storage = storage
        self.client_factory = client_factory

    def _make_client(self, cookie: str) -> InnerTubeClient:
        preferences = (
            Preferences.load(self.storage)
            if hasattr(self.storage, "get_setting")
            else Preferences()
        )
        try:
            return self.client_factory(
                cookie,
                hl=preferences.language,
                gl=preferences.region,
                max_bitrate=preferences.max_bitrate,
                proxy=preferences.proxy,
            )
        except TypeError:
            return self.client_factory(cookie)

    def client(self) -> InnerTubeClient:
        return self._make_client(self.storage.load_cookie())

    def connect(self, cookie: str) -> bool:
        client = self._make_client(cookie.strip())
        if not client.authenticated:
            return False
        self.storage.save_cookie(cookie.strip())
        return True

    def disconnect(self) -> None:
        self.storage.clear_cookie()

    def validate_account(self) -> bool:
        return self.client().validate_session()

    def account_profile(self) -> AccountProfile:
        return self.client().account_profile()

    def sync_library(self) -> dict[str, list[LibraryItem]]:
        categories = (
            "playlists",
            "songs",
            "albums",
            "artists",
            "uploads",
            "uploaded-albums",
            "podcasts",
            "podcast-episodes",
        )
        required = {"playlists", "songs", "albums", "artists"}
        cached = self.storage.load_library()
        sections: dict[str, list[LibraryItem]] = {}
        with ThreadPoolExecutor(
            max_workers=len(categories), thread_name_prefix="library-sync"
        ) as pool:
            pending = {
                pool.submit(self.client().library, category): category for category in categories
            }
            for future in as_completed(pending):
                category = pending[future]
                try:
                    sections[category] = future.result()
                except Exception:
                    if category in required:
                        raise
                    if category in cached:
                        sections[category] = cached[category]
        ordered = {category: sections[category] for category in categories if category in sections}
        self.storage.save_library(ordered)
        return ordered

    def sync_home(self) -> list[HomeSection]:
        sections = self.client().home()
        self.storage.save_home(sections)
        return sections

    def sync_explore(self) -> ExploreData:
        data = self.client().explore()
        self.storage.save_explore(data)
        return data

    def discovery(self, destination: ExploreDestination) -> ExploreData:
        return self.client().discovery(destination)

    def browse(self, item: LibraryItem) -> list[LibraryItem]:
        is_dynamic_mix = item.kind == "playlists" and item.id.startswith("VLRD")
        return self.client().browse(item.id, item.kind, all_pages=not is_dynamic_mix)

    def artist(self, artist_id: str) -> ArtistPage:
        return self.client().artist(artist_id)

    def artist_section(self, section: ArtistSection) -> list[LibraryItem]:
        return self.client().artist_section(section)

    def mutate(self, operation):
        return operation(self.client())

    def radio(self, video_id: str) -> list[LibraryItem]:
        return self.client().radio(video_id)

    def lyrics(self, video_id: str) -> str | None:
        return self.client().lyrics(video_id)

    def history(self) -> list[HistoryEntry]:
        return self.client().history()

    def remove_history_item(self, feedback_token: str) -> None:
        self.client().remove_history_item(feedback_token)

    def universal_search(self, query: str) -> SearchResults:
        query = query.strip()
        if not query:
            return SearchResults("", [])
        groups: dict[str, SearchGroup] = {}
        errors: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=len(SEARCH_ORDER), thread_name_prefix="search") as pool:
            pending = {
                pool.submit(self.client().search_category, query, category): category
                for category in SEARCH_ORDER
            }
            for future in as_completed(pending):
                category = pending[future]
                try:
                    groups[category] = future.result()
                except Exception as exc:
                    errors[category] = str(exc)
        return SearchResults(
            query,
            [groups[key] for key in SEARCH_ORDER if key in groups and groups[key].items],
            errors or None,
        )

    def search_more(self, query: str, group: SearchGroup) -> SearchGroup:
        if not group.continuation:
            return SearchGroup(group.key, group.title, list(group.items), None)
        return self.client().search_category(query, group.key, group.continuation)

    def suggestions(self, query: str) -> list[str]:
        return self.client().search_suggestions(query)

    def resolve_stream(self, video_id: str, force: bool = False) -> StreamInfo:
        """Resolve audio through the shared extractor, retaining legacy fallback during migration."""
        client = self.client()
        if not (hasattr(client, "_open") and hasattr(client, "_bootstrap")):
            return client.resolve_stream(video_id, force=force)

        try:
            candidate = InnerTubeStreamExtractor(client).extract_audio(
                video_id,
                max_bitrate=getattr(client, "max_bitrate", 10_000_000),
            )
        except (StreamExtractionError, AttributeError, TypeError):
            # Until cipher/PoToken support is fully ported, the mature legacy
            # resolver remains a safety net for profiles whose direct URL cannot
            # yet be reconstructed by the new extraction layer.
            return client.resolve_stream(video_id, force=force)

        return StreamInfo(
            url=candidate.url,
            duration_ms=candidate.duration_ms,
            client=candidate.client,
            mime_type=candidate.mime_type,
            bitrate=candidate.bitrate,
            itag=candidate.itag,
            expires_at=candidate.expires_at,
            playback_tracking_url=candidate.playback_tracking_url,
        )

    def resolve_video(
        self,
        item: LibraryItem,
        *,
        max_height: int = 720,
        force: bool = False,
        allow_video_only: bool = False,
    ) -> VideoStreamInfo:
        """Resolve the best matching music-video stream."""
        return resolve_video_stream(
            self.client(),
            item,
            max_height=max_height,
            force=force,
            allow_video_only=allow_video_only,
        )

    def register_playback(self, tracking_url: str, playlist_id: str | None = None) -> None:
        self.client().register_playback(tracking_url, playlist_id)
