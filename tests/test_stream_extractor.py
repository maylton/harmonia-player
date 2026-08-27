from __future__ import annotations

from harmonia.stream_extractor import (
    InnerTubeStreamExtractor,
    PlayerClientProfile,
    _cipher_url,
)


class DummyClient:
    authenticated = False
    cookie = ""
    hl = "pt-BR"
    gl = "BR"
    client_version = "1.test"
    visitor_data = None
    data_sync_id = None

    def _bootstrap(self):
        return None


def profile(name="TEST"):
    return PlayerClientProfile(
        id="1",
        name=name,
        version="1.0",
        user_agent="test-agent",
    )


def test_cipher_url_accepts_direct_and_clear_signature():
    assert _cipher_url({"url": "https://media.test/direct"}) == "https://media.test/direct"

    cipher = (
        "url=https%3A%2F%2Fmedia.test%2Fvideo%3Fx%3D1"
        "&sp=sig&sig=already-clear"
    )
    assert _cipher_url({"signatureCipher": cipher}) == (
        "https://media.test/video?x=1&sig=already-clear"
    )


def test_cipher_url_defers_encrypted_signature_to_cipher_provider():
    cipher = "url=https%3A%2F%2Fmedia.test%2Fvideo&sp=sig&s=encrypted"
    assert _cipher_url({"signatureCipher": cipher}) is None


def test_video_selection_prefers_720p_vp9_over_av1():
    extractor = InnerTubeStreamExtractor(DummyClient())
    payload = {
        "playabilityStatus": {"status": "OK"},
        "streamingData": {
            "adaptiveFormats": [
                {
                    "url": "https://media.test/av1",
                    "mimeType": 'video/mp4; codecs="av01.0.05M.08"',
                    "height": 720,
                    "width": 1280,
                    "fps": 30,
                    "bitrate": 1_900_000,
                    "itag": 398,
                },
                {
                    "url": "https://media.test/vp9",
                    "mimeType": 'video/webm; codecs="vp9"',
                    "height": 720,
                    "width": 1280,
                    "fps": 30,
                    "bitrate": 1_500_000,
                    "itag": 247,
                },
                {
                    "url": "https://media.test/1080",
                    "mimeType": 'video/webm; codecs="vp9"',
                    "height": 1080,
                    "width": 1920,
                    "fps": 30,
                    "bitrate": 2_500_000,
                    "itag": 248,
                },
            ]
        },
    }
    extractor._payloads = lambda *_args: iter([(profile(), payload)])
    selected = extractor.extract_video("video", max_height=720)
    assert selected.url == "https://media.test/vp9"
    assert selected.itag == 247


def test_progressive_only_ignores_adaptive_video():
    extractor = InnerTubeStreamExtractor(DummyClient())
    payload = {
        "playabilityStatus": {"status": "OK"},
        "streamingData": {
            "formats": [
                {
                    "url": "https://media.test/muxed",
                    "mimeType": 'video/mp4; codecs="avc1.4d401f, mp4a.40.2"',
                    "height": 360,
                    "width": 640,
                    "fps": 30,
                    "bitrate": 600_000,
                    "itag": 18,
                }
            ],
            "adaptiveFormats": [
                {
                    "url": "https://media.test/adaptive",
                    "mimeType": 'video/webm; codecs="vp9"',
                    "height": 720,
                    "width": 1280,
                    "fps": 30,
                    "bitrate": 1_500_000,
                    "itag": 247,
                }
            ],
        },
    }
    extractor._payloads = lambda *_args: iter([(profile(), payload)])
    selected = extractor.extract_video("video", max_height=720, progressive_only=True)
    assert selected.url == "https://media.test/muxed"
    assert selected.muxed is True


def test_audio_selection_respects_max_bitrate():
    extractor = InnerTubeStreamExtractor(DummyClient())
    payload = {
        "playabilityStatus": {"status": "OK"},
        "streamingData": {
            "adaptiveFormats": [
                {
                    "url": "https://media.test/low",
                    "mimeType": 'audio/webm; codecs="opus"',
                    "bitrate": 128_000,
                    "itag": 251,
                },
                {
                    "url": "https://media.test/high",
                    "mimeType": 'audio/mp4; codecs="mp4a.40.2"',
                    "bitrate": 256_000,
                    "itag": 141,
                },
            ]
        },
    }
    extractor._payloads = lambda *_args: iter([(profile(), payload)])
    selected = extractor.extract_audio("audio", max_bitrate=192_000)
    assert selected.url == "https://media.test/low"
    assert selected.itag == 251
