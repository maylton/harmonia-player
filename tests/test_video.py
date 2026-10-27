from __future__ import annotations

import pytest

from harmonia.innertube import PLAYER_CLIENTS, InnerTubeError
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


def test_video_variant_prefers_authoritative_music_video_counterpart():
    item = LibraryItem(
        "audio-closer",
        "Closer",
        "Tocou 79\u00a0mi vezes · 3:29",
        kind="songs",
    )

    class CounterpartClient(SearchClient):
        def __init__(self):
            super().__init__([LibraryItem("wrong", "Closer", "Outro artista", kind="videos")])
            self.search_called = False

        def video_counterpart(self, video_id: str):
            assert video_id == "audio-closer"
            return "official-closer"

        def search_category(self, query: str, category: str):
            self.search_called = True
            return super().search_category(query, category)

    client = CounterpartClient()
    assert find_video_variant(client, item, force=True) == "official-closer"
    assert not client.search_called


def test_video_variant_falls_back_when_counterpart_lookup_fails():
    item = LibraryItem("song-fallback", "Fallback Song", "Fallback Artist · 3:12", kind="songs")

    class FailingCounterpartClient(SearchClient):
        def video_counterpart(self, _video_id: str):
            raise InnerTubeError("counterpart unavailable")

    client = FailingCounterpartClient(
        [LibraryItem("fallback-video", "Fallback Song", "Fallback Artist", kind="videos")]
    )

    assert find_video_variant(client, item, force=True) == "fallback-video"


def test_video_variant_rejects_unrelated_results():
    item = LibraryItem("song999", "Northern Lights", "Aster", kind="songs")
    client = SearchClient(
        [LibraryItem("wrong", "Completely Different", "Another Channel", kind="videos")]
    )
    with pytest.raises(InnerTubeError):
        find_video_variant(client, item, force=True)


def test_video_variant_does_not_treat_play_count_as_artist():
    item = LibraryItem(
        "song-sign",
        "Sign",
        "Tocou 251\u00a0mi vezes · 3:57",
        kind="songs",
    )

    class QueryClient(SearchClient):
        def __init__(self):
            super().__init__([LibraryItem("sign-video", "Sign", "FLOW", kind="videos")])
            self.queries = []

        def search_category(self, query: str, category: str):
            self.queries.append(query)
            return super().search_category(query, category)

    client = QueryClient()
    assert find_video_variant(client, item, force=True) == "sign-video"
    assert client.queries == ["Sign"]


def test_video_variant_rejects_exact_title_from_unrelated_artist():
    item = LibraryItem(
        "song-body-type",
        "BODY TYPE",
        "Pabllo Vittar e Urias · Tocou 66\u00a0mil vezes · 2:27",
        kind="songs",
    )
    client = SearchClient(
        [
            LibraryItem("wrong", "Body Type", "Zepeto Drift", kind="videos"),
            LibraryItem(
                "variant",
                "Pabllo Vittar, Urias - BODY TYPE (Sped Up)",
                "Kye • 49 visualizações • 2:03",
                kind="videos",
            ),
            LibraryItem(
                "right",
                "Pabllo Vittar, Urias - BODY TYPE (Videoclipe)",
                "QG da Pabllo Vittar • 128 visualizações • 2:22",
                kind="videos",
            ),
        ]
    )
    assert find_video_variant(client, item, force=True) == "right"


def test_video_variant_prefers_official_video_search_over_same_title_lyrics():
    item = LibraryItem(
        "song-beautiful-girls",
        "Beautiful Girls",
        "Sean Kingston · Sean Kingston · 4:02",
        kind="songs",
    )

    class OfficialQueryClient(SearchClient):
        def __init__(self):
            super().__init__([])
            self.queries = []

        def search_category(self, query: str, category: str):
            self.queries.append(query)
            if query.endswith("official music video"):
                items = [
                    LibraryItem(
                        "official",
                        "Beautiful Girls",
                        "Sean Kingston • 1,5 bi de visualizações • 4:22",
                        kind="videos",
                    ),
                    LibraryItem(
                        "lyrics-canonical",
                        "Beautiful Girls",
                        "Sean Kingston • 37 mi de visualizações • 4:02",
                        kind="videos",
                    ),
                ]
            else:
                items = [
                    LibraryItem(
                        "lyrics",
                        "Beautiful Girls",
                        "Sean Kingston • 37 mi de visualizações • 4:02",
                        kind="videos",
                    )
                ]
            return SearchGroup("videos", "Vídeos", items)

    client = OfficialQueryClient()
    assert find_video_variant(client, item, force=True) == "official"
    assert client.queries == [
        "Beautiful Girls Sean Kingston",
        "Beautiful Girls Sean Kingston official music video",
    ]


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

    PlayerClient.player_response = lambda *_args, **_kwargs: payload
    stream = resolve_video_stream(PlayerClient(), item, max_height=720, force=True)
    assert stream.height == 720
    assert stream.url.endswith("720.mp4")
    assert stream.muxed is True
    assert stream.request_headers == {
        "User-Agent": PLAYER_CLIENTS[0]["user_agent"],
        "Accept": "*/*",
    }


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

    PlayerClient.player_response = lambda *_args, **_kwargs: payload
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

        def _bootstrap(self):
            return None

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

    PlayerClient.player_response = lambda *_args, **_kwargs: payload
    stream = resolve_video_stream(
        PlayerClient(),
        item,
        max_height=720,
        force=True,
        allow_video_only=True,
    )

    assert stream.itag == 135
    assert stream.height == 480
    assert stream.stream_type == ""
    assert stream.content_length == 12_345_678
    assert stream.init_range == (0, 739)
    assert stream.index_range == (740, 1515)


