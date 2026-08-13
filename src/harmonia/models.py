from dataclasses import dataclass, field


@dataclass(slots=True)
class LibraryItem:
    id: str
    title: str
    subtitle: str = ""
    thumbnail: str | None = None
    kind: str = "item"
    playlist_id: str | None = None
    set_video_id: str | None = None


@dataclass(frozen=True, slots=True)
class AccountProfile:
    name: str
    thumbnail: str | None = None
    email: str = ""
    channel_handle: str = ""


@dataclass(frozen=True, slots=True)
class LyricLine:
    start_ms: int
    text: str
    translation: str = ""


@dataclass(slots=True)
class LyricsDocument:
    plain: str
    provider: str
    synced: list[LyricLine] = field(default_factory=list)
    translation: str = ""
    translation_language: str = ""

    @property
    def is_synced(self) -> bool:
        return bool(self.synced)

    @property
    def display_text(self) -> str:
        return self.plain or "\n".join(line.text for line in self.synced)


@dataclass(slots=True)
class HomeSection:
    title: str
    items: list[LibraryItem]


@dataclass(slots=True)
class ExploreDestination:
    title: str
    browse_id: str
    params: str | None = None


@dataclass(slots=True)
class ExploreData:
    sections: list[HomeSection]
    shortcuts: list[ExploreDestination]
    genres: list[ExploreDestination]


@dataclass(slots=True)
class SearchGroup:
    """One typed and independently pageable section of universal search."""

    key: str
    title: str
    items: list[LibraryItem]
    continuation: str | None = None


@dataclass(slots=True)
class SearchResults:
    query: str
    groups: list[SearchGroup]
    errors: dict[str, str] | None = None

    def group(self, key: str) -> SearchGroup | None:
        return next((group for group in self.groups if group.key == key), None)


@dataclass(frozen=True, slots=True)
class StreamInfo:
    """A resolved media stream plus the information needed to refresh it."""

    url: str
    duration_ms: int | None
    client: str
    mime_type: str = ""
    bitrate: int = 0
    itag: int | None = None
    expires_at: int | None = None
    playback_tracking_url: str | None = None

    def valid_at(self, timestamp: int, margin: int = 90) -> bool:
        return self.expires_at is None or timestamp + margin < self.expires_at


@dataclass(slots=True)
class ArtistSection:
    title: str
    items: list[LibraryItem]
    browse_id: str | None = None
    params: str | None = None


@dataclass(slots=True)
class ArtistPage:
    id: str
    title: str
    description: str = ""
    thumbnail: str | None = None
    subscribers: str = ""
    subscribed: bool = False
    sections: list[ArtistSection] | None = None

    @property
    def songs(self) -> list[LibraryItem]:
        for section in self.sections or []:
            if section.items and all(item.kind == "songs" for item in section.items):
                return section.items
        return []


@dataclass(slots=True)
class PlaybackState:
    queue: list[LibraryItem]
    related: list[LibraryItem]
    index: int = 0
    position_ms: int = 0
    shuffle: bool = False
    repeat: bool = False
    autoplay: bool = True


@dataclass(slots=True)
class HistoryEntry:
    id: int | None
    item: LibraryItem
    played_at: int | None = None
    position_ms: int = 0
    source: str = "local"
    group: str = "Neste dispositivo"
    feedback_token: str | None = None


@dataclass(slots=True)
class DownloadRecord:
    item: LibraryItem
    status: str = "queued"
    file_path: str = ""
    downloaded_bytes: int = 0
    total_bytes: int = 0
    account_hash: str = ""
    error: str = ""
    updated_at: int = 0

    @property
    def progress(self) -> float:
        return self.downloaded_bytes / self.total_bytes if self.total_bytes else 0.0


@dataclass(slots=True)
class LocalPlaylist:
    id: int | None
    title: str
    items: list[LibraryItem]
    created_at: int = 0
    updated_at: int = 0
