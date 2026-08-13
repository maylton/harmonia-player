from __future__ import annotations

import hashlib
import json
import os
import socket
import struct
import time
import urllib.parse
import urllib.request
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from .i18n import _
from .models import LibraryItem
from .secrets import NamedSecret


class LastFmError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LastFmSession:
    username: str
    key: str


@dataclass(frozen=True, slots=True)
class LastFmCredentials:
    api_secret: str = ""
    session: LastFmSession | None = None


class LastFmCredentialStore:
    """Keep Last.fm write credentials out of the portable SQLite backup."""

    def __init__(self, storage) -> None:
        self._secret = NamedSecret("lastfm", "Conta Last.fm — Harmonia")
        self._fallback = storage.cookie_file.parent / "lastfm-credentials"

    def load(self) -> LastFmCredentials:
        payload = self._secret.lookup()
        if not payload:
            try:
                payload = self._fallback.read_text()
            except OSError:
                return LastFmCredentials()
        try:
            data = json.loads(payload)
            session = None
            if data.get("session_key"):
                session = LastFmSession(str(data.get("username", "")), data["session_key"])
            return LastFmCredentials(str(data.get("api_secret", "")), session)
        except (TypeError, ValueError, KeyError):
            return LastFmCredentials()

    def save(self, credentials: LastFmCredentials) -> None:
        payload = json.dumps(
            {
                "api_secret": credentials.api_secret,
                "username": credentials.session.username if credentials.session else "",
                "session_key": credentials.session.key if credentials.session else "",
            }
        )
        if self._secret.store(payload):
            self._fallback.unlink(missing_ok=True)
            return
        self._fallback.write_text(payload)
        self._fallback.chmod(0o600)

    def clear_session(self) -> None:
        credentials = self.load()
        if credentials.api_secret:
            self.save(LastFmCredentials(credentials.api_secret))
        else:
            self.clear()

    def clear(self) -> None:
        self._secret.clear()
        self._fallback.unlink(missing_ok=True)


