from __future__ import annotations

import urllib.parse

from harmonia.stream_extractor import InnerTubeStreamExtractor, PlayerClientProfile
from harmonia.stream_transport import (
    clear_stream_transport,
    mark_stream_transport_failure,
    stream_transport_headers,
)


class DummyClient:
    authenticated = False
    cookie = ""
    hl = "pt-BR"
    gl = "BR"
    client_version = "1.test"
    visitor_data = None
    data_sync_id = None


PROFILE = PlayerClientProfile(
    id="1",
    name="TEST",
    version="1.0",
    user_agent="harmonia-test-agent",
)


def setup_function():
    clear_stream_transport()


def test_force_retry_skips_representation_that_failed_in_player():
    high = "https://media.test/audio-high"
    low = "https://media.test/audio-low"
    payload = {
        "playabilityStatus": {"status": "OK"},
        "streamingData": {
            "adaptiveFormats": [
                {
                    "url": high,
                    "mimeType": 'audio/webm; codecs="opus"',
                    "bitrate": 192_000,
                    "itag": 251,
                },
                {
                    "url": low,
                    "mimeType": 'audio/mp4; codecs="mp4a.40.2"',
                    "bitrate": 128_000,
                    "itag": 140,
                },
            ]
        },
    }
    extractor = InnerTubeStreamExtractor(DummyClient())
    extractor._payloads = lambda *_args, **_kwargs: iter([(PROFILE, payload)])

    first = extractor.extract_audio("retry-audio-unique", force=True)
    assert urllib.parse.urlsplit(first.url).path == "/audio-high"

    mark_stream_transport_failure(first.url, ttl=60)
    second = extractor.extract_audio("retry-audio-unique", force=True)

    assert urllib.parse.urlsplit(second.url).path == "/audio-low"
    assert ("User-Agent", "harmonia-test-agent") in stream_transport_headers(second.url)
