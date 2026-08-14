from __future__ import annotations

import json
import mimetypes
import tempfile
import time
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

from .i18n import _
from .secrets import NamedSecret


@dataclass(frozen=True, slots=True)
class RecognitionResult:
    title: str
    artist: str
    album: str = ""
    link: str = ""


class RecognitionTokenStore:
    def __init__(self, storage) -> None:
        self._secret = NamedSecret("recognition", "Reconhecimento de música — Harmonia")
        self._fallback = storage.cookie_file.parent / "recognition-token"

    def load(self) -> str:
        value = self._secret.lookup()
        if value:
            return value
        try:
            return self._fallback.read_text().strip()
        except OSError:
            return ""

    def save(self, value: str) -> None:
        value = value.strip()
        if not value:
            return
        if self._secret.store(value):
            self._fallback.unlink(missing_ok=True)
            return
        self._fallback.write_text(value)
        self._fallback.chmod(0o600)

    def clear(self) -> None:
        self._secret.clear()
        self._fallback.unlink(missing_ok=True)


class GStreamerRecorder:
    def capture(self, output: Path, seconds: int = 12) -> Path:
        Gst.init(None)
        location = str(output).replace("\\", "\\\\").replace('"', '\\"')
        pipeline = Gst.parse_launch(
            "pulsesrc ! audioconvert ! audioresample ! "
            f'audio/x-raw,rate=44100,channels=1 ! wavenc ! filesink location="{location}"'
        )
        pipeline.set_state(Gst.State.PLAYING)
        try:
            time.sleep(max(1, seconds))
            pipeline.send_event(Gst.Event.new_eos())
            message = pipeline.get_bus().timed_pop_filtered(
                5 * Gst.SECOND,
                Gst.MessageType.EOS | Gst.MessageType.ERROR,
            )
            if message is None:
                raise RuntimeError(_("A captura de áudio não terminou a tempo"))
            if message.type == Gst.MessageType.ERROR:
                error, _debug = message.parse_error()
                raise RuntimeError(str(error))
        finally:
            pipeline.set_state(Gst.State.NULL)
        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError(_("Nenhum áudio foi capturado"))
        return output


class AuddRecognitionProvider:
    endpoint = "https://api.audd.io/"

    def __init__(self, token: str, opener=None, endpoint: str | None = None) -> None:
        self.token = token.strip()
        self._opener = opener or urllib.request.urlopen
        self.endpoint = (endpoint or self.endpoint).strip()

    def recognize(self, audio: Path) -> RecognitionResult | None:
        if not self.token:
            raise RuntimeError(_("Configure o token do AudD nas Preferências"))
        boundary = f"----harmonia-{uuid.uuid4().hex}"
        mime = mimetypes.guess_type(audio.name)[0] or "audio/wav"
        body = bytearray()
        for name, value in (("api_token", self.token), ("return", "apple_music,spotify")):
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            body.extend(value.encode())
            body.extend(b"\r\n")
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="file"; filename="{audio.name}"\r\n'.encode()
        )
        body.extend(f"Content-Type: {mime}\r\n\r\n".encode())
        body.extend(audio.read_bytes())
        body.extend(f"\r\n--{boundary}--\r\n".encode())
        request = urllib.request.Request(
            self.endpoint,
            data=bytes(body),
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "Harmonia/0.1",
            },
            method="POST",
        )
        with self._opener(request, timeout=30) as response:
            payload = json.loads(response.read())
        if payload.get("status") != "success":
            error = payload.get("error", {}).get("error_message", _("Falha no reconhecimento"))
            raise RuntimeError(error)
        result = payload.get("result")
        if not result:
            return None
        return RecognitionResult(
            str(result.get("title", "")),
            str(result.get("artist", "")),
            str(result.get("album", "")),
            str(result.get("song_link", "")),
        )


class MusicRecognizer:
    def __init__(self, provider: AuddRecognitionProvider, recorder=None) -> None:
        self.provider = provider
        self.recorder = recorder or GStreamerRecorder()

    def recognize(self, seconds: int = 12) -> RecognitionResult | None:
        with tempfile.TemporaryDirectory(prefix="harmonia-recognition-") as directory:
            audio = self.recorder.capture(Path(directory) / "sample.wav", seconds)
            return self.provider.recognize(audio)
