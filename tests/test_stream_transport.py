from __future__ import annotations

import time

from harmonia.stream_transport import (
    clear_stream_transport,
    mark_stream_transport_failure,
    register_stream_transport,
    stream_transport_blocked,
    stream_transport_headers,
)


def setup_function():
    clear_stream_transport()


def test_transport_preserves_headers_and_failure_quarantine():
    url = "https://r1.googlevideo.com/videoplayback?id=test&itag=251"
    headers = (("User-Agent", "harmonia-test"), ("Referer", "https://www.youtube.com/"))

    register_stream_transport(url, headers, expires_at=int(time.time()) + 600)
    assert stream_transport_headers(url) == headers
    assert stream_transport_blocked(url) is False

    mark_stream_transport_failure(url, ttl=60)
    assert stream_transport_blocked(url) is True

    register_stream_transport(url, headers, expires_at=int(time.time()) + 600)
    assert stream_transport_blocked(url) is True


def test_failure_quarantine_does_not_block_same_itag_for_another_video():
    failed = "https://r1.googlevideo.com/videoplayback?id=video-a&itag=251&cpn=first"
    other = "https://r2.googlevideo.com/videoplayback?id=video-b&itag=251&cpn=second"

    mark_stream_transport_failure(failed, ttl=60)

    assert stream_transport_blocked(failed) is True
    assert stream_transport_blocked(other) is False


def test_failure_quarantine_ignores_request_scoped_tokens():
    first = "https://r1.googlevideo.com/videoplayback?id=video-a&itag=251&cpn=first&pot=one"
    refreshed = "https://r1.googlevideo.com/videoplayback?id=video-a&itag=251&cpn=second&pot=two"

    mark_stream_transport_failure(first, ttl=60)

    assert stream_transport_blocked(refreshed) is True


def test_expired_transport_is_discarded():
    url = "https://r2.googlevideo.com/videoplayback?id=expired"
    register_stream_transport(
        url,
        (("User-Agent", "expired"),),
        expires_at=int(time.time()) - 1,
    )

    assert stream_transport_headers(url) == ()
    assert stream_transport_blocked(url) is False
