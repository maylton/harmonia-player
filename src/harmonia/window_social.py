from __future__ import annotations

import logging
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib

from .i18n import _
from .social import (
    DiscordPresence,
    LastFmClient,
    LastFmCredentials,
    LastFmCredentialStore,
    LastFmError,
    playback_started_at,
    scrobble_ready,
)

LOGGER = logging.getLogger(__name__)


class WindowSocialMixin:
    def _initialize_social(self) -> None:
        self.lastfm_credentials = LastFmCredentialStore(self.storage)
        self._lastfm_pending_token = ""
        self._social_started_at = 0
        self._lastfm_scrobbled_request = -1
        self.discord_presence = None
        self._configure_discord_presence()
        self.connect("close-request", self._close_social_integrations)

    def _lastfm_client(self, *, require_session: bool = True) -> LastFmClient:
        credentials = self.lastfm_credentials.load()
        session_key = credentials.session.key if credentials.session else ""
        if require_session and not session_key:
            raise LastFmError(_("A conta do Last.fm ainda não foi autorizada"))
        return LastFmClient(self.preferences.lastfm_api_key, credentials.api_secret, session_key)

    def _social_worker(self, name: str, operation, completed=None) -> None:
        def worker() -> None:
            try:
                result, error = operation(), None
            except Exception as exc:
                LOGGER.debug("Falha na integração %s", name, exc_info=True)
                result, error = None, str(exc)
            if completed:
                GLib.idle_add(completed, result, error)

        threading.Thread(target=worker, daemon=True, name=f"social-{name}").start()

    def _configure_lastfm_secret(self, value: str) -> None:
        value = value.strip()
        if not value:
            return
        credentials = self.lastfm_credentials.load()
        self.lastfm_credentials.save(LastFmCredentials(value, credentials.session))

    def _begin_lastfm_authorization(self) -> None:
        def begin():
            client = self._lastfm_client(require_session=False)
            token = client.request_token()
            return token, client.authorization_url(token)

        def completed(result, error):
            if error:
                self.toast_overlay.add_toast(
                    Adw.Toast(
                        title=_("Não foi possível iniciar o Last.fm: {error}").format(error=error)
                    )
                )
                return False
            self._lastfm_pending_token, url = result
            Gio.AppInfo.launch_default_for_uri(url, None)
            self.toast_overlay.add_toast(
                Adw.Toast(title=_("Autorize no navegador e clique em Concluir"), timeout=6)
            )
            self.show_settings()
            return False

        self._social_worker("lastfm-auth", begin, completed)

    def _finish_lastfm_authorization(self) -> None:
        token = self._lastfm_pending_token
        if not token:
            self.toast_overlay.add_toast(
                Adw.Toast(title=_("Inicie a autorização do Last.fm primeiro"))
            )
            return

        def finish():
            client = self._lastfm_client(require_session=False)
            session = client.create_session(token)
            credentials = self.lastfm_credentials.load()
            self.lastfm_credentials.save(LastFmCredentials(credentials.api_secret, session))
            return session

        def completed(session, error):
            if error:
                self.toast_overlay.add_toast(
                    Adw.Toast(
                        title=_("Não foi possível conectar ao Last.fm: {error}").format(error=error)
                    )
                )
                return False
            self._lastfm_pending_token = ""
            self.preferences.lastfm_enabled = True
            self.preferences.save(self.storage)
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=_("Last.fm conectado como {username}").format(username=session.username)
                )
            )
            self.show_settings()
            return False

        self._social_worker("lastfm-session", finish, completed)

    def _disconnect_lastfm(self) -> None:
        self.lastfm_credentials.clear_session()
        self.preferences.lastfm_enabled = False
        self.preferences.save(self.storage)
        self._lastfm_pending_token = ""
        self.toast_overlay.add_toast(Adw.Toast(title=_("Last.fm desconectado")))
        self.show_settings()

    def _configure_discord_presence(self) -> None:
        if self.discord_presence:
            self.discord_presence.clear()
            self.discord_presence.close()
        self.discord_presence = (
            DiscordPresence(self.preferences.discord_client_id)
            if self.preferences.discord_enabled and self.preferences.discord_client_id
            else None
        )

    def _discord_preference_changed(self, name: str, value) -> None:
        self._preference_changed(name, value)
        self._configure_discord_presence()
        if self.discord_presence and getattr(self, "current_item", None):
            self._social_playback_changed(self.player.playing)

    def _social_track_started(self, position_ms: int = 0) -> None:
        self._social_started_at = playback_started_at(position_ms)
        self._lastfm_scrobbled_request = -1
        item = getattr(self, "current_item", None)
        if item is None:
            return
        if self.preferences.lastfm_enabled:
            self._social_worker(
                "lastfm-now-playing",
                lambda: self._lastfm_client().update_now_playing(item, self.current_duration_ms),
            )
        self._social_playback_changed(True)

    def _social_playback_changed(self, playing: bool) -> None:
        item = getattr(self, "current_item", None)
        presence = self.discord_presence
        if item is None or presence is None:
            return
        self._social_worker(
            "discord-presence",
            lambda: presence.update(item, playing, self._social_started_at),
        )

    def _maybe_scrobble_lastfm(self, position_ms: int) -> None:
        if (
            not self.preferences.lastfm_enabled
            or self._lastfm_scrobbled_request == self._play_request
            or not scrobble_ready(self.current_duration_ms, position_ms)
        ):
            return
        item = getattr(self, "current_item", None)
        if item is None:
            return
        self._lastfm_scrobbled_request = self._play_request
        self._social_worker(
            "lastfm-scrobble",
            lambda: self._lastfm_client().scrobble(
                item, self._social_started_at, self.current_duration_ms
            ),
        )

    def _clear_social_presence(self) -> None:
        if self.discord_presence:
            self._social_worker("discord-clear", self.discord_presence.clear)

    def _close_social_integrations(self, *_args) -> bool:
        if self.discord_presence:
            self.discord_presence.clear()
            self.discord_presence.close()
        return False
