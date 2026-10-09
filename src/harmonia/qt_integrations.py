"""The KDE frontend's integrations, as QML sees them.

Each integration keeps its state and logic in its own module (qt_lastfm,
qt_discord, qt_together, qt_recognition, qt_cast); this controller only
declares the properties and slots QML binds to, runs their background jobs
and forwards the playback events they follow.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from .i18n import _
from .qt_cast import CastBridge
from .qt_discord import DiscordBridge
from .qt_integration_context import IntegrationContext, Job
from .qt_lastfm import LastFmBridge
from .qt_recognition import RecognitionBridge
from .qt_together import TogetherBridge
from .social import playback_started_at

LOGGER = logging.getLogger(__name__)


class QtIntegrationsController(QObject):
    """Qt bridge for the shared social, LAN and recognition services."""

    changed = Signal()
    togetherChanged = Signal()
    castChanged = Signal()
    _jobFinished = Signal(object, object, str)

    def __init__(
        self,
        backend,
        executor: ThreadPoolExecutor,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.backend = backend
        self.settings = backend.settings
        self.playback = backend.playback
        self.executor = executor
        self._social_started_at = 0
        self._social_item = None

        context = IntegrationContext(
            settings=self.settings,
            playback=self.playback,
            storage=backend.storage,
            set_status=backend._set_status,
            run=self._run,
            save_preferences=self._save_preferences,
            changed=self.changed.emit,
        )
        self.lastfm = LastFmBridge(context)
        self.discord = DiscordBridge(context)
        self.together = TogetherBridge(context, self.togetherChanged.emit)
        self.recognition = RecognitionBridge(context, backend.search)
        self.cast = CastBridge(context, self.castChanged.emit)

        self._jobFinished.connect(self._job_finished)
        self.playback.trackStarted.connect(self._track_started)
        self.playback.playbackChanged.connect(self._update_discord)
        self.playback.positionChanged.connect(self._position_changed)
        self.playback.nowPlayingChanged.connect(self._now_playing_changed)
        self.backend.preferencesChanged.connect(self.reload)
        self.backend.sessionChanged.connect(self._session_changed)
        self.playback.set_remote_transport(self.cast)

        self._together_timer = QTimer(self)
        self._together_timer.setInterval(1000)
        self._together_timer.timeout.connect(self.together.tick)
        self._together_timer.start()

        self._download_validation_timer = QTimer(self)
        self._download_validation_timer.setInterval(24 * 60 * 60 * 1000)
        self._download_validation_timer.timeout.connect(self._validate_downloads_if_connected)
        self._download_validation_timer.start()
        if self.backend.loggedIn:
            QTimer.singleShot(1500, self._validate_downloads_if_connected)

        self.discord.configure()

    # Preferences -----------------------------------------------------

    def _save_preferences(self) -> None:
        self.settings.save()
        self.changed.emit()

    @Slot()
    def reload(self) -> None:
        self.discord.configure()
        self.changed.emit()

    # Last.fm ---------------------------------------------------------

    @Property(bool, notify=changed)
    def lastFmConnected(self) -> bool:
        return self.lastfm.connected

    @Property(str, notify=changed)
    def lastFmUsername(self) -> str:
        return self.lastfm.username

    @Property(bool, notify=changed)
    def lastFmEnabled(self) -> bool:
        return self.settings.values.lastfm_enabled

    @Property(str, notify=changed)
    def lastFmApiKey(self) -> str:
        return self.settings.values.lastfm_api_key

    @Property(bool, notify=changed)
    def lastFmSecretConfigured(self) -> bool:
        return self.lastfm.secret_configured

    @Property(bool, notify=changed)
    def lastFmAuthorizationPending(self) -> bool:
        return bool(self.lastfm.pending_token)

    @Slot(bool)
    def setLastFmEnabled(self, enabled: bool) -> None:
        self.lastfm.set_enabled(enabled)

    @Slot(str)
    def setLastFmApiKey(self, value: str) -> None:
        self.lastfm.set_api_key(value)

    @Slot(str)
    def setLastFmSecret(self, value: str) -> None:
        self.lastfm.set_secret(value)

    @Slot()
    def beginLastFmAuthorization(self) -> None:
        self.lastfm.begin_authorization()

    @Slot()
    def finishLastFmAuthorization(self) -> None:
        self.lastfm.finish_authorization()

    @Slot()
    def disconnectLastFm(self) -> None:
        self.lastfm.disconnect()

    # Discord ---------------------------------------------------------

    @Property(bool, notify=changed)
    def discordEnabled(self) -> bool:
        return self.settings.values.discord_enabled

    @Property(str, notify=changed)
    def discordClientId(self) -> str:
        return self.settings.values.discord_client_id

    @Slot(bool)
    def setDiscordEnabled(self, enabled: bool) -> None:
        if self.discord.set_enabled(enabled):
            self._update_discord()

    @Slot(str)
    def setDiscordClientId(self, value: str) -> None:
        if self.discord.set_client_id(value):
            self._update_discord()

    # Playback hooks --------------------------------------------------

    @Slot(object, int)
    def _track_started(self, item, duration_ms: int) -> None:
        self._social_item = item
        self._social_started_at = playback_started_at(self.playback.position)
        self.lastfm.track_started(item, duration_ms)
        self._update_discord()
        self.together.track_started()

    @Slot()
    def _update_discord(self) -> None:
        item = self._social_item or self.playback.current_item
        self.discord.update(item, self.playback.playing, self._social_started_at)

    @Slot()
    def _position_changed(self) -> None:
        self.lastfm.position_changed(self._social_item, self._social_started_at)

    @Slot()
    def _now_playing_changed(self) -> None:
        if self.playback.current_item is None:
            self._social_item = None
            self.discord.clear()

    # Listen Together -------------------------------------------------

    @Property(str, notify=togetherChanged)
    def togetherStatus(self) -> str:
        return self.together.status

    @Property(str, notify=togetherChanged)
    def togetherShareUrl(self) -> str:
        return self.together.share_url

    @Property(bool, notify=togetherChanged)
    def togetherActive(self) -> bool:
        return self.together.active

    @Slot()
    def createTogetherSession(self) -> None:
        self.together.create()

    @Slot(str)
    def joinTogetherSession(self, share_url: str) -> None:
        self.together.join(share_url)

    @Slot()
    def leaveTogetherSession(self) -> None:
        self.together.leave()
        self.backend._set_status(_("Sessão Listen Together encerrada."))

    # Recognition -----------------------------------------------------

    @Property(str, notify=changed)
    def recognitionProvider(self) -> str:
        return self.settings.values.recognition_provider

    @Property(str, notify=changed)
    def recognitionEndpoint(self) -> str:
        return self.settings.values.recognition_endpoint

    @Property(bool, notify=changed)
    def recognitionTokenConfigured(self) -> bool:
        return self.recognition.token_configured

    @Slot(str)
    def setRecognitionProvider(self, value: str) -> None:
        self.recognition.set_provider(value)

    @Slot(str)
    def setRecognitionEndpoint(self, value: str) -> None:
        self.recognition.set_endpoint(value)

    @Slot(str)
    def setRecognitionToken(self, value: str) -> None:
        self.recognition.set_token(value)

    @Slot()
    def recognizeMusic(self) -> None:
        self.recognition.recognize()

    # UPnP / DLNA -----------------------------------------------------

    @Property("QVariantList", notify=castChanged)
    def castDevices(self) -> list[dict[str, object]]:
        return [{"name": device.name, "index": i} for i, device in enumerate(self.cast.devices)]

    @Property(bool, notify=castChanged)
    def castConnected(self) -> bool:
        return self.cast.active

    @Property(str, notify=castChanged)
    def castDeviceName(self) -> str:
        return self.cast.device.name if self.cast.device else ""

    @Slot()
    def scanCastDevices(self) -> None:
        self.cast.scan()

    @Slot(int)
    def connectCastDevice(self, index: int) -> None:
        self.cast.connect(index)

    @Slot()
    def disconnectCast(self) -> None:
        self.cast.disconnect(resume=True)

    # Background jobs -------------------------------------------------

    def _run(self, job: Job, operation: Callable[[], Any]) -> None:
        """Run ``operation`` on the executor and the job's callbacks on the Qt thread."""

        def worker() -> None:
            try:
                result, error = operation(), ""
            except Exception as exc:
                LOGGER.debug("Falha na integração Qt %s", job.name, exc_info=True)
                result, error = None, str(exc)
            self._jobFinished.emit(job, result, error)

        try:
            self.executor.submit(worker)
        except RuntimeError:
            LOGGER.debug("Executor já encerrado; ignorando %s", job.name)

    @Slot(object, object, str)
    def _job_finished(self, job: Job, result, error: str) -> None:
        if not error:
            if job.on_done is not None:
                job.on_done(result)
            return
        if job.on_failure is not None:
            job.on_failure(error)
        if job.failure_label:
            self.backend._set_status(
                _("{label}: {error}").format(label=job.failure_label, error=error), error=True
            )

    # Lifecycle -------------------------------------------------------

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
        self.together.leave()
        self.cast.close()
        self.discord.close()