class LastFmClient:
    API_URL = "https://ws.audioscrobbler.com/2.0/"
    AUTH_URL = "https://www.last.fm/api/auth/"

    def __init__(self, api_key: str, api_secret: str, session_key: str = "", opener=None):
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.session_key = session_key.strip()
        self._opener = opener or urllib.request.urlopen

    def _signature(self, parameters: dict[str, str]) -> str:
        source = "".join(f"{key}{parameters[key]}" for key in sorted(parameters))
        return hashlib.md5(f"{source}{self.api_secret}".encode(), usedforsecurity=False).hexdigest()

    def _call(self, method: str, *, authenticated: bool = False, **values) -> dict:
        if not self.api_key or not self.api_secret:
            raise LastFmError(_("A chave e o segredo da API do Last.fm são obrigatórios"))
        parameters = {"api_key": self.api_key, "method": method}
        parameters.update(
            {key: str(value) for key, value in values.items() if value not in (None, "")}
        )
        if authenticated:
            if not self.session_key:
                raise LastFmError(_("A conta do Last.fm ainda não foi autorizada"))
            parameters["sk"] = self.session_key
        parameters["api_sig"] = self._signature(parameters)
        parameters["format"] = "json"
        request = urllib.request.Request(
            self.API_URL,
            data=urllib.parse.urlencode(parameters).encode(),
            headers={"User-Agent": "Harmonia/0.1 (Linux music player)"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=15) as response:
                payload = json.loads(response.read().decode())
        except (OSError, ValueError) as exc:
            raise LastFmError(_("Falha ao acessar o Last.fm: {error}").format(error=exc)) from exc
        if "error" in payload:
            raise LastFmError(str(payload.get("message") or f"Erro {payload['error']} do Last.fm"))
        return payload

    def request_token(self) -> str:
        token = str(self._call("auth.getToken").get("token", ""))
        if not token:
            raise LastFmError(_("O Last.fm não retornou um token de autorização"))
        return token

    def authorization_url(self, token: str) -> str:
        return (
            f"{self.AUTH_URL}?{urllib.parse.urlencode({'api_key': self.api_key, 'token': token})}"
        )

    def create_session(self, token: str) -> LastFmSession:
        data = self._call("auth.getSession", token=token).get("session") or {}
        session = LastFmSession(str(data.get("name", "")), str(data.get("key", "")))
        if not session.username or not session.key:
            raise LastFmError(_("O Last.fm não retornou uma sessão válida"))
        return session

    def update_now_playing(self, item: LibraryItem, duration_ms: int = 0) -> None:
        self._call(
            "track.updateNowPlaying",
            authenticated=True,
            artist=media_artist(item),
            track=item.title,
            duration=duration_ms // 1000 if duration_ms else None,
        )

    def scrobble(self, item: LibraryItem, started_at: int, duration_ms: int = 0) -> None:
        self._call(
            "track.scrobble",
            authenticated=True,
            artist=media_artist(item),
            track=item.title,
            timestamp=started_at,
            duration=duration_ms // 1000 if duration_ms else None,
        )


def media_artist(item: LibraryItem) -> str:
    parts = [part.strip() for part in item.subtitle.replace("·", "•").split("•") if part.strip()]
    media_labels = {"música", "music", "vídeo", "video", "álbum", "album", "ep"}
    if parts and parts[0].casefold() in media_labels and len(parts) > 1:
        return parts[1]
    return parts[0] if parts else "YouTube Music"


class DiscordPresence:
    """Minimal Discord IPC client; no remote Discord API or background service."""

    def __init__(self, client_id: str, socket_factory=socket.socket) -> None:
        self.client_id = client_id.strip()
        self._socket_factory = socket_factory
        self._socket = None

    @staticmethod
    def candidate_paths() -> list[Path]:
        roots = [
            Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")),
            Path(os.environ.get("TMPDIR", "/tmp")),
        ]
        candidates: list[Path] = []
        for root in roots:
            for index in range(10):
                candidates.append(root / f"discord-ipc-{index}")
                candidates.append(root / "app/com.discordapp.Discord" / f"discord-ipc-{index}")
        return candidates

    @staticmethod
    def _frame(operation: int, payload: dict) -> bytes:
        body = json.dumps(payload, separators=(",", ":")).encode()
        return struct.pack("<II", operation, len(body)) + body

    def _read_exact(self, length: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < length:
            chunk = self._socket.recv(length - len(chunks))
            if not chunk:
                raise OSError("Discord fechou o socket IPC")
            chunks.extend(chunk)
        return bytes(chunks)

    def _receive(self) -> dict:
        _operation, length = struct.unpack("<II", self._read_exact(8))
        return json.loads(self._read_exact(length))

    def connect(self) -> None:
        if self._socket is not None:
            return
        if not self.client_id:
            raise OSError("O Client ID do Discord não foi configurado")
        last_error = None
        for path in self.candidate_paths():
            candidate = self._socket_factory(socket.AF_UNIX, socket.SOCK_STREAM)
            candidate.settimeout(1.5)
            try:
                candidate.connect(str(path))
                self._socket = candidate
                candidate.sendall(self._frame(0, {"v": 1, "client_id": self.client_id}))
                response = self._receive()
                if response.get("evt") == "ERROR":
                    raise OSError(response.get("data", {}).get("message", "Falha no Discord IPC"))
                return
            except OSError as exc:
                last_error = exc
                candidate.close()
                self._socket = None
        raise OSError(f"Discord não encontrado: {last_error or 'socket IPC indisponível'}")

    def _command(self, activity: dict | None) -> None:
        self.connect()
        payload = {
            "cmd": "SET_ACTIVITY",
            "args": {"pid": os.getpid(), "activity": activity},
            "nonce": str(uuid.uuid4()),
        }
        try:
            self._socket.sendall(self._frame(1, payload))
            response = self._receive()
            if response.get("evt") == "ERROR":
                raise OSError(response.get("data", {}).get("message", "Falha no Discord IPC"))
        except OSError:
            self.close()
            raise

    def update(self, item: LibraryItem, playing: bool, started_at: int = 0) -> None:
        activity = {
            "details": item.title,
            "state": media_artist(item),
            "instance": False,
        }
        if playing and started_at:
            activity["timestamps"] = {"start": started_at}
        if not playing:
            activity["state"] = f"Pausado · {activity['state']}"
        self._command(activity)

    def clear(self) -> None:
        if self._socket is not None:
            with suppress(OSError):
                self._command(None)

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None


def scrobble_ready(duration_ms: int, position_ms: int) -> bool:
    if duration_ms <= 30_000:
        return False
    return position_ms >= min(duration_ms // 2, 240_000)


def playback_started_at(position_ms: int = 0) -> int:
    return int(time.time()) - max(0, position_ms // 1000)
