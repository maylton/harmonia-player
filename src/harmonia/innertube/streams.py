"""Audio streams: asking the player clients in order, the stream cache and
registering a play in the account's history.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import suppress
from typing import Any

from ..i18n import _
from ..loudness import loudness_from_player
from ..models import (
    StreamInfo,
)
from .challenges import NoJsRuntimeError
from .player_clients import CATALOG
from .protocol import (
    API_URL,
    CLIENT_NAME,
    ORIGIN,
    USER_AGENT,
    InnerTubeError,
    sapisid_hash,
    stream_expiration,
)
from .restricted import TV_CLIENT

_STREAM_CACHE: dict[str, StreamInfo] = {}
_STREAM_CACHE_LOCK = threading.Lock()


class AgeRestrictedError(InnerTubeError):
    """YouTube age-restricts the track and its original stream could not be
    opened (no session, no JavaScript engine, or the TV client failed).
    Retrying cannot help.
    """


def is_age_gated(status: dict[str, Any]) -> bool:
    return "desktopLegacyAgeGateReason" in status or status.get("status") == "AGE_CHECK_REQUIRED"


class StreamsMixin:
    """Needs InnerTubeSession's _api_post, _bootstrap and session attributes."""

    def player_response(self, video_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        """POST /player as one client profile (player_clients.py), retrying transient failures once.

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

    def _audio_stream(self, payload: dict[str, Any], client_name: str) -> StreamInfo | None:
        """The best direct audio format of a playable /player response, if any."""
        if (payload.get("playabilityStatus") or {}).get("status") != "OK":
            return None
        formats = (payload.get("streamingData") or {}).get("adaptiveFormats") or []
        audio = [
            fmt
            for fmt in formats
            if str(fmt.get("mimeType", "")).startswith("audio/") and fmt.get("url")
        ]
        if not audio:
            return None
        within_quality = [
            fmt for fmt in audio if int(fmt.get("bitrate", 0) or 0) <= self.max_bitrate
        ]
        selected = max(within_quality or audio, key=lambda fmt: int(fmt.get("bitrate", 0) or 0))
        duration = selected.get("approxDurationMs")
        url = str(selected["url"])
        tracking = (payload.get("playbackTracking") or {}).get("videostatsPlaybackUrl") or {}
        return StreamInfo(
            url=url,
            duration_ms=int(duration) if duration else None,
            client=client_name,
            mime_type=str(selected.get("mimeType") or ""),
            bitrate=int(selected.get("bitrate", 0) or 0),
            itag=int(selected["itag"]) if selected.get("itag") is not None else None,
            expires_at=stream_expiration(url),
            playback_tracking_url=tracking.get("baseUrl"),
            loudness_db=loudness_from_player(payload, selected),
        )

    def _restricted_stream(self, video_id: str) -> StreamInfo:
        """The original stream of an age-restricted track (restricted.py)."""
        if not self.authenticated:
            raise AgeRestrictedError(
                _(
                    "Esta faixa tem restrição de idade: entre na sua conta do YouTube Music para ouvi-la."
                )
            )
        try:
            payload = self.restricted_player_response(video_id)
        except NoJsRuntimeError as exc:
            raise AgeRestrictedError(
                _(
                    "Esta faixa tem restrição de idade e falta um interpretador JavaScript "
                    "para abri-la. Instale o QuickJS ou o Node.js."
                )
            ) from exc
        except InnerTubeError as exc:
            raise AgeRestrictedError(
                _(
                    "Esta faixa tem restrição de idade e o stream original não abriu: {error}"
                ).format(error=exc)
            ) from exc
        stream = self._audio_stream(payload, TV_CLIENT["name"])
        if stream is None:
            raise AgeRestrictedError(
                _(
                    "Esta faixa tem restrição de idade e o stream original não abriu: {error}"
                ).format(error=_("sem formato de áudio"))
            )
        return stream

    def resolve_stream(self, video_id: str, force: bool = False) -> StreamInfo:
        """Resolve audio with cache, transient retries and ordered client fallback.

        An age-restricted track gets its original stream from the TV client
        (restricted.py), or raises AgeRestrictedError saying why it could not.
        """
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
        for profile in CATALOG.profiles():
            try:
                payload = self.player_response(video_id, profile)
            except InnerTubeError as exc:
                failures.append(f"{profile['name']}: {exc}")
                CATALOG.record(profile["name"], ok=False)
                continue
            status = payload.get("playabilityStatus", {})
            stream = self._audio_stream(payload, str(profile["name"]))
            if stream is None and is_age_gated(status):
                # The other clients refuse it the same way: go to the one that plays it.
                stream = self._restricted_stream(video_id)
            if stream is not None:
                with _STREAM_CACHE_LOCK:
                    _STREAM_CACHE[cache_key] = stream
                CATALOG.record(profile["name"], ok=stream.client == profile["name"])
                return stream
            failures.append(
                f"{profile['name']}: {status.get('reason') or status.get('status') or 'sem stream direto'}"
            )
            # A track the client cannot play (age, region) says little of its health.
            if status.get("status") == "OK":
                CATALOG.record(profile["name"], ok=False)
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
