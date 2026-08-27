from __future__ import annotations

import pytest

from harmonia.innertube import InnerTubeError
from harmonia.models import LibraryItem, SearchGroup
from harmonia.video import find_video_variant, resolve_video_stream


class SearchClient:
    def __init__(self, items):
        self.items = items

    def search_category(self, query: str, category: str):
        assert category == "videos"
        assert query
        return SearchGroup("videos", "Vídeos", list(self.items))


def test_video_item_uses_its_existing_video_id():
    item = LibraryItem("video123", "Song", "Artist", kind="videos")
    assert find_video_variant(SearchClient([]), item, force=True) == "video123"


def test_video_variant_prefers_matching_title_and_artist():
    item = LibraryItem("song123", "Midnight Drive", "The Satellites · Album · 3:42", kind="songs")
    client = SearchClient(
        [
            LibraryItem("wrong", "Midnight Drive", "Different Artist", kind="videos"),
            LibraryItem(
                "right",
                "Midnight Drive (Official Music Video)",
                "The Satellites · 12 mi de visualizações",
                kind="videos",
            ),
        ]
    )
    assert find_video_variant(client, item, force=True) == "right"


def test_video_variant_rejects_unrelated_results():
    item = LibraryItem("song999", "Northern Lights", "Aster", kind="songs")
    client = SearchClient(
        [LibraryItem("wrong", "Completely Different", "Another Channel", kind="videos")]
    )
    with pytest.raises(InnerTubeError):
        find_video_variant(client, item, force=True)


def test_progressive_video_prefers_highest_format_within_limit(monkeypatch):
    item = LibraryItem("video-quality", "Song", "Artist", kind="videos")

    class PlayerClient:
        gl = "BR"

        def _bootstrap(self):
            return None

    payload = {
        "playabilityStatus": {"status": "OK"},
        "streamingData": {
            "formats": [
                {
                    "url": "https://example.test/360.mp4",
                    "mimeType": 'video/mp4; codecs="avc1, mp4a"',
                    "height": 360,
                    "width": 640,
                    "fps": 30,
                    "bitrate": 500_000,
                    "itag": 18,
                },
                {
                    "url": "https://example.test/720.mp4",
                    "mimeType": 'video/mp4; codecs="avc1, mp4a"',
                    "height": 720,
                    "width": 1280,
                    "fps": 30,
                    "bitrate": 2_000_000,
                    "itag": 22,
                },
                {
                    "url": "https://example.test/1080.mp4",
                    "mimeType": 'video/mp4; codecs="avc1, mp4a"',
                    "height": 1080,
                    "width": 1920,
                    "fps": 30,
                    "bitrate": 4_000_000,
                    "itag": 37,
                },
            ]
        },
    }

    monkeypatch.setattr("harmonia.video._player_payload", lambda *_args, **_kwargs: payload)
    stream = resolve_video_stream(PlayerClient(), item, max_height=720, force=True)
    assert stream.height == 720
    assert stream.url.endswith("720.mp4")
    assert stream.muxed is True


def test_qt_video_layer_can_use_adaptive_video_only(monkeypatch):
    item = LibraryItem("video-adaptive", "Song", "Artist", kind="videos")

    class PlayerClient:
        gl = "BR"

        def _bootstrap(self):
            return None

    payload = {
        "playabilityStatus": {"status": "OK"},
        "streamingData": {
            "formats": [],
            "adaptiveFormats": [
                {
                    "url": "https://example.test/480.mp4",
                    "mimeType": 'video/mp4; codecs="avc1.4d401f"',
                    "height": 480,
                    "width": 854,
                    "fps": 30,
                    "bitrate": 900_000,
                    "itag": 135,
                },
                {
                    "url": "https://example.test/720.mp4",
                    "mimeType": 'video/mp4; codecs="avc1.64001f"',
                    "height": 720,
                    "width": 1280,
                    "fps": 30,
                    "bitrate": 1_500_000,
                    "itag": 136,
                },
            ],
        },
    }

    monkeypatch.setattr("harmonia.video._player_payload", lambda *_args, **_kwargs: payload)
    stream = resolve_video_stream(
        PlayerClient(),
        item,
        max_height=720,
        force=True,
        allow_video_only=True,
    )
    assert stream.height == 720
    assert stream.itag == 136
    assert stream.muxed is False
