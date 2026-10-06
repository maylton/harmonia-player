"""What the embedded logins share, independent of the browser engine."""

from __future__ import annotations

from collections.abc import Iterable

from .innertube import parse_cookie

LOGIN_URL = "https://accounts.google.com/ServiceLogin?continue=https%3A%2F%2Fmusic.youtube.com"
MUSIC_ORIGIN = "https://music.youtube.com"


def session_cookie_header(cookies: Iterable[tuple[str, str]]) -> str | None:
    """Join a browser's music.youtube.com cookies into a Cookie header.

    None until the login finished: the header must carry a SAPISID cookie,
    which the session hash is computed from.
    """
    raw = "; ".join(f"{name}={value}" for name, value in cookies)
    parsed = parse_cookie(raw)
    if "SAPISID" not in parsed and "__Secure-3PAPISID" not in parsed:
        return None
    return raw
