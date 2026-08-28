from harmonia.models import LibraryItem
from harmonia.resilient_video import resolve_resilient_video_stream
from harmonia.stream_extractor import StreamCandidate


def test_resilient_video_uses_current_variant_selection_and_shared_extractor(monkeypatch):
    item = LibraryItem("song-id", "Song", "Artist", kind="songs")

    class Client:
        pass

    monkeypatch.setattr(
        "harmonia.resilient_video.find_video_variant",
        lambda client, candidate, force=False: "official-video-id",
    )

    def extract(_self, video_id, *, max_height, progressive_only, force=False):
        assert video_id == "official-video-id"
        assert max_height == 720
        assert progressive_only is False
        assert force is True
        return StreamCandidate(
            url="https://example.test/video.mp4",
            client="TEST",
            mime_type='video/mp4; codecs="avc1"',
            bitrate=1_500_000,
            itag=136,
            duration_ms=42_000,
            width=1280,
            height=720,
            fps=30,
            muxed=False,
            headers=(("User-Agent", "test-agent"),),
            content_length=12_345,
        )

    monkeypatch.setattr(
        "harmonia.resilient_video.InnerTubeStreamExtractor.extract_video",
        extract,
    )

    stream = resolve_resilient_video_stream(
        Client(),
        item,
        max_height=720,
        force=True,
        allow_video_only=True,
    )

    assert stream.video_id == "official-video-id"
    assert stream.url == "https://example.test/video.mp4"
    assert stream.request_headers == {"User-Agent": "test-agent"}
    assert stream.muxed is False