def test_video_failures_name_each_client_and_its_reason():
    item = LibraryItem("video-missing", "Song", "Artist", kind="videos")

    class PlayerClient:
        gl = "BR"

        def _bootstrap(self):
            return None

        def player_response(self, _video_id, profile):
            raise InnerTubeError(f"HTTP 4{len(profile['name'])}")

    with pytest.raises(InnerTubeError) as error:
        resolve_video_stream(PlayerClient(), item, force=True)
    for profile in PLAYER_CLIENTS:
        assert f"{profile['name']}: HTTP 4{len(profile['name'])}" in str(error.value)


def _adaptive(height, codec, itag, *, mime="video/mp4"):
    return {
        "url": f"https://example.test/{itag}",
        "mimeType": f'{mime}; codecs="{codec}"',
        "height": height,
        "width": height * 16 // 9,
        "fps": 30,
        "bitrate": height * 1000,
        "itag": itag,
        "contentLength": "1000",
        "initRange": {"start": "0", "end": "10"},
        "indexRange": {"start": "11", "end": "20"},
    }


def _resolve_among(formats, progressive=()):
    class PlayerClient:
        gl = "BR"

        def _bootstrap(self):
            return None

        def player_response(self, *_args, **_kwargs):
            return {
                "playabilityStatus": {"status": "OK"},
                "streamingData": {"formats": list(progressive), "adaptiveFormats": formats},
            }

    item = LibraryItem(f"video-{len(formats)}", "Song", "Artist", kind="videos")
    return resolve_video_stream(PlayerClient(), item, force=True, allow_video_only=True)


FORMATS = [
    _adaptive(720, "avc1.4D401F", 136),
    _adaptive(1080, "vp9", 248, mime="video/webm"),
    _adaptive(1080, "av01.0.08M.08", 399),
]


def test_video_reaches_1080p_with_a_codec_this_system_decodes(monkeypatch):
    from harmonia import host, video

    monkeypatch.setattr(host, "IS_WINDOWS", False)
    # Software only, without a fast AV1 decoder (libaom is left out).
    monkeypatch.setattr(
        video, "_video_decoders", lambda: {"video/x-h264": "software", "video/x-vp9": "software"}
    )
    assert _resolve_among(FORMATS).itag == 248
    monkeypatch.setattr(video, "_video_decoders", lambda: {"video/x-h264": "software"})
    assert _resolve_among(FORMATS).itag == 136  # VP9 and AV1 cannot play here
    hardware = {"video/x-h264": "hardware", "video/x-vp9": "hardware", "video/x-av1": "hardware"}
    monkeypatch.setattr(video, "_video_decoders", lambda: hardware)
    assert _resolve_among(FORMATS).itag == 399  # the graphics card takes the newest codec


def test_windows_takes_indexed_mp4_and_h264_first(monkeypatch):
    from harmonia import host, video

    monkeypatch.setattr(host, "IS_WINDOWS", True)
    hardware = {"video/x-h264": "hardware", "video/x-vp9": "hardware", "video/x-av1": "hardware"}
    monkeypatch.setattr(video, "_video_decoders", lambda: hardware)
    # The indexed MP4, which the relay serves as DASH, wins over the WebM, and
    # at the same height H.264, which D3D decodes on the GPU too.
    formats = [
        _adaptive(1080, "vp9", 248, mime="video/webm"),
        _adaptive(1080, "avc1.640028", 137),
        _adaptive(1080, "av01.0.08M.08", 399),
    ]
    assert _resolve_among(formats).itag == 137
    # Only a WebM there: it is still played.
    assert _resolve_among(formats[:1]).itag == 248


def test_video_beside_the_audio_skips_the_360p_muxed_format(monkeypatch):
    from harmonia import video

    monkeypatch.setattr(video, "_video_decoders", lambda: {"video/x-h264": "software"})
    muxed = {
        "url": "https://example.test/18",
        "mimeType": 'video/mp4; codecs="avc1.42001E, mp4a.40.2"',
        "height": 360,
        "itag": 18,
    }
    stream = _resolve_among([_adaptive(1080, "avc1.640028", 137)], progressive=[muxed])
    assert stream.itag == 137 and stream.muxed is False
