from __future__ import annotations

import hashlib
import io
import json
import struct
import urllib.parse

from harmonia.models import LibraryItem
from harmonia.social import (
    DiscordPresence,
    LastFmClient,
    LastFmCredentials,
    LastFmCredentialStore,
    LastFmSession,
    media_artist,
    scrobble_ready,
)


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_lastfm_desktop_auth_and_signed_playback_calls():
    requests = []
    responses = iter(
        [
            {"token": "request-token"},
            {"session": {"name": "listener", "key": "session-key"}},
            {"nowplaying": {}},
            {"scrobbles": {"@attr": {"accepted": "1"}}},
        ]
    )

    def opener(request, timeout):
        assert timeout == 15
        parameters = dict(urllib.parse.parse_qsl(request.data.decode()))
        requests.append(parameters)
        return Response(json.dumps(next(responses)).encode())

    client = LastFmClient("api-key", "api-secret", opener=opener)
    token = client.request_token()
    assert token == "request-token"
    assert "api_key=api-key" in client.authorization_url(token)
    session = client.create_session(token)
    assert session == LastFmSession("listener", "session-key")

    authenticated = LastFmClient("api-key", "api-secret", session.key, opener=opener)
    item = LibraryItem("track", "911", "Música • Lady Gaga")
    authenticated.update_now_playing(item, 180_000)
    authenticated.scrobble(item, 1_700_000_000, 180_000)

    assert [request["method"] for request in requests] == [
        "auth.getToken",
        "auth.getSession",
        "track.updateNowPlaying",
        "track.scrobble",
    ]
    for parameters in requests:
        signature_parameters = {
            key: value for key, value in parameters.items() if key not in {"api_sig", "format"}
        }
        source = "".join(
            f"{key}{signature_parameters[key]}" for key in sorted(signature_parameters)
        )
        expected = hashlib.md5(f"{source}api-secret".encode(), usedforsecurity=False).hexdigest()
        assert parameters["api_sig"] == expected
    assert requests[2]["artist"] == "Lady Gaga"
    assert requests[3]["timestamp"] == "1700000000"


def test_lastfm_credentials_fallback_is_private(monkeypatch, tmp_path):
    monkeypatch.setenv("HARMONIA_DISABLE_SECRET_SERVICE", "1")

    class Storage:
        cookie_file = tmp_path / "config" / "session"

    Storage.cookie_file.parent.mkdir()
    store = LastFmCredentialStore(Storage())
    credentials = LastFmCredentials("secret", LastFmSession("listener", "session"))
    store.save(credentials)

    assert store.load() == credentials
    assert oct(store._fallback.stat().st_mode & 0o777) == "0o600"
    store.clear_session()
    assert store.load() == LastFmCredentials("secret")


def test_scrobble_threshold_and_media_artist():
    assert not scrobble_ready(30_000, 30_000)
    assert not scrobble_ready(180_000, 89_999)
    assert scrobble_ready(180_000, 90_000)
    assert not scrobble_ready(600_000, 239_999)
    assert scrobble_ready(600_000, 240_000)
    assert media_artist(LibraryItem("1", "Song", "Música • Artist")) == "Artist"
    assert media_artist(LibraryItem("2", "Song", "Artist • Album")) == "Artist"


class FakeDiscordSocket:
    def __init__(self, *_args):
        self.sent = []
        self.responses = bytearray()
        self.closed = False

    def settimeout(self, _timeout):
        pass

    def connect(self, _path):
        pass

    def sendall(self, data):
        self.sent.append(data)
        payload = {"evt": "READY"} if len(self.sent) == 1 else {"data": {}}
        body = json.dumps(payload).encode()
        self.responses.extend(struct.pack("<II", 1, len(body)) + body)

    def recv(self, length):
        chunk = bytes(self.responses[:length])
        del self.responses[:length]
        return chunk

    def close(self):
        self.closed = True


def test_discord_presence_uses_local_ipc(monkeypatch):
    created = []

    def factory(*args):
        created.append(FakeDiscordSocket(*args))
        return created[-1]

    monkeypatch.setattr(DiscordPresence, "candidate_paths", staticmethod(lambda: ["socket"]))
    presence = DiscordPresence("client-id", socket_factory=factory)
    presence.update(LibraryItem("1", "Song", "Artist"), True, 1_700_000_000)

    handshake = json.loads(created[0].sent[0][8:])
    activity = json.loads(created[0].sent[1][8:])
    assert handshake == {"v": 1, "client_id": "client-id"}
    assert activity["cmd"] == "SET_ACTIVITY"
    assert activity["args"]["activity"]["details"] == "Song"
    assert activity["args"]["activity"]["timestamps"]["start"] == 1_700_000_000

    presence.clear()
    clear = json.loads(created[0].sent[2][8:])
    assert clear["args"]["activity"] is None
