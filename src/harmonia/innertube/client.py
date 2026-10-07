"""Small native port of Metrolist's authenticated InnerTube library client.

It deliberately uses only Python's standard library.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import suppress
from typing import Any

from .. import host
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
    StreamInfo,
)
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
    API_URL,
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_VERSION,
    LIBRARIES,
    ORIGIN,
    PLAYER_CLIENTS,
    SEARCH_FILTER_SONGS,
    SEARCH_FILTERS,
    SEARCH_TITLES,
    USER_AGENT,
    InnerTubeError,
    sapisid_hash,
    stream_expiration,
)

_STREAM_CACHE: dict[str, StreamInfo] = {}
_STREAM_CACHE_LOCK = threading.Lock()


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
        language = host.user_locale()
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

    def video_counterpart(self, video_id: str) -> str | None:
        """Return the official music-video counterpart linked to an audio track."""
        if not video_id:
            return None
        payload = self._api_post("next", {"videoId": video_id}, authenticated=True)
        return find_video_counterpart(payload)

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

    def player_response(self, video_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        """POST /player as one of PLAYER_CLIENTS, retrying transient failures once.

        Raises InnerTubeError with a short reason when no response is obtained.
        """
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
        for attempt in range(2):
            try:
                with self._open(request, timeout=30) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code not in (408, 429, 500, 502, 503, 504) or attempt == 1:
                    raise InnerTubeError(f"HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                if attempt == 1:
                    raise InnerTubeError(str(exc)) from exc
            time.sleep(0.2 * (2**attempt))
        raise AssertionError("unreachable")

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
            try:
                payload = self.player_response(video_id, profile)
            except InnerTubeError as exc:
                failures.append(f"{profile['name']}: {exc}")
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
                    expires_at=stream_expiration(url),
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
