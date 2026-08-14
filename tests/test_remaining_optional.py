from __future__ import annotations

import io
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from harmonia.cast import CastDevice, LocalMediaServer, UpnpDiscovery, UpnpRenderer
from harmonia.models import LibraryItem
from harmonia.recognition import AuddRecognitionProvider, MusicRecognizer
from harmonia.together import TogetherClient, TogetherHost, TogetherState
from harmonia.window_optional import WindowOptionalMixin


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_listen_together_roundtrip_and_delay_correction():
    host = TogetherHost("127.0.0.1")
    try:
        state = TogetherState(
            [LibraryItem("one", "Song", "Artist")],
            position_ms=12_000,
            playing=True,
        )
        host.update(state)
        client = TogetherClient(host.share_url("127.0.0.1"))
        received = client.fetch()

        assert received.queue == state.queue
        assert received.revision == 1
        assert received.corrected_position_ms(received.sent_at_ms + 750) == 12_750
    finally:
        host.close()


def test_listen_together_rejects_invalid_or_unauthorized_links():
    with pytest.raises(ValueError):
        TogetherClient("https://example.com/session")

    host = TogetherHost("127.0.0.1")
    try:
        invalid = host.share_url("127.0.0.1").replace(host.token, "wrong-token")
        with pytest.raises(urllib.error.HTTPError):
            TogetherClient(invalid).fetch()
    finally:
        host.close()


def test_audd_recognition_uses_temporary_recording(tmp_path):
    requests = []

    def opener(request, timeout):
        requests.append((request, timeout))
        return Response(
            json.dumps(
                {
                    "status": "success",
                    "result": {
                        "title": "911",
                        "artist": "Lady Gaga",
                        "album": "Chromatica",
                        "song_link": "https://lis.tn/911",
                    },
                }
            ).encode()
        )

    captured = []

    class Recorder:
        def capture(self, output: Path, seconds: int):
            captured.append((output, seconds))
            output.write_bytes(b"RIFF-audio")
            return output

    result = MusicRecognizer(AuddRecognitionProvider("token", opener), Recorder()).recognize(3)

    assert (result.title, result.artist, result.album) == ("911", "Lady Gaga", "Chromatica")
    assert captured[0][1] == 3
    assert not captured[0][0].parent.exists()
    assert requests[0][1] == 30
    assert b'name="api_token"' in requests[0][0].data
    assert b"RIFF-audio" in requests[0][0].data


DEVICE_XML = b"""<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
 <device><friendlyName>Living Room</friendlyName><serviceList><service>
  <serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>
  <controlURL>/upnp/control/avtransport</controlURL>
 </service></serviceList></device>
</root>"""


def test_upnp_device_parsing_and_remote_controls():
    requests = []

    def opener(request, timeout):
        requests.append((request, timeout))
        if isinstance(request, str):
            return Response(DEVICE_XML)
        return Response(b"")

    discovery = UpnpDiscovery(opener=opener)
    device = discovery._device("http://192.0.2.4:1400/description.xml")
    assert device == CastDevice(
        "Living Room",
        "http://192.0.2.4:1400/description.xml",
        "http://192.0.2.4:1400/upnp/control/avtransport",
    )

    renderer = UpnpRenderer(device, opener)
    renderer.play_uri("https://media.example/song.m4a?a=1&b=2", "Song & Artist")
    renderer.pause()
    renderer.seek(65_000)
    renderer.stop()

    actions = [request.headers["Soapaction"] for request, _timeout in requests[1:]]
    assert actions == [
        '"urn:schemas-upnp-org:service:AVTransport:1#SetAVTransportURI"',
        '"urn:schemas-upnp-org:service:AVTransport:1#Play"',
        '"urn:schemas-upnp-org:service:AVTransport:1#Pause"',
        '"urn:schemas-upnp-org:service:AVTransport:1#Seek"',
        '"urn:schemas-upnp-org:service:AVTransport:1#Stop"',
    ]
    assert b"00:01:05" in requests[4][0].data
    assert b"Song &amp;amp; Artist" in requests[1][0].data


def test_together_paused_state_does_not_accumulate_delay():
    state = TogetherState(
        position_ms=5_000, playing=False, sent_at_ms=int(time.time() * 1000) - 900
    )
    assert state.corrected_position_ms() == 5_000


def test_local_cast_media_server_supports_ranges(monkeypatch, tmp_path):
    from harmonia import cast as cast_module

    monkeypatch.setattr(cast_module, "local_address", lambda: "127.0.0.1")
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"0123456789")
    server = LocalMediaServer(audio)
    try:
        request = urllib.request.Request(server.url, headers={"Range": "bytes=3-6"})
        with urllib.request.urlopen(request) as response:
            assert response.status == 206
            assert response.headers["Content-Type"] == "audio/mp4"
            assert response.headers["Content-Range"] == "bytes 3-6/10"
            assert response.read() == b"3456"
    finally:
        server.close()


def test_window_shutdown_releases_services_and_quits_once(monkeypatch):
    events = []

    class Service:
        def close(self):
            events.append("close")

    class Application:
        def quit(self):
            events.append("quit")

    window = WindowOptionalMixin()
    window._shutdown_started = False
    window._optional_tick_source = 0
    window.mpris = Service()
    window.player = Service()
    window._close_optional_services = lambda: events.append("optional")
    window._close_social_integrations = lambda: events.append("social")
    window.get_application = Application
    monkeypatch.setattr(
        "harmonia.window_optional.GLib.idle_add", lambda callback, *args: callback(*args)
    )

    assert window._shutdown_application() is False
    assert window._shutdown_application() is False
    assert events == ["optional", "social", "close", "close", "quit"]
