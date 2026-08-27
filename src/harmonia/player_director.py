from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Iterable, Iterator
from typing import Any

from .client_health import CLIENT_HEALTH
from .player_config import PlayerConfig, PlayerConfigResolver
from .potoken import current_potoken_provider

LOGGER = logging.getLogger(__name__)
ORIGIN_MUSIC = "https://music.youtube.com"
ORIGIN_WWW = "https://www.youtube.com"
ORIGIN_STUDIO = "https://studio.youtube.com"
_TRANSIENT_HTTP = {408, 425, 429, 500, 502, 503, 504}


class PlayerClientDirector:
    """Select and execute playback-client requests with PoToken fallback.

    The director mirrors InnerTubeX's transport split: Music clients use the
    music.youtube.com player endpoint, ordinary TV/web identities use
    www.youtube.com, and WEB_CREATOR uses studio.youtube.com. Successful
    responses receive private PoToken metadata consumed by the extractor.
    """

    def __init__(self, client, config_resolver: PlayerConfigResolver) -> None:
        self.client = client
        self.config_resolver = config_resolver
        self._configs: dict[bool, PlayerConfig] = {}

    def _authenticated(self) -> bool:
        try:
            return bool(self.client.authenticated)
        except Exception:
            return False

    def _config(self, video_id: str, *, authenticated: bool) -> PlayerConfig | None:
        cached = self._configs.get(authenticated)
        if cached is not None:
            return cached
        try:
            config = self.config_resolver.fetch(
                video_id,
                use_login_cookies=authenticated,
            )
        except Exception as exc:
            LOGGER.debug("YouTube player config unavailable: %s", exc)
            return None
        self._configs[authenticated] = config
        return config

    def invalidate_player_config(self) -> None:
        self._configs.clear()

    def _ensure_session(self) -> None:
        try:
            self.client._bootstrap()
        except Exception as exc:
            LOGGER.debug("InnerTube bootstrap failed before player extraction: %s", exc)

    @staticmethod
    def _profile_base_name(profile) -> str:
        name = str(profile.name)
        for suffix in ("_0_1", "_1_65_10", "_1_61_48", "_1_43_32"):
            if name.endswith(suffix):
                return name[: -len(suffix)]
        return name

    @classmethod
    def _request_origin(cls, profile) -> tuple[str, str]:
        base_name = cls._profile_base_name(profile)
        if profile.use_music_player_endpoint or base_name == "WEB_REMIX":
            return ORIGIN_MUSIC, f"{ORIGIN_MUSIC}/"
        if base_name == "WEB_CREATOR":
            return ORIGIN_STUDIO, f"{ORIGIN_STUDIO}/"
        if profile.is_embedded:
            return ORIGIN_WWW, "https://www.reddit.com/"
        return ORIGIN_WWW, f"{ORIGIN_WWW}/"

    @staticmethod
    def _sapisid_hash(cookie: str, origin: str) -> str | None:
        cookies: dict[str, str] = {}
        for part in (cookie or "").split(";"):
            if "=" not in part:
                continue
            key, value = part.strip().split("=", 1)
            cookies[key] = value
        sapisid = (
            cookies.get("SAPISID")
            or cookies.get("__Secure-3PAPISID")
            or cookies.get("__Secure-1PAPISID")
        )
        if not sapisid:
            return None
        now = int(time.time())
        digest = hashlib.sha1(f"{now} {sapisid} {origin}".encode()).hexdigest()
        return f"SAPISIDHASH {now}_{digest}"

    def _request(
        self,
        video_id: str,
        profile,
        diagnostics,
        *,
        want_video: bool,
    ) -> dict[str, Any] | None:
        profile_id = str(profile.name)
        authenticated = bool(profile.login_supported and self._authenticated())
        if profile.login_required and not authenticated:
            diagnostics.attempts.append(f"{profile.name}: login necessário")
            return None

        config = (
            self._config(video_id, authenticated=authenticated)
            if profile.use_signature_timestamp or profile.use_live_version
            else None
        )
        version = (
            config.client_version
            if profile.use_live_version and config and config.client_version
            else profile.version
        )
        visitor_data = getattr(self.client, "visitor_data", None) or (
            config.visitor_data if config else None
        )

        token = None
        provider = current_potoken_provider()
        should_mint = bool(
            profile.use_web_potoken
            and visitor_data
            and provider is not None
            and (want_video or profile.require_potoken or authenticated)
        )
        if should_mint:
            try:
                token = provider.get_po_token(
                    video_id,
                    str(visitor_data),
                    getattr(self.client, "cookie", "") if authenticated else None,
                    timeout=50.0,
                )
            except Exception as exc:
                LOGGER.warning("PoToken provider failed for %s: %s", profile.name, exc)
        if profile.require_potoken and token is None:
            diagnostics.attempts.append(f"{profile.name}: PoToken obrigatório indisponível")
            CLIENT_HEALTH.failure(profile_id, transient=True)
            return None

        client_context: dict[str, Any] = {
            "clientName": self._profile_base_name(profile),
            "clientVersion": version,
            "hl": getattr(self.client, "hl", "pt-BR"),
            "gl": getattr(self.client, "gl", "BR"),
            **profile.context_values(),
        }
        if profile.include_user_agent_in_context:
            client_context["userAgent"] = profile.user_agent
        if visitor_data:
            client_context["visitorData"] = visitor_data

        user_context: dict[str, Any] = {}
        data_sync_id = getattr(self.client, "data_sync_id", None)
        if authenticated and data_sync_id:
            user_context["onBehalfOfUser"] = data_sync_id

        request_context: dict[str, Any] = {
            "client": client_context,
            "user": user_context,
        }
        if profile.is_embedded:
            request_context["thirdParty"] = {"embedUrl": "https://www.reddit.com/"}

        body: dict[str, Any] = {
            "context": request_context,
            "videoId": video_id,
            "contentCheckOk": True,
            "racyCheckOk": True,
        }
        if config and config.signature_timestamp is not None:
            body["playbackContext"] = {
                "contentPlaybackContext": {"signatureTimestamp": config.signature_timestamp}
            }
        if token is not None and token.player_request_token:
            body["serviceIntegrityDimensions"] = {"poToken": token.player_request_token}

        origin, referer = self._request_origin(profile)
        request = urllib.request.Request(
            f"{origin}/youtubei/v1/player?prettyPrint=false",
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Accept-Language": getattr(self.client, "hl", "pt-BR"),
                "User-Agent": profile.user_agent,
                "Origin": origin,
                "X-Origin": origin,
                "Referer": referer,
                "X-Goog-Api-Format-Version": "1",
                "X-YouTube-Client-Name": profile.id,
                "X-YouTube-Client-Version": version,
                **({"X-Goog-Visitor-Id": visitor_data} if visitor_data else {}),
            },
        )
        if authenticated:
            cookie = getattr(self.client, "cookie", "")
            request.add_header("Cookie", cookie)
            auth = self._sapisid_hash(cookie, origin)
            if auth:
                request.add_header("Authorization", auth)
            session_index = getattr(self.client, "session_index", None)
            if session_index:
                request.add_header("X-Goog-AuthUser", str(session_index))

        for attempt in range(2):
            try:
                with self.client._open(request, timeout=30) as response:
                    payload = json.load(response)
                status = payload.get("playabilityStatus") or {}
                playable = status.get("status") == "OK" or bool(profile.skip_response_validation)
                if playable:
                    payload["_harmoniaStreamingPoToken"] = (
                        token.streaming_data_token if token is not None else ""
                    )
                    payload["_harmoniaUsedPoToken"] = token is not None
                    payload["_harmoniaRequestOrigin"] = origin
                    payload["_harmoniaRequestReferer"] = referer
                    CLIENT_HEALTH.success(profile_id)
                    return payload
                diagnostics.attempts.append(
                    f"{profile.name}: "
                    f"{status.get('reason') or status.get('status') or 'não reproduzível'}"
                )
                CLIENT_HEALTH.failure(
                    profile_id,
                    severe=status.get("status") == "UNPLAYABLE",
                )
                return payload
            except urllib.error.HTTPError as exc:
                if exc.code not in _TRANSIENT_HTTP or attempt == 1:
                    diagnostics.attempts.append(f"{profile.name}: HTTP {exc.code}")
                    CLIENT_HEALTH.failure(
                        profile_id,
                        transient=exc.code in _TRANSIENT_HTTP,
                    )
                    return None
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                if attempt == 1:
                    diagnostics.attempts.append(f"{profile.name}: {exc}")
                    CLIENT_HEALTH.failure(profile_id, transient=True)
                    return None
            time.sleep(0.2 * (2**attempt))
        return None

    def payloads(
        self,
        video_id: str,
        profiles: Iterable,
        diagnostics,
        *,
        want_video: bool = False,
    ) -> Iterator[tuple[Any, dict[str, Any]]]:
        self._ensure_session()
        indexed = list(enumerate(profiles))
        ordered = sorted(
            indexed,
            key=lambda pair: CLIENT_HEALTH.order_key(str(pair[1].name), -pair[0]),
        )
        healthy = [pair for pair in ordered if CLIENT_HEALTH.available(str(pair[1].name))]
        selected = healthy or ordered
        for _index, profile in selected:
            payload = self._request(
                video_id,
                profile,
                diagnostics,
                want_video=want_video,
            )
            if not payload:
                continue
            status = payload.get("playabilityStatus") or {}
            if status.get("status") == "OK" or profile.skip_response_validation:
                yield profile, payload
