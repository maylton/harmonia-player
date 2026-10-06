from __future__ import annotations

import html
import mimetypes
import secrets
import socket
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .together import local_address

MEDIA_RENDERER = "urn:schemas-upnp-org:device:MediaRenderer:1"
AVTRANSPORT = "urn:schemas-upnp-org:service:AVTransport:1"


MAX_DESCRIPTION_BYTES = 512 * 1024


def parse_byte_range(header: str, size: int) -> tuple[int, int] | None:
    """Parse a single HTTP Range header; None means the whole file.

    Malformed ranges yield an unsatisfiable (start > end) range, answered 416.
    """
    if not header.startswith("bytes="):
        return None
    first, separator, last = header[6:].split(",", 1)[0].strip().partition("-")
    try:
        if not separator:
            raise ValueError
        if not first:  # suffix range: the last N bytes
            length = int(last)
            return (max(0, size - length), size - 1) if length > 0 else (size, size - 1)
        start = int(first)
        end = min(size - 1, int(last)) if last else size - 1
    except ValueError:
        return (size, size - 1)
    return start, end


class LocalMediaServer:
    """Expose one local audio file to a renderer on the LAN, with byte ranges."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.content_type = mimetypes.guess_type(self.path.name)[0] or "application/octet-stream"
        # The server listens on the LAN so a renderer can fetch the file; a
        # random path keeps other devices from reading it.
        self.token = secrets.token_urlsafe(16)
        media = self

        class Handler(BaseHTTPRequestHandler):
            def _serve(self, body: bool) -> None:
                if self.path.split("?", 1)[0] != f"/audio/{media.token}":
                    self.send_error(404)
                    return
                size = media.path.stat().st_size
                byte_range = parse_byte_range(self.headers.get("Range", ""), size)
                partial = byte_range is not None
                start, end = byte_range or (0, size - 1)
                if start < 0 or start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                self.send_response(206 if partial else 200)
                self.send_header("Content-Type", media.content_type)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(end - start + 1))
                if partial:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.end_headers()
                if not body:
                    return
                with media.path.open("rb") as source:
                    source.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        chunk = source.read(min(64 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)

            def do_GET(self):
                self._serve(True)

            def do_HEAD(self):
                self._serve(False)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True, name="cast-media").start()

    @classmethod
    def from_uri(cls, uri: str) -> LocalMediaServer:
        parsed = urllib.parse.urlsplit(uri)
        if parsed.scheme != "file":
            raise ValueError("A URI não aponta para um arquivo local")
        # url2pathname also turns Windows' "/C:/Music/a.m4a" into "C:\Music\a.m4a".
        return cls(Path(urllib.request.url2pathname(parsed.path)))

    @property
    def url(self) -> str:
        return f"http://{local_address()}:{self.server.server_port}/audio/{self.token}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class CastMediaHost:
    """Make the current track reachable by a renderer on the LAN.

    Remote streams are handed to the renderer as they are; local files
    (downloads and the local library) are served by a LocalMediaServer, one at
    a time, which is replaced on every track and closed when casting ends.
    """

    def __init__(self) -> None:
        self._server: LocalMediaServer | None = None

    def uri_for(self, uri: str) -> str:
        """Return a URI the renderer can fetch; raises OSError or ValueError."""
        self.close()
        if uri.startswith("file:"):
            self._server = LocalMediaServer.from_uri(uri)
            return self._server.url
        return uri

    def close(self) -> None:
        if self._server:
            self._server.close()
            self._server = None


@dataclass(frozen=True, slots=True)
class CastDevice:
    name: str
    location: str
    control_url: str


class UpnpDiscovery:
    def __init__(self, socket_factory=socket.socket, opener=None) -> None:
        self._socket_factory = socket_factory
        self._opener = opener or urllib.request.urlopen

    def discover(self, timeout: float = 2.0) -> list[CastDevice]:
        message = "\r\n".join(
            (
                "M-SEARCH * HTTP/1.1",
                "HOST: 239.255.255.250:1900",
                'MAN: "ssdp:discover"',
                "MX: 2",
                f"ST: {MEDIA_RENDERER}",
                "",
                "",
            )
        ).encode()
        client = self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        client.settimeout(0.25)
        client.sendto(message, ("239.255.255.250", 1900))
        locations: set[str] = set()
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                try:
                    payload, _address = client.recvfrom(64 * 1024)
                except TimeoutError:
                    continue
                headers = self._headers(payload.decode(errors="replace"))
                if headers.get("location"):
                    locations.add(headers["location"])
        finally:
            client.close()
        devices = []
        for location in sorted(locations):
            try:
                device = self._device(location)
                if device:
                    devices.append(device)
            except (OSError, ET.ParseError):
                continue
        return devices

    @staticmethod
    def _headers(payload: str) -> dict[str, str]:
        headers = {}
        for line in payload.replace("\r\n", "\n").split("\n")[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        return headers

    def _device(self, location: str) -> CastDevice | None:
        # Any device on the network can answer discovery, so bound the read and
        # refuse DTDs/entities (entity expansion bombs) before parsing.
        with self._opener(location, timeout=4) as response:
            data = response.read(MAX_DESCRIPTION_BYTES + 1)
        if len(data) > MAX_DESCRIPTION_BYTES or b"<!DOCTYPE" in data or b"<!ENTITY" in data:
            return None
        root = ET.fromstring(data)
        name = next((node.text for node in root.iter() if node.tag.endswith("friendlyName")), None)
        for service in root.iter():
            if not service.tag.endswith("service"):
                continue
            values = {child.tag.rsplit("}", 1)[-1]: child.text or "" for child in service}
            if values.get("serviceType", "").startswith(AVTRANSPORT):
                return CastDevice(
                    name or urllib.parse.urlsplit(location).hostname or "Media Renderer",
                    location,
                    urllib.parse.urljoin(location, values["controlURL"]),
                )
        return None


class UpnpRenderer:
    def __init__(self, device: CastDevice, opener=None) -> None:
        self.device = device
        self._opener = opener or urllib.request.urlopen

    def _action(self, action: str, arguments: dict[str, str] | None = None) -> None:
        arguments = arguments or {}
        values = "".join(
            f"<{key}>{html.escape(str(value))}</{key}>" for key, value in arguments.items()
        )
        envelope = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            f'<s:Body><u:{action} xmlns:u="{AVTRANSPORT}">{values}</u:{action}></s:Body>'
            "</s:Envelope>"
        ).encode()
        request = urllib.request.Request(
            self.device.control_url,
            data=envelope,
            headers={
                "Content-Type": 'text/xml; charset="utf-8"',
                "SOAPAction": f'"{AVTRANSPORT}#{action}"',
            },
            method="POST",
        )
        with self._opener(request, timeout=6) as response:
            response.read()

    def play_uri(self, uri: str, title: str) -> None:
        content_type = mimetypes.guess_type(urllib.parse.urlsplit(uri).path)[0] or "audio/mp4"
        metadata = (
            '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
            f'<item id="0" parentID="0" restricted="1"><dc:title>{html.escape(title)}</dc:title>'
            "<upnp:class>object.item.audioItem.musicTrack</upnp:class>"
            f'<res protocolInfo="http-get:*:{content_type}:*">{html.escape(uri)}</res>'
            "</item></DIDL-Lite>"
        )
        self._action(
            "SetAVTransportURI",
            {"InstanceID": "0", "CurrentURI": uri, "CurrentURIMetaData": metadata},
        )
        self.play()

    def play(self) -> None:
        self._action("Play", {"InstanceID": "0", "Speed": "1"})

    def pause(self) -> None:
        self._action("Pause", {"InstanceID": "0"})

    def stop(self) -> None:
        self._action("Stop", {"InstanceID": "0"})

    def seek(self, position_ms: int) -> None:
        seconds = max(0, position_ms // 1000)
        target = f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"
        self._action(
            "Seek",
            {"InstanceID": "0", "Unit": "REL_TIME", "Target": target},
        )
