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
    url = "https://r1.googlevideo.com/videoplayback?id=test"
    headers = (("User-Agent", "harmonia-test"), ("Referer", "https://www.youtube.com/"))

    register_stream_transport(url, headers, expires_at=int(time.time()) + 600)
    assert stream_transport_headers(url) == headers
    assert stream_transport_blocked(url) is False

    mark_stream_transport_failure(url, ttl=60)
    assert stream_transport_blocked(url) is True

    # Re-registering a freshly resolved copy of the same URL must not erase a
    # recent playback failure; otherwise force=True would select it again.
    register_stream_transport(url, headers, expires_at=int(time.time()) + 600)
    assert stream_transport_blocked(url) is True


def test_expired_transport_is_discarded():
    url = "https://r2.googlevideo.com/videoplayback?id=expired"
    register_stream_transport(
        url,
        (("User-Agent", "expired"),),
        expires_at=int(time.time()) - 1,
    )

    assert stream_transport_headers(url) == ()
    assert stream_transport_blocked(url) is False
