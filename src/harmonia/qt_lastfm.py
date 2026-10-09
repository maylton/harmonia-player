"""Last.fm in the KDE frontend: authorization and scrobbling."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from .i18n import _
from .qt_integration_context import IntegrationContext, Job
from .social import (
    LastFmClient,
    LastFmCredentials,
    LastFmCredentialStore,
    LastFmError,
    scrobble_ready,
)


class LastFmBridge:
    def __init__(self, context: IntegrationContext) -> None:
        self.context = context
        self.credentials = LastFmCredentialStore(context.storage)
        self.pending_token = ""
        self._scrobbled = False

    @property
    def values(self):
        return self.context.settings.values

    @property
    def connected(self) -> bool:
        return self.credentials.load().session is not None

    @property
    def username(self) -> str:
        session = self.credentials.load().session
        return session.username if session else ""

    @property
    def secret_configured(self) -> bool:
        return bool(self.credentials.load().api_secret)

    @property
    def active(self) -> bool:
        return self.values.lastfm_enabled and self.connected

    def client(self, *, require_session: bool = True) -> LastFmClient:
        credentials = self.credentials.load()
        session_key = credentials.session.key if credentials.session else ""
        if require_session and not session_key:
            raise LastFmError(_("A conta do Last.fm ainda não foi autorizada"))
        return LastFmClient(self.values.lastfm_api_key, credentials.api_secret, session_key)

    # Settings

    def set_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled) and self.connected
        if enabled != self.values.lastfm_enabled:
            self.values.lastfm_enabled = enabled
            self.context.save_preferences()

    def set_api_key(self, value: str) -> None:
        value = value.strip()
        if value != self.values.lastfm_api_key:
            self.values.lastfm_api_key = value
            self.context.save_preferences()

    def set_secret(self, value: str) -> None:
        value = value.strip()
        if not value:
            return
        self.credentials.save(LastFmCredentials(value, self.credentials.load().session))
        self.context.changed()
        self.context.set_status(_("Segredo da API do Last.fm salvo no chaveiro do sistema."))

    # Authorization

    def begin_authorization(self) -> None:
        self.context.set_status(_("Iniciando autorização do Last.fm…"))

        def operation():
            client = self.client(require_session=False)
            token = client.request_token()
            return token, client.authorization_url(token)

        self.context.run(
            Job(
                "lastfm-begin",
                self._authorization_started,
                None,
                _("Não foi possível iniciar o Last.fm"),
            ),
            operation,
        )

    def _authorization_started(self, result) -> None:
        self.pending_token, url = result
        self.context.changed()
        QDesktopServices.openUrl(QUrl(url))
        self.context.set_status(_("Autorize no navegador e depois clique em Concluir."))

    def finish_authorization(self) -> None:
        token = self.pending_token
        if not token:
            self.context.set_status(_("Inicie a autorização do Last.fm primeiro."))
            return
        self.context.set_status(_("Concluindo autorização do Last.fm…"))

        def operation():
            session = self.client(require_session=False).create_session(token)
            self.credentials.save(LastFmCredentials(self.credentials.load().api_secret, session))
            return session

        self.context.run(
            Job(
                "lastfm-finish",
                self._authorization_finished,
                None,
                _("Não foi possível conectar ao Last.fm"),
            ),
            operation,
        )

    def _authorization_finished(self, session) -> None:
        self.pending_token = ""
        self.values.lastfm_enabled = True
        self.context.save_preferences()
        self.context.set_status(
            _("Last.fm conectado como {username}.").format(username=session.username)
        )

    def disconnect(self) -> None:
        self.credentials.clear_session()
        self.pending_token = ""
        self.values.lastfm_enabled = False
        self.context.save_preferences()
        self.context.set_status(_("Last.fm desconectado."))

    # Playback

    def track_started(self, item, duration_ms: int) -> None:
        self._scrobbled = False
        if item is not None and self.active:
            self.context.run(
                Job("lastfm-now-playing"),
                lambda: self.client().update_now_playing(item, duration_ms),
            )

    def position_changed(self, item, started_at: int) -> None:
        playback = self.context.playback
        if (
            item is None
            or self._scrobbled
            or not self.active
            or not scrobble_ready(playback.duration, playback.position)
        ):
            return
        self._scrobbled = True
        duration = playback.duration
        self.context.run(
            Job("lastfm-scrobble"), lambda: self.client().scrobble(item, started_at, duration)
        )
