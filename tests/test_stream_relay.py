import http.client
import re
import urllib.parse
import urllib.request

import pytest

from harmonia.stream_relay import StreamRelay

DATA = bytes(range(256)) * 20  # 5120 bytes


class Upstream:
    """urlopen stand-in serving DATA for bounded Range requests, like Googlevideo."""

    def __init__(self):
        self.ranges: list[tuple[int, int]] = []

    def __call__(self, request, timeout=None):
        start, end = map(int, re.fullmatch(r"bytes=(\d+)-(\d+)", request.headers["Range"]).groups())
        self.ranges.append((start, end))
        end = min(end, len(DATA) - 1)
        return Response(DATA[start : end + 1], f"bytes {start}-{end}/{len(DATA)}")


class Response:
    def __init__(self, body: bytes, content_range: str):
        self.body = body
        self.headers = {"Content-Range": content_range, "Content-Type": "audio/webm"}

    def read(self, size=-1):
        chunk, self.body = (self.body, b"") if size < 0 else (self.body[:size], self.body[size:])
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


@pytest.fixture
def relay(monkeypatch):
    upstream = Upstream()
    monkeypatch.setattr(urllib.request, "urlopen", upstream)
    monkeypatch.setattr(StreamRelay, "CHUNK_SIZE", 1000)
    relay = StreamRelay()
    relay.upstream = upstream
    yield relay
    relay.close()


def fetch(uri: str, method: str = "GET", headers: dict | None = None):
    parts = urllib.parse.urlsplit(uri)
    connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=10)
    connection.request(method, parts.path, headers=headers or {})
    response = connection.getresponse()
    body = response.read()
    connection.close()
    return response, body


def test_whole_stream_is_relayed_in_bounded_chunks(relay):
    response, body = fetch(relay.uri_for("https://media.example/v?id=1", {"X-Test": "1"}))
    assert response.status == 200
    assert body == DATA
    assert response.getheader("Content-Length") == str(len(DATA))
    # Googlevideo rejects open-ended ranges: every upstream request is bounded.
    assert relay.upstream.ranges[0] == (0, 999)
    assert all(end - start < 1000 for start, end in relay.upstream.ranges)


def test_range_requests_get_partial_content(relay):
    uri = relay.uri_for("https://media.example/v?id=2")
    response, body = fetch(uri, headers={"Range": "bytes=4000-"})
    assert response.status == 206
    assert body == DATA[4000:]
    assert response.getheader("Content-Range") == f"bytes 4000-{len(DATA) - 1}/{len(DATA)}"

    response, body = fetch(uri, headers={"Range": "bytes=10-19"})
    assert response.status == 206 and body == DATA[10:20]


def test_head_answers_without_a_body_and_past_the_end_is_416(relay):
    uri = relay.uri_for("https://media.example/v?id=3")
    response, body = fetch(uri, "HEAD")
    assert response.status == 200 and body == b""
    assert response.getheader("Content-Length") == str(len(DATA))

    response, _body = fetch(uri, headers={"Range": f"bytes={len(DATA) + 10}-"})
    assert response.status == 416
    assert response.getheader("Content-Range") == f"bytes */{len(DATA)}"


def test_unknown_streams_and_manifests_are_404(relay):
    base = relay.uri_for("https://media.example/v?id=4").rsplit("/stream/", 1)[0]
    assert fetch(base + "/stream/999")[0].status == 404
    assert fetch(base + "/manifest/999")[0].status == 404


def test_only_the_latest_streams_are_kept(relay):
    for index in range(6):
        relay.uri_for(f"https://media.example/v?id={index}")
    assert sorted(relay.streams) == [3, 4, 5, 6]


def box(kind: bytes, payload: bytes = b"") -> bytes:
    return (8 + len(payload)).to_bytes(4, "big") + kind + payload


def test_mp4_segment_base_is_located_from_the_sidx_box():
    head = box(b"ftyp", b"isom") + box(b"moov", b"\0" * 20)
    data = head + box(b"sidx", b"\0" * 12) + box(b"moof")
    assert StreamRelay._locate_mp4_segment_base(data) == (
        (0, len(head) - 1),
        (len(head), len(head) + 19),
    )
    assert StreamRelay._locate_mp4_segment_base(box(b"ftyp") + box(b"moov")) is None


def test_only_indexed_mp4_video_gets_a_dash_manifest(relay):
    assert relay.dash_uri_for("https://media.example/v?mime=audio%2Fwebm&gir=yes") is None
    assert relay.dash_uri_for("https://media.example/v?mime=video%2Fmp4&gir=no") is None
