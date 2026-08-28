from __future__ import annotations

import io
import json

from harmonia.player_director import PlayerClientDirector
from harmonia.potoken import PoTokenResult, install_potoken_provider
from harmonia.stream_extractor import ExtractionDiagnostics, PlayerClientProfile


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class DummyClient:
    authenticated = False
    cookie = ""
    hl = "pt-BR"
    gl = "BR"
    client_version = "1.live"
    visitor_data = "visitor-123"
    data_sync_id = None

    def __init__(self):
        self.requests = []

    def _bootstrap(self):
        return None

    def _open(self, request, timeout=30):
        self.requests.append((request, timeout))
        payload = {
            "playabilityStatus": {"status": "OK"},
            "streamingData": {"adaptiveFormats": []},
        }
        return Response(json.dumps(payload).encode())


class DummyConfigResolver:
    def fetch(self, *_args, **_kwargs):
        return None


class DummyPoTokenProvider:
    def __init__(self):
        self.timeouts = []

    def get_po_token(self, video_id, visitor_data, cookie=None, *, timeout=50.0):
        assert video_id == "video"
        assert visitor_data == "visitor-123"
        self.timeouts.append(timeout)
        return PoTokenResult("player-pot", "stream-pot", visitor_data)

    def close(self):
        return None


def teardown_function():
    install_potoken_provider(None)


def test_director_adds_player_and_streaming_potokens():
    provider = DummyPoTokenProvider()
    install_potoken_provider(provider)
    client = DummyClient()
    profile = PlayerClientProfile(
        id="67",
        name="WEB_REMIX",
        version="1.test",
        user_agent="test-agent",
        use_web_potoken=True,
    )
    diagnostics = ExtractionDiagnostics("video")
    director = PlayerClientDirector(client, DummyConfigResolver())

    results = list(director.payloads("video", [profile], diagnostics, want_video=True))

    assert len(results) == 1
    _profile, payload = results[0]
    assert payload["_harmoniaStreamingPoToken"] == "stream-pot"
    assert len(provider.timeouts) == 1
    assert 0 < provider.timeouts[0] <= 10
    request, request_timeout = client.requests[0]
    assert 0 < request_timeout <= 12
    body = json.loads(request.data)
    assert body["serviceIntegrityDimensions"]["poToken"] == "player-pot"
    assert body["context"]["client"]["visitorData"] == "visitor-123"
