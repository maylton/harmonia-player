from __future__ import annotations

from collections.abc import Iterable

LOGIN_URL = "https://accounts.google.com/ServiceLogin?continue=https%3A%2F%2Fmusic.youtube.com"
YOUTUBE_MUSIC_ORIGIN = "https://music.youtube.com"
SESSION_COOKIE_NAMES = frozenset({"SAPISID", "__Secure-3PAPISID"})


def is_youtube_music_url(url: str) -> bool:
    """Return whether *url* points at the YouTube Music HTTPS origin."""
    return (url or "").strip().lower().startswith(YOUTUBE_MUSIC_ORIGIN)


def has_session_cookie(cookie_names: Iterable[str]) -> bool:
    """Return whether the cookie set can authenticate YouTube Music requests."""
    return bool(SESSION_COOKIE_NAMES.intersection(cookie_names))
