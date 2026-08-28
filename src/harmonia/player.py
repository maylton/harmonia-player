from __future__ import annotations

import html
import logging
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

LOGGER = logging.getLogger(__name__)


class _StreamRelay:
    """Local range relay for Googlevideo URLs.

    Googlevideo currently rejects the open-ended Range requests emitted by
    GStreamer's souphttpsrc. urllib works correctly with bounded ranges, so the
    relay translates those requests in 1 MiB chunks while remaining localhost-only.

    For indexed adaptive MP4 video the relay can additionally expose a tiny
    local MPEG-DASH SegmentBase manifest. This lets GStreamer's DASH demuxer use
    the MP4 ``sidx`` index for time-based seeking instead of treating the remote
    fragmented MP4 as one sequential HTTP resource.
    """

    CHUNK_SIZE = 1024 * 1024
    INDEX_PROBE_SIZE = 4 * 1024 * 1024

    def __init__(self):
        self.streams: dict[int, tuple[str, dict[str, str]]] = {}
        self.manifests: dict[int, bytes] = {}
        relay = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _generation(self) -> int | None:
                path = urllib.parse.urlsplit(self.path).path
                try:
                    return int(path.rstrip("/").rsplit("/", 1)[-1])
                except ValueError:
                    return None

            def _remote(self) -> tuple[str, dict[str, str]] | None:
                generation = self._generation()
                return relay.streams.get(generation) if generation is not None else None

            @staticmethod
            def _range(value: str | None) -> tuple[int, int | None, bool]:
                if not value:
                    return 0, None, False
                match = re.fullmatch(r"bytes=(\d+)-(\d*)", value.strip())
                if not match:
                    raise ValueError(_("Intervalo HTTP inválido"))
                return int(match.group(1)), int(match.group(2)) if match.group(2) else None, True

            @staticmethod
            def _upstream(
                remote: str,
                start: int,
                end: int,
                headers: dict[str, str],
            ):
                request_headers = dict(headers)
                request_headers["Range"] = f"bytes={start}-{end}"
                request = urllib.request.Request(
                    remote,
                    headers=request_headers,
                    method="GET",
                )
                return urllib.request.urlopen(request, timeout=30)

            def _serve_stream(self, send_body: bool):
                stream = self._remote()
                if not stream:
                    self.send_error(404)
                    return
                remote, request_headers = stream
                headers_sent = False
                try:
                    start, requested_end, partial = self._range(self.headers.get("Range"))
                    first_end = start + relay.CHUNK_SIZE - 1
                    if requested_end is not None:
                        first_end = min(first_end, requested_end)
                    with self._upstream(remote, start, first_end, request_headers) as first:
                        content_range = first.headers.get("Content-Range", "")
                        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
                        if not match:
                            raise OSError(_("O servidor de mídia não informou o tamanho total"))
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
                            "Content-Type",
                            first.headers.get("Content-Type", "application/octet-stream"),
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
                            with self._upstream(
                                remote,
                                cursor,
                                chunk_end,
                                request_headers,
                            ) as response:
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

            def _serve_manifest(self, send_body: bool):
                generation = self._generation()
                payload = relay.manifests.get(generation) if generation is not None else None
                if payload is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/dash+xml")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                if send_body:
                    with suppress(BrokenPipeError, ConnectionError):
                        self.wfile.write(payload)
                self.close_connection = True

            def do_GET(self):
                path = urllib.parse.urlsplit(self.path).path
                if path.startswith("/manifest/"):
                    self._serve_manifest(True)
                else:
                    self._serve_stream(True)

            def do_HEAD(self):
                path = urllib.parse.urlsplit(self.path).path
                if path.startswith("/manifest/"):
                    self._serve_manifest(False)
                else:
                    self._serve_stream(False)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(
            target=self.server.serve_forever, daemon=True, name="harmonia-stream-relay"
        ).start()
        self.generation = 0

    def _register(self, remote_url: str, headers: dict[str, str] | None = None) -> int:
        self.generation += 1
        generation = self.generation
        self.streams[generation] = (remote_url, dict(headers or {}))
        for old_generation in list(self.streams):
            if old_generation < generation - 3:
                self.streams.pop(old_generation, None)
                self.manifests.pop(old_generation, None)
        return generation

    @staticmethod
    def _locate_mp4_segment_base(data: bytes) -> tuple[tuple[int, int], tuple[int, int]] | None:
        """Return init/index byte ranges for a top-level MP4 ``sidx`` box."""
        cursor = 0
        size_data = len(data)
        while cursor + 8 <= size_data:
            box_size = int.from_bytes(data[cursor : cursor + 4], "big")
            box_type = data[cursor + 4 : cursor + 8]
            header_size = 8
            if box_size == 1:
                if cursor + 16 > size_data:
                    return None
                box_size = int.from_bytes(data[cursor + 8 : cursor + 16], "big")
                header_size = 16
            elif box_size == 0:
                return None
            if box_size < header_size:
                return None
            box_end = cursor + box_size
            if box_type == b"sidx":
                if box_end > size_data or cursor <= 0:
                    return None
                return (0, cursor - 1), (cursor, box_end - 1)
            if box_end > size_data:
                return None
            cursor = box_end
        return None

    @classmethod
    def _probe_mp4_segment_base(
        cls,
        remote_url: str,
        headers: dict[str, str] | None,
    ) -> tuple[tuple[int, int], tuple[int, int]] | None:
        request_headers = dict(headers or {})
        request_headers["Range"] = f"bytes=0-{cls.INDEX_PROBE_SIZE - 1}"
        request = urllib.request.Request(remote_url, headers=request_headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = response.read(cls.INDEX_PROBE_SIZE)
        except Exception:
            LOGGER.debug("Could not probe MP4 SegmentBase", exc_info=True)
            return None
        return cls._locate_mp4_segment_base(data)

    def uri_for(self, remote_url: str, headers: dict[str, str] | None = None) -> str:
        generation = self._register(remote_url, headers)
        return f"http://127.0.0.1:{self.server.server_port}/stream/{generation}"

    def dash_uri_for(
        self,
        remote_url: str,
        headers: dict[str, str] | None = None,
    ) -> str | None:
        """Expose an indexed adaptive MP4 as a local DASH SegmentBase asset."""
        values = urllib.parse.parse_qs(urllib.parse.urlsplit(remote_url).query)
        mime_type = str((values.get("mime") or [""])[0]).lower()
        gir = str((values.get("gir") or [""])[0]).lower()
        if mime_type != "video/mp4" or gir != "yes":
            return None

        ranges = self._probe_mp4_segment_base(remote_url, headers)
        if ranges is None:
            return None
        init_range, index_range = ranges

        try:
            duration = float((values.get("dur") or ["0"])[0])
        except (TypeError, ValueError):
            duration = 0.0
        if duration <= 0:
            return None

        try:
            content_length = int((values.get("clen") or ["0"])[0])
        except (TypeError, ValueError):
            content_length = 0
        bandwidth = max(1, int(content_length * 8 / duration)) if content_length else 1
        representation_id = html.escape(str((values.get("itag") or ["video"])[0]), quote=True)

        generation = self._register(remote_url, headers)
        media_uri = f"http://127.0.0.1:{self.server.server_port}/stream/{generation}"
        escaped_media_uri = html.escape(media_uri, quote=True)
        duration_text = f"{duration:.3f}"
        manifest = f"""<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"
     type="static"
     profiles="urn:mpeg:dash:profile:isoff-on-demand:2011"
     minBufferTime="PT1.5S"
     mediaPresentationDuration="PT{duration_text}S">
  <Period start="PT0S" duration="PT{duration_text}S">
    <AdaptationSet mimeType="video/mp4" segmentAlignment="true" startWithSAP="1">
      <Representation id="{representation_id}" bandwidth="{bandwidth}">
        <BaseURL>{escaped_media_uri}</BaseURL>
        <SegmentBase indexRange="{index_range[0]}-{index_range[1]}" indexRangeExact="true">
          <Initialization range="{init_range[0]}-{init_range[1]}" />
        </SegmentBase>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>
""".encode()
        self.manifests[generation] = manifest
        LOGGER.info(
            "Using local DASH SegmentBase for YouTube video: init=%d-%d index=%d-%d",
            init_range[0],
            init_range[1],
            index_range[0],
            index_range[1],
        )
        return f"http://127.0.0.1:{self.server.server_port}/manifest/{generation}.mpd"

    def close(self) -> None:
        self.streams.clear()
        self.manifests.clear()
        self.server.shutdown()
        self.server.server_close()


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
        self._video_sink: Gst.Element | None = None
        self._replace_generation = 0
        self._install_audio_filter()
        self.on_state = on_state
        self.on_error = on_error
        self.on_eos = on_eos
        self._last_position_us = 0
        self._relay = _StreamRelay()
        self._bus = self._playbin.get_bus()
        self._bus.add_signal_watch()
        self._bus.connect("message", self._on_message)

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

    def set_video_sink(self, sink: Gst.Element | None) -> None:
        """Attach a toolkit-owned video sink to the shared playbin."""
        self._video_sink = sink
        self._playbin.set_property("video-sink", sink)

    @property
    def video_sink(self) -> Gst.Element | None:
        return self._video_sink

    def play(self, uri: str) -> None:
        self._replace_generation += 1
        self._playbin.set_state(Gst.State.NULL)
        self._last_position_us = 0
        self._playbin.set_property("uri", self._source_uri(uri))
        self._playbin.set_state(Gst.State.PLAYING)

    def replace(
        self,
        uri: str,
        position_us: int = 0,
        playing: bool | None = None,
        request_headers: dict[str, str] | None = None,
    ) -> None:
        """Replace only the media source while preserving transport state/position.

        This is intentionally separate from :meth:`play`: callers use it for
        Music <-> Video switching inside the same logical track, so queue,
        MPRIS, history and scrobble generation stay untouched.
        """
        should_play = self.playing if playing is None else bool(playing)
        target = max(0, int(position_us))
        self._replace_generation += 1
        generation = self._replace_generation
        self._playbin.set_state(Gst.State.NULL)
        self._last_position_us = target
        self._playbin.set_property("uri", self._source_uri(uri, request_headers))
        # Preroll paused first; seeking before preroll is unreliable for remote
        # MP4 streams and can briefly play from 0 before the requested position.
        self._playbin.set_state(Gst.State.PAUSED)
        GLib.timeout_add(40, self._finish_replace, generation, target, should_play, 0)

    def _finish_replace(
        self,
        generation: int,
        target: int,
        should_play: bool,
        attempt: int,
    ) -> bool:
        if generation != self._replace_generation:
            return GLib.SOURCE_REMOVE
        _result, state, _pending = self._playbin.get_state(0)
        ready = state in (Gst.State.PAUSED, Gst.State.PLAYING)
        if not ready and attempt < 50:
            GLib.timeout_add(40, self._finish_replace, generation, target, should_play, attempt + 1)
            return GLib.SOURCE_REMOVE
        if target:
            self.seek(target)
        self._playbin.set_state(Gst.State.PLAYING if should_play else Gst.State.PAUSED)
        return GLib.SOURCE_REMOVE

    def _source_uri(
        self,
        uri: str,
        request_headers: dict[str, str] | None = None,
    ) -> str:
        scheme = urllib.parse.urlsplit(uri).scheme
        if scheme == "file" or (scheme == "http" and "googlevideo.com" not in uri):
            return uri
        dash_uri = self._relay.dash_uri_for(uri, request_headers)
        if dash_uri is not None:
            return dash_uri
        return self._relay.uri_for(uri, request_headers)

    def toggle(self) -> None:
        _result, state, _pending = self._playbin.get_state(0)
        self._playbin.set_state(
            Gst.State.PAUSED if state == Gst.State.PLAYING else Gst.State.PLAYING
        )

    def stop(self) -> None:
        self._replace_generation += 1
        self._playbin.set_state(Gst.State.NULL)
        self._last_position_us = 0

    def close(self) -> None:
        self.stop()
        self._bus.remove_signal_watch()
        self._relay.close()

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
            error, debug = message.parse_error()
            try:
                source = message.src.get_path_string() if message.src is not None else "unknown"
            except Exception:
                source = "unknown"
            LOGGER.error(
                "GStreamer playback error from %s: %s (%s)",
                source,
                error,
                debug or "sem debug",
            )
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
