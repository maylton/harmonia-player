"""Small native port of Metrolist's authenticated InnerTube library client.

This module deliberately uses only Python's standard library. Authentication is
the same scheme used by the YouTube Music web client: the user's session cookie
plus a time-bound SAPISIDHASH. No password is ever requested or transmitted.
"""

from __future__ import annotations

import hashlib
import json
import locale
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from contextlib import suppress
from typing import Any

from .i18n import _
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
    StreamInfo,
)

ORIGIN = "https://music.youtube.com"
API_URL = f"{ORIGIN}/youtubei/v1"
CLIENT_NAME = "WEB_REMIX"
CLIENT_ID = "67"
CLIENT_VERSION = "1.20260114.03.00"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
PLAYER_CLIENTS = (
    {
        "name": "VISIONOS",
        "id": "101",
        "version": "0.1",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
        "context": {
            "osName": "visionOS",
            "osVersion": "1.3.21O771",
            "deviceMake": "Apple",
            "deviceModel": "RealityDevice14,1",
        },
    },
    {
        "name": "ANDROID_MUSIC",
        "id": "21",
        "version": "8.10.51",
        "user_agent": "com.google.android.apps.youtube.music/8.10.51 (Linux; U; Android 14) gzip",
        "context": {"androidSdkVersion": 34, "osName": "Android", "osVersion": "14"},
    },
    {
        "name": "IOS",
        "id": "5",
        "version": "21.03.1",
        "user_agent": "com.google.ios.youtube/21.03.1 (iPhone16,2; U; CPU iOS 18_2 like Mac OS X;)",
    },
    {
        "name": "ANDROID_VR",
        "id": "28",
        "version": "1.65.10",
        "user_agent": "com.google.android.apps.youtube.vr.oculus/1.65.10 (Linux; U; Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip",
    },
    {
        "name": "WEB_REMIX",
        "id": CLIENT_ID,
        "version": CLIENT_VERSION,
        "user_agent": USER_AGENT,
        "authenticated": True,
        "live_version": True,
    },
)

LIBRARIES = {
    "playlists": "FEmusic_liked_playlists",
    "songs": "FEmusic_liked_videos",
    "albums": "FEmusic_liked_albums",
    "artists": "FEmusic_library_corpus_artists",
    "uploads": "FEmusic_library_privately_owned_tracks",
    "uploaded-albums": "FEmusic_library_privately_owned_releases",
    "podcasts": "FEmusic_library_non_music_audio_channels_list",
    "podcast-episodes": "FEmusic_library_non_music_audio_list",
}

SEARCH_FILTER_SONGS = "EgWKAQIIAWoKEAkQBRAKEAMQBA%3D%3D"
SEARCH_FILTERS = {
    "songs": SEARCH_FILTER_SONGS,
    "videos": "EgWKAQIQAWoKEAkQChAFEAMQBA%3D%3D",
    "albums": "EgWKAQIYAWoKEAkQChAFEAMQBA%3D%3D",
    "artists": "EgWKAQIgAWoKEAkQChAFEAMQBA%3D%3D",
    "playlists": "EgeKAQQoAEABagoQAxAEEAoQCRAF",
}
SEARCH_TITLES = {
    "songs": _("Músicas"),
    "videos": _("Vídeos"),
    "albums": _("Álbuns"),
    "artists": _("Artistas"),
    "playlists": _("Playlists"),
}

_STREAM_CACHE: dict[str, StreamInfo] = {}
_STREAM_CACHE_LOCK = threading.Lock()


class InnerTubeError(RuntimeError):
    pass


