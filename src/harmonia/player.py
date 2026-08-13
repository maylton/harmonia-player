from __future__ import annotations

import re
import threading
import urllib.parse
import urllib.request
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import pairwise
from typing import ClassVar

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst

from .i18n import _


class _StreamRelay:
    """Local range relay for Googlevideo URLs.

    Googlevideo currently rejects the open-ended Range requests emitted by
    GStreamer's souphttpsrc. urllib works correctly with bounded ranges, so the
    relay translates those requests in 1 MiB chunks while remaining localhost-only.
    """

    CHUNK_SIZE = 1024 * 1024

    def __init__(self):
        self.streams: dict[int, str] = {}
        relay = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _remote(self) -> str | None:
                try:
                    generation = int(self.path.rstrip("/").rsplit("/", 1)[-1])
                except ValueError:
                    return None
                return relay.streams.get(generation)

            @staticmethod
            def _range(value: str | None) -> tuple[int, int | None, bool]:
                if not value:
                    return 0, None, False
                match = re.fullmatch(r"bytes=(\d+)-(\d*)", value.strip())
                if not match:
                    raise ValueError(_("Intervalo HTTP inválido"))
                return int(match.group(1)), int(match.group(2)) if match.group(2) else None, True

            @staticmethod
            def _upstream(remote: str, start: int, end: int):
                request = urllib.request.Request(
                    remote, headers={"Range": f"bytes={start}-{end}"}, method="GET"
                )
                return urllib.request.urlopen(request, timeout=30)

            def _serve(self, send_body: bool):
                remote = self._remote()
                if not remote:
                    self.send_error(404)
                    return
                headers_sent = False
                try:
                    start, requested_end, partial = self._range(self.headers.get("Range"))
                    first_end = start + relay.CHUNK_SIZE - 1
                    if requested_end is not None:
                        first_end = min(first_end, requested_end)
                    with self._upstream(remote, start, first_end) as first:
                        content_range = first.headers.get("Content-Range", "")
                        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
                        if not match:
                            raise OSError(_("O servidor de áudio não informou o tamanho total"))
                        total = int(match.group(3))
                        if start >= total:
                            self.send_response(416)
                            self.send_header("Content-Range", f"bytes */{total}")
                            self.send_header("Content-Length", "0")
                            self.end_headers()
                            headers_sent = True
                            return
                        end = min(
                            requested_end if requested_end is not None else total - 1, total - 1
                        )
                        self.send_response(206 if partial else 200)
                        self.send_header(
                            "Content-Type", first.headers.get("Content-Type", "audio/mp4")
                        )
                        self.send_header("Content-Length", str(end - start + 1))
                        self.send_header("Accept-Ranges", "bytes")
                        if partial:
                            self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        headers_sent = True
                        if not send_body:
                            return
                        cursor = start
                        while chunk := first.read(64 * 1024):
                            self.wfile.write(chunk)
                            cursor += len(chunk)
                        while cursor <= end:
                            chunk_end = min(cursor + relay.CHUNK_SIZE - 1, end)
                            with self._upstream(remote, cursor, chunk_end) as response:
                                while chunk := response.read(64 * 1024):
                                    self.wfile.write(chunk)
                                    cursor += len(chunk)
                except (BrokenPipeError, ConnectionError):
                    return
                except Exception as exc:
                    if not self.wfile.closed and not headers_sent:
                        with suppress(BrokenPipeError, ConnectionError):
                            self.send_error(502, str(exc))
                finally:
                    self.close_connection = True

            def do_GET(self):
                self._serve(True)

            def do_HEAD(self):
                self._serve(False)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(
            target=self.server.serve_forever, daemon=True, name="harmonia-stream-relay"
        ).start()
        self.generation = 0

    def uri_for(self, remote_url: str) -> str:
        self.generation += 1
        self.streams[self.generation] = remote_url
        for generation in list(self.streams):
            if generation < self.generation - 3:
                self.streams.pop(generation, None)
        return f"http://127.0.0.1:{self.server.server_port}/stream/{self.generation}"


