"""Localhost relay that lets GStreamer play and seek Googlevideo streams."""

from __future__ import annotations

import html
import logging
import re
import threading
import urllib.parse
import urllib.request
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .i18n import _

LOGGER = logging.getLogger(__name__)
RangeBounds = tuple[tuple[int, int], tuple[int, int]]


class StreamRelay:
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
        self.generation = 0
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _RelayHandler)
        self.server.relay = self
        threading.Thread(
            target=self.server.serve_forever, daemon=True, name="harmonia-stream-relay"
        ).start()

    def _register(self, remote_url: str, headers: dict[str, str] | None = None) -> int:
        self.generation += 1
        generation = self.generation
        self.streams[generation] = (remote_url, dict(headers or {}))
        for old_generation in list(self.streams):
            if old_generation < generation - 3:
                self.streams.pop(old_generation, None)
                self.manifests.pop(old_generation, None)
        return generation

    def _local_uri(self, kind: str, generation: int) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/{kind}/{generation}"

    @staticmethod
    def _locate_mp4_segment_base(data: bytes) -> RangeBounds | None:
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
    ) -> RangeBounds | None:
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
        return self._local_uri("stream", self._register(remote_url, headers))

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
        representation_id = str((values.get("itag") or ["video"])[0])

        generation = self._register(remote_url, headers)
        self.manifests[generation] = dash_manifest(
            self._local_uri("stream", generation), duration, bandwidth, representation_id, ranges
        )
        init_range, index_range = ranges
        LOGGER.info(
            "Using local DASH SegmentBase for YouTube video: init=%d-%d index=%d-%d",
            init_range[0],
            init_range[1],
            index_range[0],
            index_range[1],
        )
        return self._local_uri("manifest", generation)

    def close(self) -> None:
        self.streams.clear()
        self.manifests.clear()
        self.server.shutdown()
        self.server.server_close()


def dash_manifest(
    media_uri: str,
    duration: float,
    bandwidth: int,
    representation_id: str,
    ranges: RangeBounds,
) -> bytes:
    """A one-representation static MPD pointing at an MP4 with a sidx index."""
    init_range, index_range = ranges
    duration_text = f"{duration:.3f}"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"
     type="static"
     profiles="urn:mpeg:dash:profile:isoff-on-demand:2011"
     minBufferTime="PT1.5S"
     mediaPresentationDuration="PT{duration_text}S">
  <Period start="PT0S" duration="PT{duration_text}S">
    <AdaptationSet mimeType="video/mp4" segmentAlignment="true" startWithSAP="1">
      <Representation id="{html.escape(representation_id, quote=True)}" bandwidth="{bandwidth}">
        <BaseURL>{html.escape(media_uri, quote=True)}</BaseURL>
        <SegmentBase indexRange="{index_range[0]}-{index_range[1]}" indexRangeExact="true">
          <Initialization range="{init_range[0]}-{init_range[1]}" />
        </SegmentBase>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>
""".encode()


def _upstream(remote: str, start: int, end: int, headers: dict[str, str]):
    request_headers = dict(headers)
    request_headers["Range"] = f"bytes={start}-{end}"
    request = urllib.request.Request(remote, headers=request_headers, method="GET")
    return urllib.request.urlopen(request, timeout=30)


def _requested_range(value: str | None) -> tuple[int, int | None, bool]:
    """(start, end or None, partial) from a client's Range header."""
    if not value:
        return 0, None, False
    match = re.fullmatch(r"bytes=(\d+)-(\d*)", value.strip())
    if not match:
        raise ValueError(_("Intervalo HTTP inválido"))
    return int(match.group(1)), int(match.group(2)) if match.group(2) else None, True


class _RelayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def relay(self) -> StreamRelay:
        return self.server.relay

    def _generation(self) -> int | None:
        path = urllib.parse.urlsplit(self.path).path
        try:
            return int(path.rstrip("/").rsplit("/", 1)[-1])
        except ValueError:
            return None

    def _remote(self) -> tuple[str, dict[str, str]] | None:
        generation = self._generation()
        return self.relay.streams.get(generation) if generation is not None else None

    def _serve_stream(self, send_body: bool):
        stream = self._remote()
        if not stream:
            self.send_error(404)
            return
        remote, request_headers = stream
        headers_sent = False
        try:
            start, requested_end, partial = _requested_range(self.headers.get("Range"))
            first_end = start + self.relay.CHUNK_SIZE - 1
            if requested_end is not None:
                first_end = min(first_end, requested_end)
            with _upstream(remote, start, first_end, request_headers) as first:
                content_range = first.headers.get("Content-Range", "")
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
                if not match:
                    raise OSError(_("O servidor de mídia não informou o tamanho total"))
                total = int(match.group(3))
                if start >= total:
                    self._send_unsatisfiable(total)
                    headers_sent = True
                    return
                end = min(requested_end if requested_end is not None else total - 1, total - 1)
                self._send_stream_headers(first, start, end, total, partial)
                headers_sent = True
                if send_body:
                    self._copy_range(first, remote, request_headers, start, end)
        except (BrokenPipeError, ConnectionError):
            return
        except Exception as exc:
            if not self.wfile.closed and not headers_sent:
                with suppress(BrokenPipeError, ConnectionError):
                    self.send_error(502, str(exc))
        finally:
            self.close_connection = True

    def _send_unsatisfiable(self, total: int) -> None:
        self.send_response(416)
        self.send_header("Content-Range", f"bytes */{total}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_stream_headers(self, first, start: int, end: int, total: int, partial: bool) -> None:
        self.send_response(206 if partial else 200)
        self.send_header(
            "Content-Type", first.headers.get("Content-Type", "application/octet-stream")
        )
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
        self.send_header("Connection", "close")
        self.end_headers()

    def _copy_range(self, first, remote: str, headers: dict[str, str], start: int, end: int):
        """Write bytes start..end: the first upstream chunk, then bounded ones."""
        cursor = start
        while chunk := first.read(64 * 1024):
            self.wfile.write(chunk)
            cursor += len(chunk)
        while cursor <= end:
            chunk_end = min(cursor + self.relay.CHUNK_SIZE - 1, end)
            with _upstream(remote, cursor, chunk_end, headers) as response:
                while chunk := response.read(64 * 1024):
                    self.wfile.write(chunk)
                    cursor += len(chunk)

    def _serve_manifest(self, send_body: bool):
        generation = self._generation()
        payload = self.relay.manifests.get(generation) if generation is not None else None
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

    def _serve(self, send_body: bool) -> None:
        if urllib.parse.urlsplit(self.path).path.startswith("/manifest/"):
            self._serve_manifest(send_body)
        else:
            self._serve_stream(send_body)

    def do_GET(self):
        self._serve(True)

    def do_HEAD(self):
        self._serve(False)

    def log_message(self, *_args):
        pass