def parse_cookie(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in raw.split(";"):
        if "=" in part:
            key, value = part.strip().split("=", 1)
            result[key] = value
    return result


def sapisid_hash(cookie: str, timestamp: int | None = None) -> str:
    cookies = parse_cookie(cookie)
    sapisid = cookies.get("SAPISID") or cookies.get("__Secure-3PAPISID")
    if not sapisid:
        raise InnerTubeError(
            _(
                "O cookie não contém SAPISID. Entre novamente no music.youtube.com "
                "e exporte o cookie completo."
            )
        )
    now = int(time.time()) if timestamp is None else timestamp
    digest = hashlib.sha1(f"{now} {sapisid} {ORIGIN}".encode()).hexdigest()
    return f"SAPISIDHASH {now}_{digest}"


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


def _kind_for_id(item_id: str, renderer: dict[str, Any], default: str) -> str:
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
            actual_kind = _kind_for_id(item_id, renderer, kind) if kind == "auto" else kind
            items.append(
                LibraryItem(
                    stable_id,
                    title,
                    subtitle,
                    _best_thumbnail(renderer),
                    actual_kind,
                    playlist_id,
                    _set_video_id(renderer),
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
            LibraryItem(str(video_id), title, subtitle, _best_thumbnail(renderer), "songs")
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


class InnerTubeClient:
    def __init__(
        self,
        cookie: str,
        hl: str | None = None,
        gl: str | None = None,
        max_bitrate: int | None = None,
        proxy: str = "",
    ):
        self.cookie = cookie.strip()
        language, _ = locale.getlocale()
        language = language if language and language not in ("C", "POSIX") else "pt_BR"
        self.hl = hl or language.replace("_", "-")
        self.gl = gl or (language.split("_")[-1] if "_" in language else "BR")
        self.client_version = CLIENT_VERSION
        self.visitor_data: str | None = None
        self.data_sync_id: str | None = None
        self.session_index: str | None = None
        self._bootstrapped = False
        self.max_bitrate = max_bitrate or 10_000_000
        self._proxy_opener = (
            urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy})
            )
            if proxy
            else None
        )

    def _open(self, request, timeout=30):
        """Keep the default opener late-bound so tests and embedders can inject it."""
        if self._proxy_opener:
            return self._proxy_opener.open(request, timeout=timeout)
        return urllib.request.urlopen(request, timeout=timeout)

    @property
    def authenticated(self) -> bool:
        try:
            sapisid_hash(self.cookie)
            return True
        except InnerTubeError:
            return False

    def validate_session(self) -> bool:
        if not self.authenticated:
            return False
        self._bootstrap()
        return True

    def account_profile(self) -> AccountProfile:
        return parse_account_profile(self._api_post("account/account_menu", {}))

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._api_post("browse", body, authenticated=True)

    def _api_post(
        self, endpoint: str, body: dict[str, Any], authenticated: bool = True
    ) -> dict[str, Any]:
        if authenticated:
            self._bootstrap()
        context = {
            "client": {
                "clientName": CLIENT_NAME,
                "clientVersion": self.client_version,
                "hl": self.hl,
                "gl": self.gl,
                **({"visitorData": self.visitor_data} if self.visitor_data else {}),
            },
            "user": {**({"onBehalfOfUser": self.data_sync_id} if self.data_sync_id else {})},
        }
        body = {"context": context, **body}
        query_separator = "&" if "?" in endpoint else "?"
        request = urllib.request.Request(
            f"{API_URL}/{endpoint}{query_separator}prettyPrint=false",
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
                "Origin": ORIGIN,
                "Referer": f"{ORIGIN}/",
                "X-Origin": ORIGIN,
                "X-Goog-Api-Format-Version": "1",
                "X-YouTube-Client-Name": CLIENT_ID,
                "X-YouTube-Client-Version": self.client_version,
                **({"X-Goog-Visitor-Id": self.visitor_data} if self.visitor_data else {}),
                **({"X-Goog-AuthUser": self.session_index} if self.session_index else {}),
                **(
                    {"Cookie": self.cookie, "Authorization": sapisid_hash(self.cookie)}
                    if authenticated
                    else {}
                ),
            },
        )
        for attempt in range(3):
            try:
                with self._open(request, timeout=30) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:300]
                if exc.code in (401, 403):
                    raise InnerTubeError(
                        _("A sessão expirou ou o cookie não tem acesso ao YouTube Music.")
                    ) from exc
                if exc.code not in (408, 429, 500, 502, 503, 504) or attempt == 2:
                    raise InnerTubeError(
                        _("YouTube Music respondeu HTTP {code}: {detail}").format(
                            code=exc.code, detail=detail
                        )
                    ) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == 2:
                    raise InnerTubeError(
                        _("Não foi possível conectar ao YouTube Music: {error}").format(error=exc)
                    ) from exc
            time.sleep(0.2 * (2**attempt))
        raise InnerTubeError(_("Não foi possível concluir a requisição ao YouTube Music."))

    def _bootstrap(self) -> None:
        """Read the live InnerTube configuration associated with this session."""
        if self._bootstrapped:
            return
        request = urllib.request.Request(
            f"{ORIGIN}/",
            headers={"Cookie": self.cookie, "User-Agent": USER_AGENT, "Accept-Language": self.hl},
        )
        try:
            with self._open(request, timeout=30) as response:
                html = response.read().decode(errors="replace")
        except (urllib.error.URLError, TimeoutError) as exc:
            raise InnerTubeError(
                _("Não foi possível iniciar a sessão do YouTube Music: {error}").format(error=exc)
            ) from exc

        def config(name: str) -> str | None:
            match = re.search(rf'"{name}"\s*:\s*(?:"([^"]*)"|([0-9]+))', html)
            return (match.group(1) or match.group(2)) if match else None

        self.client_version = config("INNERTUBE_CLIENT_VERSION") or CLIENT_VERSION
        self.visitor_data = config("VISITOR_DATA")
        data_sync = config("DATASYNC_ID")
        self.data_sync_id = data_sync.split("||", 1)[0] if data_sync else None
        self.session_index = config("SESSION_INDEX")
        self._bootstrapped = True

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
        return list(unique.values())

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

    @staticmethod
    def _stream_expiration(url: str) -> int | None:
        values = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("expire")
        try:
            return int(values[0]) if values else None
        except (TypeError, ValueError):
            return None

    def resolve_stream(self, video_id: str, force: bool = False) -> StreamInfo:
        """Resolve audio with cache, transient retries and ordered client fallback."""
        if not video_id:
            raise InnerTubeError(_("A faixa não contém um identificador reproduzível."))
        cache_key = f"{self.gl}:{self.max_bitrate}:{video_id}"
        if not force:
            with _STREAM_CACHE_LOCK:
                cached = _STREAM_CACHE.get(cache_key)
            if cached and cached.valid_at(int(time.time())):
                return cached
        else:
            with _STREAM_CACHE_LOCK:
                _STREAM_CACHE.pop(cache_key, None)

        failures: list[str] = []
        with suppress(InnerTubeError):
            self._bootstrap()
        for profile in PLAYER_CLIENTS:
            version = self.client_version if profile.get("live_version") else profile["version"]
            client = {
                "clientName": profile["name"],
                "clientVersion": version,
                "userAgent": profile["user_agent"],
                "hl": self.hl,
                "gl": self.gl,
                **profile.get("context", {}),
                **({"visitorData": self.visitor_data} if self.visitor_data else {}),
            }
            body = {
                "context": {"client": client, "user": {}},
                "videoId": video_id,
                "contentCheckOk": True,
                "racyCheckOk": True,
            }
            request = urllib.request.Request(
                f"{API_URL}/player?prettyPrint=false",
                data=json.dumps(body).encode(),
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": profile["user_agent"],
                    "X-YouTube-Client-Name": profile["id"],
                    "X-YouTube-Client-Version": version,
                    **({"X-Goog-Visitor-Id": self.visitor_data} if self.visitor_data else {}),
                    **(
                        {
                            "Cookie": self.cookie,
                            "Authorization": sapisid_hash(self.cookie),
                            "Origin": ORIGIN,
                            "X-Origin": ORIGIN,
                        }
                        if profile.get("authenticated") and self.authenticated
                        else {}
                    ),
                },
            )
            payload: dict[str, Any] | None = None
            for attempt in range(2):
                try:
                    with self._open(request, timeout=30) as response:
                        payload = json.load(response)
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code not in (408, 429, 500, 502, 503, 504) or attempt == 1:
                        failures.append(f"{profile['name']}: HTTP {exc.code}")
                        break
                except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                    if attempt == 1:
                        failures.append(f"{profile['name']}: {exc}")
                        break
                time.sleep(0.2 * (2**attempt))
            if payload is None:
                continue
            status = payload.get("playabilityStatus", {})
            formats = (payload.get("streamingData") or {}).get("adaptiveFormats") or []
            audio = [
                fmt
                for fmt in formats
                if str(fmt.get("mimeType", "")).startswith("audio/") and fmt.get("url")
            ]
            if status.get("status") == "OK" and audio:
                within_quality = [
                    fmt for fmt in audio if int(fmt.get("bitrate", 0) or 0) <= self.max_bitrate
                ]
                selected = max(
                    within_quality or audio, key=lambda fmt: int(fmt.get("bitrate", 0) or 0)
                )
                duration = selected.get("approxDurationMs")
                url = str(selected["url"])
                stream = StreamInfo(
                    url=url,
                    duration_ms=int(duration) if duration else None,
                    client=str(profile["name"]),
                    mime_type=str(selected.get("mimeType") or ""),
                    bitrate=int(selected.get("bitrate", 0) or 0),
                    itag=int(selected["itag"]) if selected.get("itag") is not None else None,
                    expires_at=self._stream_expiration(url),
                    playback_tracking_url=(
                        (
                            (payload.get("playbackTracking") or {}).get("videostatsPlaybackUrl")
                            or {}
                        ).get("baseUrl")
                    ),
                )
                with _STREAM_CACHE_LOCK:
                    _STREAM_CACHE[cache_key] = stream
                return stream
            failures.append(
                f"{profile['name']}: {status.get('reason') or status.get('status') or 'sem stream direto'}"
            )
        raise InnerTubeError(
            _("Não foi possível obter um stream reproduzível. {details}").format(
                details="; ".join(failures)
            )
        )

    def player(self, video_id: str, force: bool = False) -> tuple[str, int | None]:
        """Compatibility wrapper retained for the GTK playback controller."""
        stream = self.resolve_stream(video_id, force=force)
        return stream.url, stream.duration_ms

    def register_playback(self, tracking_url: str, playlist_id: str | None = None) -> None:
        """Register a qualified playback in the account's YouTube Music history."""
        if not tracking_url:
            return
        parsed = urllib.parse.urlsplit(tracking_url)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        query.extend(
            (
                ("c", CLIENT_NAME),
                ("cpn", secrets.token_urlsafe(12)[:16]),
                ("ver", "2"),
            )
        )
        if playlist_id:
            playlist_id = playlist_id.removeprefix("VL")
            query.extend(
                (
                    ("list", playlist_id),
                    ("referrer", f"{ORIGIN}/playlist?list={playlist_id}"),
                )
            )
        url = urllib.parse.urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                urllib.parse.urlencode(query),
                parsed.fragment,
            )
        )
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Cookie": self.cookie,
                **(
                    {"Authorization": sapisid_hash(self.cookie), "Origin": ORIGIN}
                    if self.authenticated
                    else {}
                ),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20):
                return
        except (urllib.error.URLError, TimeoutError) as exc:
            raise InnerTubeError(
                _("Não foi possível registrar a reprodução: {error}").format(error=exc)
            ) from exc

    def like_song(self, video_id: str, liked: bool = True) -> None:
        self._api_post(
            "like/like" if liked else "like/removelike", {"target": {"videoId": video_id}}
        )

    def like_playlist(self, playlist_id: str, liked: bool = True) -> None:
        self._api_post(
            "like/like" if liked else "like/removelike",
            {"target": {"playlistId": playlist_id.removeprefix("VL")}},
        )

    def subscribe_artist(self, channel_id: str, subscribed: bool = True) -> None:
        endpoint = "subscription/subscribe" if subscribed else "subscription/unsubscribe"
        self._api_post(endpoint, {"channelIds": [channel_id]})

    def create_playlist(
        self, title: str, privacy: str = "PRIVATE", video_ids: list[str] | None = None
    ) -> str:
        title = title.strip()
        if not title:
            raise ValueError(_("O nome da playlist não pode ficar vazio"))
        payload = self._api_post(
            "playlist/create",
            {"title": title, "privacyStatus": privacy, "videoIds": video_ids or None},
        )
        playlist_id = payload.get("playlistId")
        if not playlist_id:
            raise InnerTubeError(_("O YouTube criou a playlist sem retornar o identificador"))
        return str(playlist_id)

    def edit_playlist(self, playlist_id: str, actions: list[dict[str, Any]]) -> None:
        self._api_post(
            "browse/edit_playlist",
            {"playlistId": playlist_id.removeprefix("VL"), "actions": actions},
        )

    def rename_playlist(self, playlist_id: str, title: str) -> None:
        self.edit_playlist(
            playlist_id, [{"action": "ACTION_SET_PLAYLIST_NAME", "playlistName": title.strip()}]
        )

    def delete_playlist(self, playlist_id: str) -> None:
        self._api_post("playlist/delete", {"playlistId": playlist_id.removeprefix("VL")})

    def add_to_playlist(self, playlist_id: str, video_id: str) -> None:
        self.edit_playlist(playlist_id, [{"action": "ACTION_ADD_VIDEO", "addedVideoId": video_id}])

    def remove_from_playlist(self, playlist_id: str, video_id: str, set_video_id: str) -> None:
        if not set_video_id:
            raise ValueError(
                _("A faixa não contém playlistSetVideoId e não pode ser removida com segurança")
            )
        self.edit_playlist(
            playlist_id,
            [
                {
                    "action": "ACTION_REMOVE_VIDEO",
                    "removedVideoId": video_id,
                    "setVideoId": set_video_id,
                }
            ],
        )