class NativePlayer:
    """Thin GStreamer playbin wrapper kept independent from the GTK widgets."""

    EQ_PRESETS: ClassVar[dict[str, tuple[int, ...]]] = {
        "flat": (0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        "bass": (6, 5, 3, 1, 0, 0, -1, -1, 0, 0),
        "vocal": (-2, -1, 0, 2, 4, 4, 2, 1, 0, -1),
        "treble": (-2, -1, 0, 0, 1, 2, 3, 4, 5, 6),
    }

    def __init__(self, on_state=None, on_error=None, on_eos=None):
        Gst.init(None)
        self._playbin = Gst.ElementFactory.make("playbin", "harmonia-player")
        if self._playbin is None:
            raise RuntimeError(_("O elemento GStreamer playbin não está disponível"))
        self._audio_elements: dict[str, Gst.Element] = {}
        self._install_audio_filter()
        self.on_state = on_state
        self.on_error = on_error
        self.on_eos = on_eos
        self._last_position_us = 0
        self._relay = _StreamRelay()
        bus = self._playbin.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)

    def _install_audio_filter(self) -> None:
        """Attach one reusable native processing graph to playbin."""
        factories = (
            ("convert-in", "audioconvert"),
            ("pitch", "pitch"),
            ("equalizer", "equalizer-10bands"),
            ("replaygain", "rgvolume"),
            ("convert-mid", "audioconvert"),
            ("silence", "removesilence"),
            ("convert-out", "audioconvert"),
        )
        elements: list[Gst.Element] = []
        audio_filter = Gst.Bin.new("harmonia-audio-filter")
        for key, factory in factories:
            element = Gst.ElementFactory.make(factory, f"harmonia-{key}")
            if element is None:
                return
            audio_filter.add(element)
            self._audio_elements[key] = element
            elements.append(element)
        for previous, following in pairwise(elements):
            if not previous.link(following):
                self._audio_elements.clear()
                return
        audio_filter.add_pad(Gst.GhostPad.new("sink", elements[0].get_static_pad("sink")))
        audio_filter.add_pad(Gst.GhostPad.new("src", elements[-1].get_static_pad("src")))
        self._playbin.set_property("audio-filter", audio_filter)
        self.apply_audio_settings()

    def apply_audio_settings(
        self,
        *,
        normalization: bool = False,
        equalizer: str = "flat",
        speed: float = 1.0,
        pitch: float = 0.0,
        skip_silence: bool = False,
    ) -> None:
        """Apply processing atomically; safe when optional plugins are absent."""
        pitch_filter = self._audio_elements.get("pitch")
        if pitch_filter:
            pitch_filter.set_property("tempo", max(0.5, min(2.0, speed)))
            pitch_filter.set_property("pitch", 2 ** (max(-12, min(12, pitch)) / 12))
        equalizer_filter = self._audio_elements.get("equalizer")
        if equalizer_filter:
            bands = self.EQ_PRESETS.get(equalizer, self.EQ_PRESETS["flat"])
            for index, gain in enumerate(bands):
                equalizer_filter.set_property(f"band{index}", float(gain))
        replaygain = self._audio_elements.get("replaygain")
        if replaygain:
            replaygain.set_property("album-mode", False)
            replaygain.set_property("fallback-gain", -6.0 if normalization else 0.0)
            replaygain.set_property("headroom", 1.0 if normalization else 0.0)
        silence = self._audio_elements.get("silence")
        if silence:
            silence.set_property("remove", skip_silence)
            silence.set_property("squash", skip_silence)
            silence.set_property("minimum-silence-time", 1_500_000_000 if skip_silence else 0)

    def play(self, uri: str) -> None:
        self._playbin.set_state(Gst.State.NULL)
        self._last_position_us = 0
        self._playbin.set_property("uri", self._source_uri(uri))
        self._playbin.set_state(Gst.State.PLAYING)

    def _source_uri(self, uri: str) -> str:
        scheme = urllib.parse.urlsplit(uri).scheme
        if scheme == "file" or (scheme == "http" and "googlevideo.com" not in uri):
            return uri
        return self._relay.uri_for(uri)

    def toggle(self) -> None:
        _result, state, _pending = self._playbin.get_state(0)
        self._playbin.set_state(
            Gst.State.PAUSED if state == Gst.State.PLAYING else Gst.State.PLAYING
        )

    def stop(self) -> None:
        self._playbin.set_state(Gst.State.NULL)
        self._last_position_us = 0

    @property
    def volume(self) -> float:
        return float(self._playbin.get_property("volume"))

    @volume.setter
    def volume(self, value: float) -> None:
        self._playbin.set_property("volume", max(0.0, min(1.0, value)))

    @property
    def playing(self) -> bool:
        _result, state, _pending = self._playbin.get_state(0)
        return state == Gst.State.PLAYING

    @property
    def position_us(self) -> int:
        ok, value = self._playbin.query_position(Gst.Format.TIME)
        if ok:
            self._last_position_us = int(value // 1000)
        return self._last_position_us

    @property
    def duration_us(self) -> int:
        ok, value = self._playbin.query_duration(Gst.Format.TIME)
        return int(value // 1000) if ok else 0

    def seek(self, position_us: int) -> bool:
        target = max(0, position_us)
        accepted = self._playbin.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
            target * 1000,
        )
        if accepted:
            self._last_position_us = target
        return accepted

    def _on_message(self, _bus, message) -> None:
        if message.type == Gst.MessageType.ERROR:
            error, _debug = message.parse_error()
            if self.on_error:
                GLib.idle_add(self.on_error, str(error))
        elif message.type == Gst.MessageType.EOS:
            position, duration = self.position_us, self.duration_us
            self.stop()
            if duration > 0 and position + 2_000_000 < duration:
                if self.on_error:
                    GLib.idle_add(
                        self.on_error,
                        _(
                            "O fluxo de áudio terminou antes do esperado "
                            "({position}s de {duration}s)"
                        ).format(
                            position=position // 1_000_000,
                            duration=duration // 1_000_000,
                        ),
                    )
            elif self.on_eos:
                GLib.idle_add(self.on_eos)
        elif message.type == Gst.MessageType.STATE_CHANGED and message.src == self._playbin:
            _old, new, _pending = message.parse_state_changed()
            if self.on_state:
                GLib.idle_add(self.on_state, new == Gst.State.PLAYING)
