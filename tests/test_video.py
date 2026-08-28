from __future__ import annotations

import pytest

from harmonia.innertube import InnerTubeError
from harmonia.models import LibraryItem, SearchGroup
from harmonia.stream_extractor import StreamCandidate
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
    item = LibraryItem(
        "song123",
        "Midnight Drive",
        "The Satellites · Album · 3:42",
        kind="songs",
    )
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


def test_progressive_video_uses_shared_extractor(monkeypatch):
    item = LibraryItem("video-quality", "Song", "Artist", kind="videos")

    class PlayerClient:
        gl = "BR"

    def extract(_self, video_id, *, max_height, progressive_only, force=False):
        assert video_id == "video-quality"
        assert max_height == 720
        assert progressive_only is True
        assert force is True
        return StreamCandidate(
            url="https://example.test/720.mp4",
            client="TEST",
            mime_type='video/mp4; codecs="avc1, mp4a"',
            bitrate=2_000_000,
            itag=22,
            duration_ms=42_000,
            width=1280,
            height=720,
            fps=30,
            muxed=True,
        )

    monkeypatch.setattr("harmonia.video.InnerTubeStreamExtractor.extract_video", extract)
    stream = resolve_video_stream(PlayerClient(), item, max_height=720, force=True)
    assert stream.height == 720
    assert stream.url.endswith("720.mp4")
    assert stream.muxed is True
    assert stream.request_headers == {}


def test_qt_video_layer_can_use_adaptive_video_only(monkeypatch):
    item = LibraryItem("video-adaptive", "Song", "Artist", kind="videos")

    class PlayerClient:
        gl = "BR"

    def extract(_self, video_id, *, max_height, progressive_only, force=False):
        assert video_id == "video-adaptive"
        assert max_height == 720
        assert progressive_only is False
        assert force is True
        return StreamCandidate(
            url="https://example.test/720.mp4",
            client="TEST",
            mime_type='video/mp4; codecs="avc1.64001f"',
            bitrate=1_500_000,
            itag=136,
            duration_ms=42_000,
            width=1280,
            height=720,
            fps=30,
            muxed=False,
        )

    monkeypatch.setattr("harmonia.video.InnerTubeStreamExtractor.extract_video", extract)
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


def test_adaptive_video_rejects_otf_and_prefers_indexed_random_access(monkeypatch):
    item = LibraryItem("video-seekable", "Song", "Artist", kind="videos")

    class PlayerClient:
        gl = "BR"

    payload = {
        "playabilityStatus": {"status": "OK"},
        "streamingData": {
            "formats": [],
            "adaptiveFormats": [
                {
                    "url": "https://example.test/720-otf.mp4",
                    "mimeType": 'video/mp4; codecs="avc1.64001f"',
                    "height": 720,
                    "width": 1280,
                    "fps": 30,
                    "bitrate": 1_800_000,
                    "itag": 136,
                    "type": "FORMAT_STREAM_TYPE_OTF",
                    "targetDurationSec": 5,
                },
                {
                    "url": "https://example.test/480-indexed.mp4",
                    "mimeType": 'video/mp4; codecs="avc1.4d401f"',
                    "height": 480,
                    "width": 854,
                    "fps": 30,
                    "bitrate": 900_000,
                    "itag": 135,
                    "contentLength": "12345678",
                    "initRange": {"start": "0", "end": "739"},
                    "indexRange": {"start": "740", "end": "1515"},
                },
            ],
        },
    }

    def payloads(_self, *_args, **_kwargs):
        from harmonia.stream_extractor import PlayerClientProfile

        yield PlayerClientProfile("1", "TEST", "1", "test-agent"), payload

    monkeypatch.setattr("harmonia.stream_extractor.InnerTubeStreamExtractor._payloads", payloads)
    monkeypatch.setattr(
        "harmonia.stream_extractor.InnerTubeStreamExtractor._probe", lambda *_: True
    )
    stream = resolve_video_stream(
        PlayerClient(),
        item,
        max_height=720,
        force=True,
        allow_video_only=True,
    )

    assert stream.itag == 135
    assert stream.height == 480
    assert stream.content_length == 12_345_678
