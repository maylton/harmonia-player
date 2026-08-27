from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from .cast import LocalMediaServer, UpnpDiscovery, UpnpRenderer
from .recognition import AuddRecognitionProvider, MusicRecognizer, RecognitionTokenStore
from .social import (
    DiscordPresence,
    LastFmClient,
    LastFmCredentials,
    LastFmCredentialStore,
    LastFmError,
    playback_started_at,
    scrobble_ready,
)
from .together import TogetherClient, TogetherHost, TogetherState

LOGGER = logging.getLogger(__name__)


class QtIntegrationsController(QObject):
    """Qt bridge for the shared social, LAN and recognition services."""

    changed = Signal()
    togetherChanged = Signal()
    castChanged = Signal()
    _operationReady = Signal(str, object, str)

    def __init__(
        self,
        backend,
        executor: ThreadPoolExecutor,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.backend = backend
        self.storage = backend.storage
        self.settings = backend.settings
        self.playback = backend.playback
        self.executor = executor

        self.lastfm_credentials = LastFmCredentialStore(self.storage)
        self._lastfm_pending_token = ""
        self._social_started_at = 0
        self._social_item = None
        self._lastfm_scrobbled = False
        self.discord_presence: DiscordPresence | None = None
        self._discord_config: tuple[bool, str] | None = None

        self.recognition_tokens = RecognitionTokenStore(self.storage)

        self.together_host: TogetherHost | None = None
        self.together_client: TogetherClient | None = None
        self._together_share_url = ""
        self._together_revision = -1
        self._together_fetching = False
        self._together_generation = 0
        self._pending_together_playing: bool | None = None

        self.cast_renderer: UpnpRenderer | None = None
        self.cast_device = None
        self._cast_devices = []
        self._cast_media_server: LocalMediaServer | None = None
        self._cast_stream_uri = ""
        self._cast_position_ms = 0
        self._cast_started = 0.0
        self._cast_playing = False

        self._operationReady.connect(self._operation_finished)
        self.playback.trackStarted.connect(self._track_started)
        self.playback.playbackChanged.connect(self._playback_changed)
        self.playback.positionChanged.connect(self._position_changed)
        self.playback.nowPlayingChanged.connect(self._now_playing_changed)
        self.backend.preferencesChanged.connect(self.reload)
        self.backend.sessionChanged.connect(self._session_changed)
        self.playback.set_remote_transport(self)

        self._together_timer = QTimer(self)
        self._together_timer.setInterval(1000)
        self._together_timer.timeout.connect(self._together_tick)
        self._together_timer.start()

        self._download_validation_timer = QTimer(self)
        self._download_validation_timer.setInterval(24 * 60 * 60 * 1000)
        self._download_validation_timer.timeout.connect(self._validate_downloads_if_connected)
        self._download_validation_timer.start()
        if self.backend.loggedIn:
            QTimer.singleShot(1500, self._validate_downloads_if_connected)

        self._configure_discord_presence()

    # Preferences -----------------------------------------------------

    def _save_preferences(self) -> None:
        self.settings.save()
        self.changed.emit()

    @Slot()
    def reload(self) -> None:
        self._configure_discord_presence()
        self.changed.emit()

    # Last.fm ---------------------------------------------------------

    @Property(bool, notify=changed)
    def lastFmConnected(self) -> bool:
        return self.lastfm_credentials.load().session is not None

    @Property(str, notify=changed)
    def lastFmUsername(self) -> str:
        session = self.lastfm_credentials.load().session
        return session.username if session else ""

    @Property(bool, notify=changed)
    def lastFmEnabled(self) -> bool:
        return self.settings.values.lastfm_enabled

    @Property(str, notify=changed)
    def lastFmApiKey(self) -> str:
        return self.settings.values.lastfm_api_key

    @Property(bool, notify=changed)
    def lastFmSecretConfigured(self) -> bool:
        return bool(self.lastfm_credentials.load().api_secret)

    @Property(bool, notify=changed)
    def lastFmAuthorizationPending(self) -> bool:
        return bool(self._lastfm_pending_token)

    def _lastfm_client(self, *, require_session: bool = True) -> LastFmClient:
        credentials = self.lastfm_credentials.load()
        session_key = credentials.session.key if credentials.session else ""
        if require_session and not session_key:
            raise LastFmError("A conta do Last.fm ainda não foi autorizada")
        return LastFmClient(
            self.settings.values.lastfm_api_key,
            credentials.api_secret,
            session_key,
        )

    @Slot(bool)
    def setLastFmEnabled(self, enabled: bool) -> None:
        enabled = bool(enabled) and self.lastFmConnected
        if enabled == self.settings.values.lastfm_enabled:
            return
        self.settings.values.lastfm_enabled = enabled
        self._save_preferences()

    @Slot(str)
    def setLastFmApiKey(self, value: str) -> None:
        value = value.strip()
        if value == self.settings.values.lastfm_api_key:
            return
        self.settings.values.lastfm_api_key = value
        self._save_preferences()

    @Slot(str)
    def setLastFmSecret(self, value: str) -> None:
        value = value.strip()
        if not value:
            return
        credentials = self.lastfm_credentials.load()
        self.lastfm_credentials.save(LastFmCredentials(value, credentials.session))
        self.changed.emit()
        self.backend._set_status("Segredo da API do Last.fm salvo no chaveiro do sistema.")

    @Slot()
    def beginLastFmAuthorization(self) -> None:
        self.backend._set_status("Iniciando autorização do Last.fm…")

        def operation():
            client = self._lastfm_client(require_session=False)
            token = client.request_token()
            return token, client.authorization_url(token)

        self._run("lastfm-begin", operation)

    @Slot()
    def finishLastFmAuthorization(self) -> None:
        token = self._lastfm_pending_token
        if not token:
            self.backend._set_status("Inicie a autorização do Last.fm primeiro.")
            return
        self.backend._set_status("Concluindo autorização do Last.fm…")

        def operation():
            client = self._lastfm_client(require_session=False)
            session = client.create_session(token)
            credentials = self.lastfm_credentials.load()
            self.lastfm_credentials.save(LastFmCredentials(credentials.api_secret, session))
            return session

        self._run("lastfm-finish", operation)

    @Slot()
    def disconnectLastFm(self) -> None:
        self.lastfm_credentials.clear_session()
        self._lastfm_pending_token = ""
        self.settings.values.lastfm_enabled = False
        self._save_preferences()
        self.backend._set_status("Last.fm desconectado.")

    # Discord ---------------------------------------------------------

    @Property(bool, notify=changed)
    def discordEnabled(self) -> bool:
        return self.settings.values.discord_enabled

    @Property(str, notify=changed)
    def discordClientId(self) -> str:
        return self.settings.values.discord_client_id

    @Slot(bool)
    def setDiscordEnabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self.settings.values.discord_enabled:
            return
        self.settings.values.discord_enabled = enabled
        self._save_preferences()
        self._configure_discord_presence()
        self._update_discord_presence()

    @Slot(str)
    def setDiscordClientId(self, value: str) -> None:
        value = value.strip()
        if value == self.settings.values.discord_client_id:
            return
        self.settings.values.discord_client_id = value
        self._save_preferences()
        self._configure_discord_presence()
        self._update_discord_presence()

    def _configure_discord_presence(self) -> None:
        values = self.settings.values
        config = (bool(values.discord_enabled), values.discord_client_id.strip())
        if config == self._discord_config:
            return
        self._discord_config = config
        old = self.discord_presence
        if old is not None:
            try:
                old.clear()
                old.close()
            except OSError:
                LOGGER.debug("Não foi possível limpar o Rich Presence anterior", exc_info=True)
        self.discord_presence = (
            DiscordPresence(config[1]) if config[0] and config[1] else None
        )

    def _update_discord_presence(self) -> None:
        presence = self.discord_presence
        item = self._social_item or self.playback.current_item
        if presence is None or item is None:
            return
        self._run(
            "discord-presence",
            lambda: presence.update(item, self.playback.playing, self._social_started_at),
            report_error=False,
        )

    # Playback hooks --------------------------------------------------

    @Slot(object, int)
    def _track_started(self, item, duration_ms: int) -> None:
        self._social_item = item
        self._social_started_at = playback_started_at(self.playback.position)
        self._lastfm_scrobbled = False
        if item is not None and self.settings.values.lastfm_enabled and self.lastFmConnected:
            self._run(
                "lastfm-now-playing",
                lambda: self._lastfm_client().update_now_playing(item, duration_ms),
                report_error=False,
            )
        self._update_discord_presence()

        pending = self._pending_together_playing
        self._pending_together_playing = None
        if pending is False:
            QTimer.singleShot(300, self._pause_for_together)

    def _pause_for_together(self) -> None:
        if self.playback.playing:
            self.playback.toggle_playback()

    @Slot()
    def _playback_changed(self) -> None:
        self._update_discord_presence()

    @Slot()
    def _position_changed(self) -> None:
        item = self._social_item
        if (
            item is None
            or self._lastfm_scrobbled
            or not self.settings.values.lastfm_enabled
            or not self.lastFmConnected
            or not scrobble_ready(self.playback.duration, self.playback.position)
        ):
            return
        self._lastfm_scrobbled = True
        self._run(
            "lastfm-scrobble",
            lambda: self._lastfm_client().scrobble(
                item,
                self._social_started_at,
                self.playback.duration,
            ),
            report_error=False,
        )

    @Slot()
    def _now_playing_changed(self) -> None:
        if self.playback.current_item is not None:
            return
        self._social_item = None
        presence = self.discord_presence
        if presence is not None:
            self._run("discord-clear", presence.clear, report_error=False)

    # Listen Together -------------------------------------------------

    @Property(str, notify=togetherChanged)
    def togetherStatus(self) -> str:
        if self.together_host:
            return "Você está compartilhando a reprodução"
        if self.together_client:
            return "Sincronizado com o anfitrião"
        return "Nenhuma sessão ativa"

    @Property(str, notify=togetherChanged)
    def togetherShareUrl(self) -> str:
        return self._together_share_url

    @Property(bool, notify=togetherChanged)
    def togetherActive(self) -> bool:
        return bool(self.together_host or self.together_client)

    def _leave_together(self, *, invalidate: bool = True) -> None:
        if invalidate:
            self._together_generation += 1
        if self.together_host:
            self.together_host.close()
        self.together_host = None
        self.together_client = None
        self._together_share_url = ""
        self._together_revision = -1
        self._together_fetching = False
        self._pending_together_playing = None
        self.togetherChanged.emit()

    @Slot()
    def createTogetherSession(self) -> None:
        self._leave_together()
        try:
            self.together_host = TogetherHost()
            self._together_share_url = self.together_host.share_url()
        except OSError as exc:
            self.backend._set_status(f"Não foi possível criar a sessão: {exc}")
            return
        self.togetherChanged.emit()
        self.backend._set_status("Sessão Listen Together criada.")

    @Slot(str)
    def joinTogetherSession(self, share_url: str) -> None:
        try:
            client = TogetherClient(share_url)
        except ValueError as exc:
            self.backend._set_status(str(exc))
            return
        self._leave_together()
        generation = self._together_generation
        self.backend._set_status("Entrando na sessão Listen Together…")
        self._run(
            "together-join",
            lambda: (generation, client, client.fetch()),
        )

    @Slot()
    def leaveTogetherSession(self) -> None:
        self._leave_together()
        self.backend._set_status("Sessão Listen Together encerrada.")

    def _together_tick(self) -> None:
        if self.together_host:
            self.together_host.update(
                TogetherState(
                    list(self.playback.queue),
                    max(0, self.playback.queue_index),
                    self.playback.position,
                    self.playback.playing,
                )
            )
            return
        if self.together_client and not self._together_fetching:
            self._together_fetching = True
            client = self.together_client
            self._run(
                "together-sync",
                lambda: (client, client.fetch()),
                report_error=False,
            )

    def _apply_together_state(self, state: TogetherState) -> None:
        if state.revision <= self._together_revision:
            return
        self._together_revision = state.revision
        if not state.queue:
            return
        index = min(state.index, len(state.queue) - 1)
        position_ms = state.corrected_position_ms()
        current = self.playback.current_item
        target = state.queue[index]
        if current is None or current.id != target.id:
            self._pending_together_playing = state.playing
            self.playback.load_shared_state(state.queue, index, position_ms)
            return
        self.playback.queue = list(state.queue)
        self.playback.queue_index = index
        self.playback.queueChanged.emit()
        if abs(self.playback.position - position_ms) > 1500:
            self.playback.seek(position_ms)
        if state.playing != self.playback.playing:
            self.playback.toggle_playback()

    # Recognition -----------------------------------------------------

    @Property(str, notify=changed)
    def recognitionProvider(self) -> str:
        return self.settings.values.recognition_provider

    @Property(str, notify=changed)
    def recognitionEndpoint(self) -> str:
        return self.settings.values.recognition_endpoint

    @Property(bool, notify=changed)
    def recognitionTokenConfigured(self) -> bool:
        return bool(self.recognition_tokens.load())

    @Slot(str)
    def setRecognitionProvider(self, value: str) -> None:
        value = value if value in {"audd", "custom"} else "audd"
        if value == self.settings.values.recognition_provider:
            return
        self.settings.values.recognition_provider = value
        self._save_preferences()

    @Slot(str)
    def setRecognitionEndpoint(self, value: str) -> None:
        value = value.strip() or "https://api.audd.io/"
        if value == self.settings.values.recognition_endpoint:
            return
        self.settings.values.recognition_endpoint = value
        self._save_preferences()

    @Slot(str)
    def setRecognitionToken(self, value: str) -> None:
        value = value.strip()
        if not value:
            return
        self.recognition_tokens.save(value)
        self.changed.emit()
        self.backend._set_status("Token do AudD salvo no chaveiro do sistema.")

    @Slot()
    def recognizeMusic(self) -> None:
        token = self.recognition_tokens.load()
        if not token:
            self.backend._set_status("Configure o token do AudD primeiro.")
            return
        endpoint = (
            self.settings.values.recognition_endpoint
            if self.settings.values.recognition_provider == "custom"
            else None
        )
        recognizer = MusicRecognizer(AuddRecognitionProvider(token, endpoint=endpoint))
        self.backend._set_status("Ouvindo por 12 segundos…")
        self._run("recognition", recognizer.recognize)

    # UPnP / DLNA -----------------------------------------------------

    @Property("QVariantList", notify=castChanged)
    def castDevices(self) -> list[dict[str, object]]:
        return [
            {"name": device.name, "index": index}
            for index, device in enumerate(self._cast_devices)
        ]

    @Property(bool, notify=castChanged)
    def castConnected(self) -> bool:
        return self.cast_renderer is not None

    @Property(str, notify=castChanged)
    def castDeviceName(self) -> str:
        return self.cast_device.name if self.cast_device else ""

    @Slot()
    def scanCastDevices(self) -> None:
        self.backend._set_status("Procurando dispositivos UPnP/DLNA na rede local…")
        self._run("cast-discovery", UpnpDiscovery().discover)

    @Slot(int)
    def connectCastDevice(self, index: int) -> None:
        if not 0 <= index < len(self._cast_devices):
            return
        if self.playback.current_item is None or not self.playback.current_stream_uri:
            self.backend._set_status("Comece a reproduzir uma faixa antes de transmitir.")
            return

        device = self._cast_devices[index]
        renderer = UpnpRenderer(device)
        position_ms = self.playback.position
        was_playing = self.playback.playing
        uri = self.playback.current_stream_uri
        title = self.playback.current_item.title
        try:
            cast_uri = self._castable_uri(uri)
        except (OSError, ValueError) as exc:
            self.backend._set_status(f"Não foi possível transmitir: {exc}")
            return

        # Stop GStreamer before making the remote transport active, otherwise
        # the Qt playback facade would already report the renderer's state.
        self.playback.player.stop()
        self.cast_device = device
        self.cast_renderer = renderer
        self._cast_stream_uri = uri
        self._cast_position_ms = position_ms
        self._cast_started = time.monotonic() - position_ms / 1000
        self._cast_playing = was_playing
        self.castChanged.emit()
        self.playback.playbackChanged.emit()

        def operation():
            renderer.play_uri(cast_uri, title)
            if position_ms > 1000:
                renderer.seek(position_ms)
            if not was_playing:
                renderer.pause()
            return device

        self.backend._set_status(f"Conectando a {device.name}…")
        self._run("cast-connect", operation)

    @Slot()
    def disconnectCast(self) -> None:
        self._disconnect_cast(resume=True)

    @property
    def active(self) -> bool:
        return self.cast_renderer is not None

    @property
    def playing(self) -> bool:
        return self._cast_playing if self.active else self.playback.player.playing

    @property
    def position_ms(self) -> int:
        if not self.active:
            return self.playback.player.position_us // 1000
        if self._cast_playing:
            return max(0, int((time.monotonic() - self._cast_started) * 1000))
        return self._cast_position_ms

    def start_stream(self, uri: str, item) -> bool:
        if not self.active:
            return False
        renderer = self.cast_renderer
        if renderer is None:
            return False
        self._cast_stream_uri = uri
        self._cast_position_ms = 0
        self._cast_started = time.monotonic()
        self._cast_playing = True
        try:
            cast_uri = self._castable_uri(uri)
        except (OSError, ValueError) as exc:
            self.backend._set_status(f"Não foi possível transmitir: {exc}")
            self._disconnect_cast(resume=False)
            return False
        self._run("cast-track", lambda: renderer.play_uri(cast_uri, item.title))
        self.castChanged.emit()
        return True

    def toggle(self) -> bool:
        renderer = self.cast_renderer
        if renderer is None:
            return False
        if self._cast_playing:
            self._cast_position_ms = self.position_ms
            self._cast_playing = False
            self._run("cast-pause", renderer.pause, report_error=False)
        else:
            self._cast_started = time.monotonic() - self._cast_position_ms / 1000
            self._cast_playing = True
            self._run("cast-play", renderer.play, report_error=False)
        self.playback.playbackChanged.emit()
        return True

    def seek(self, position_ms: int) -> bool:
        renderer = self.cast_renderer
        if renderer is None:
            return False
        self._cast_position_ms = max(0, int(position_ms))
        if self._cast_playing:
            self._cast_started = time.monotonic() - self._cast_position_ms / 1000
        self._run(
            "cast-seek",
            lambda: renderer.seek(self._cast_position_ms),
            report_error=False,
        )
        return True

    def stop(self) -> bool:
        if not self.active:
            return False
        self._disconnect_cast(resume=False)
        return True

    def _disconnect_cast(self, *, resume: bool) -> None:
        renderer = self.cast_renderer
        if renderer is None:
            return
        position_ms = self.position_ms
        stream_uri = self._cast_stream_uri or self.playback.current_stream_uri
        self.cast_renderer = None
        self.cast_device = None
        self._cast_playing = False
        self._cast_stream_uri = ""
        self._run("cast-stop", renderer.stop, report_error=False)
        self._close_cast_media_server()
        self.castChanged.emit()
        if resume and stream_uri and self.playback.current_item is not None:
            self.playback.player.play(stream_uri)
            QTimer.singleShot(500, lambda: self.playback.seek(position_ms))
            self.backend._set_status("Reprodução devolvida a este computador.")
        self.playback.playbackChanged.emit()

    def _castable_uri(self, uri: str) -> str:
        self._close_cast_media_server()
        if uri.startswith("file:"):
            self._cast_media_server = LocalMediaServer.from_uri(uri)
            return self._cast_media_server.url
        return uri

    def _close_cast_media_server(self) -> None:
        if self._cast_media_server:
            self._cast_media_server.close()
            self._cast_media_server = None

    # Workers / lifecycle --------------------------------------------

    def _run(self, name: str, operation, *, report_error: bool = True) -> None:
        def worker() -> None:
            try:
                result, error = operation(), ""
            except Exception as exc:
                LOGGER.debug("Falha na integração Qt %s", name, exc_info=True)
                result, error = None, str(exc)
            operation_name = name if report_error else f"silent:{name}"
            self._operationReady.emit(operation_name, result, error)

        try:
            self.executor.submit(worker)
        except RuntimeError:
            LOGGER.debug("Executor já encerrado; ignorando %s", name)

    @Slot(str, object, str)
    def _operation_finished(self, operation: str, result, error: str) -> None:
        silent = operation.startswith("silent:")
        name = operation.removeprefix("silent:")
        if error:
            if name == "together-sync":
                self._together_fetching = False
            if name in {"cast-connect", "cast-track"}:
                self._disconnect_cast(resume=True)
            if not silent:
                labels = {
                    "lastfm-begin": "Não foi possível iniciar o Last.fm",
                    "lastfm-finish": "Não foi possível conectar ao Last.fm",
                    "together-join": "Não foi possível entrar na sessão",
                    "recognition": "Reconhecimento falhou",
                    "cast-discovery": "Falha ao procurar dispositivos",
                    "cast-connect": "Não foi possível transmitir",
                    "cast-track": "Não foi possível trocar a faixa no dispositivo",
                }
                self.backend._set_status(f"{labels.get(name, 'Operação falhou')}: {error}")
            return

        if name == "lastfm-begin":
            token, url = result
            self._lastfm_pending_token = token
            self.changed.emit()
            QDesktopServices.openUrl(QUrl(url))
            self.backend._set_status("Autorize no navegador e depois clique em Concluir.")
        elif name == "lastfm-finish":
            self._lastfm_pending_token = ""
            self.settings.values.lastfm_enabled = True
            self._save_preferences()
            self.backend._set_status(f"Last.fm conectado como {result.username}.")
        elif name == "together-join":
            generation, client, state = result
            if generation != self._together_generation:
                return
            self.together_client = client
            self._together_revision = -1
            self._apply_together_state(state)
            self.togetherChanged.emit()
            self.backend._set_status("Listen Together conectado.")
        elif name == "together-sync":
            self._together_fetching = False
            client, state = result
            if client is self.together_client:
                self._apply_together_state(state)
        elif name == "recognition":
            if result is None:
                self.backend._set_status("Nenhuma música reconhecida.")
            else:
                self.backend._set_status(f"Encontrada: {result.title} — {result.artist}")
                self.backend.search(f"{result.artist} {result.title}")
        elif name == "cast-discovery":
            self._cast_devices = list(result or [])
            self.castChanged.emit()
            if self._cast_devices:
                self.backend._set_status(
                    f"{len(self._cast_devices)} dispositivo(s) encontrado(s)."
                )
            else:
                self.backend._set_status("Nenhum dispositivo UPnP/DLNA encontrado.")
        elif name in {"cast-connect", "cast-track"}:
            self.castChanged.emit()
            self.playback.playbackChanged.emit()
            if self.cast_device:
                self.backend._set_status(f"Reproduzindo em {self.cast_device.name}.")

    @Slot()
    def _session_changed(self) -> None:
        if self.backend.loggedIn:
            QTimer.singleShot(1000, self._validate_downloads_if_connected)

    def _validate_downloads_if_connected(self) -> None:
        if self.backend.loggedIn:
            self.settings.validate_downloads()

    @Slot()
    def shutdown(self) -> None:
        self._together_timer.stop()
        self._download_validation_timer.stop()
        self._leave_together()
        if self.cast_renderer:
            renderer = self.cast_renderer
            self.cast_renderer = None
            self._run("cast-stop", renderer.stop, report_error=False)
        self._close_cast_media_server()
        if self.discord_presence:
            try:
                self.discord_presence.clear()
                self.discord_presence.close()
            except OSError:
                LOGGER.debug("Falha ao encerrar Discord Rich Presence", exc_info=True)
            self.discord_presence = None
