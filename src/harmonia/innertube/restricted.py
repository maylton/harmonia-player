"""The original streams of age-restricted tracks.

The clients Harmonia normally asks (player_clients.py) refuse a track YouTube
age-restricts, even signed in. An older version of the TV client accepts the
signed-in session, needs no PO token and returns every format, but with
encrypted URLs: they are decrypted with the player's own code
(challenges.py), as yt-dlp and Metrolist do.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .challenges import CHALLENGES, WWW
from .protocol import InnerTubeError, sapisid_hash

TV_CLIENT = {
    "name": "TVHTML5",
    "id": "7",
    "version": "5.20260707",
    "user_agent": "Mozilla/5.0 (ChromiumStylePlatform) Cobalt/Version",
}


def _with_query(url: str, **values: str) -> str:
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query = [(key, values.pop(key) if key in values else value) for key, value in query]
    query.extend(values.items())
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def decrypt_formats(formats: list[dict[str, Any]], challenges=None, player=None) -> None:
    """Give each format a playable "url", in place; drop those that cannot have one."""
    challenges = challenges or CHALLENGES
    pending: list[tuple[dict[str, Any], str, str | None, str | None, str]] = []
    for fmt in formats:
        cipher = urllib.parse.parse_qs(fmt.get("signatureCipher") or "")
        url = fmt.get("url") or (cipher.get("url") or [None])[0]
        if not url:
            continue
        n = (urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("n") or [None])[0]
        s = (cipher.get("s") or [None])[0]
        pending.append((fmt, url, n, s, (cipher.get("sp") or ["signature"])[0]))
    n_values = [n for _fmt, _url, n, _s, _sp in pending if n]
    sig_values = [s for _fmt, _url, _n, s, _sp in pending if s]
    player = player or challenges.player()
    n_answers, sig_answers = challenges.solve(player, n_values, sig_values)
    for fmt, url, n, s, sp in pending:
        if (n and n not in n_answers) or (s and s not in sig_answers):
            fmt.pop("url", None)
            continue
        values = {}
        if n:
            values["n"] = n_answers[n]
        if s:
            values[sp] = sig_answers[s]
        fmt["url"] = _with_query(url, **values)
        fmt.pop("signatureCipher", None)


class RestrictedStreamsMixin:
    """Needs InnerTubeSession's _open, cookie and session attributes."""

    def restricted_player_response(self, video_id: str) -> dict[str, Any]:
        """/player as the TV client, signed in, with every format's URL decrypted.

        Raises InnerTubeError (NoJsRuntimeError without a JavaScript engine).
        """
        if not self.authenticated:
            raise InnerTubeError("restricted: not signed in")
        self._bootstrap()
        player = CHALLENGES.player()
        client = {
            "clientName": TV_CLIENT["name"],
            "clientVersion": TV_CLIENT["version"],
            "userAgent": TV_CLIENT["user_agent"],
            "hl": self.hl,
            "gl": self.gl,
            **({"visitorData": self.visitor_data} if self.visitor_data else {}),
        }
        body = {
            "context": {"client": client, "user": {}},
            "videoId": video_id,
            "playbackContext": {
                "contentPlaybackContext": {
                    "html5Preference": "HTML5_PREF_WANTS",
                    "signatureTimestamp": player.sts,
                }
            },
            "contentCheckOk": True,
            "racyCheckOk": True,
        }
        request = urllib.request.Request(
            f"{WWW}/youtubei/v1/player?prettyPrint=false",
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": TV_CLIENT["user_agent"],
                "X-YouTube-Client-Name": TV_CLIENT["id"],
                "X-YouTube-Client-Version": TV_CLIENT["version"],
                "Origin": WWW,
                "X-Origin": WWW,
                "Cookie": self.cookie,
                "Authorization": sapisid_hash(self.cookie, origin=WWW),
                **({"X-Goog-AuthUser": self.session_index} if self.session_index else {}),
                **({"X-Goog-Visitor-Id": self.visitor_data} if self.visitor_data else {}),
            },
        )
        try:
            with self._open(request, timeout=30) as response:
                payload = json.load(response)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise InnerTubeError(f"{TV_CLIENT['name']}: {exc}") from exc
        status = payload.get("playabilityStatus") or {}
        if status.get("status") != "OK":
            raise InnerTubeError(
                f"{TV_CLIENT['name']}: {status.get('reason') or status.get('status')}"
            )
        streaming = payload.get("streamingData") or {}
        # One run of the solver for every format.
        formats = [*(streaming.get("adaptiveFormats") or []), *(streaming.get("formats") or [])]
        if formats:
            decrypt_formats(formats, player=player)
        return payload
