from __future__ import annotations

import io

from harmonia.player_config import (
    PlayerConfigResolver,
    _CACHE,
    _extract_player_url,
    _extract_signature_timestamp,
)


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class DummyClient:
    cookie = "SAPISID=test"
    hl = "pt-BR"

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def _open(self, request, timeout=10):
        self.requests.append((request.full_url, request.headers, timeout))
        return Response(self.responses.pop(0).encode())


def test_extract_player_url_accepts_youtube_player_script():
    html = r'{"PLAYER_JS_URL":"\/s\/player\/abc123\/player_ias.vflset\/en_US\/base.js"}'
    html = html.replace(r'\"', '"')
    assert _extract_player_url(html) == (
        "https://www.youtube.com/s/player/abc123/player_ias.vflset/en_US/base.js"
    )


def test_extract_signature_timestamp_from_page_or_player_js():
    assert _extract_signature_timestamp('"STS": 20433') == 20433
    assert _extract_signature_timestamp("signatureTimestamp:20434") == 20434


def test_player_config_uses_watch_page_signature_timestamp():
    _CACHE.clear()
    page = (
        '"PLAYER_JS_URL":"/s/player/hash/player_ias.vflset/en_US/base.js" '
        '"STS": 20435 "VISITOR_DATA":"visitor" '
        '"INNERTUBE_CLIENT_VERSION":"1.live"'
    )
    client = DummyClient([page])
    config = PlayerConfigResolver(client).fetch("abc123")
    assert config.signature_timestamp == 20435
    assert config.visitor_data == "visitor"
    assert config.client_version == "1.live"
    assert len(client.requests) == 1


def test_player_config_falls_back_to_player_js_for_timestamp():
    _CACHE.clear()
    page = '"jsUrl":"/s/player/hash/player_ias.vflset/en_US/base.js"'
    client = DummyClient([page, "signatureTimestamp:20436"])
    config = PlayerConfigResolver(client).fetch("abc124")
    assert config.signature_timestamp == 20436
    assert len(client.requests) == 2
