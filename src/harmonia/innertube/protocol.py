"""InnerTube protocol facts: endpoints, client profiles and authentication.

Authentication is the scheme of the YouTube Music web client: the user's
session cookie plus a time-bound SAPISIDHASH. No password is ever requested
or transmitted.
"""

from __future__ import annotations

import hashlib
import time
import urllib.error
import urllib.parse
import urllib.request

from ..i18n import _

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


class InnerTubeError(RuntimeError):
    pass


def parse_cookie(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in raw.split(";"):
        if "=" in part:
            key, value = part.strip().split("=", 1)
            result[key] = value
    return result


def sapisid_hash(cookie: str, timestamp: int | None = None, origin: str = ORIGIN) -> str:
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
    digest = hashlib.sha1(f"{now} {sapisid} {origin}".encode()).hexdigest()
    return f"SAPISIDHASH {now}_{digest}"


def stream_expiration(url: str) -> int | None:
    """The Unix time a googlevideo stream URL stops working, from its expire= field."""
    values = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("expire")
    try:
        return int(values[0]) if values else None
    except (TypeError, ValueError):
        return None
