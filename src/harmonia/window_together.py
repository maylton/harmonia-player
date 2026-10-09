"""Listen Together: host or join a shared queue on the local network."""

from __future__ import annotations

import gi

gi.require_version("Adw", "1")
from gi.repository import Adw, GLib

from .i18n import _
from .together import TogetherClient, TogetherHost, TogetherState


class WindowTogetherMixin:
    def _together_status(self) -> str:
        if self.together_host:
            return _("Você está compartilhando a reprodução")
        if self.together_client:
            return _("Sincronizado com o anfitrião")
        return _("Nenhuma sessão ativa")

    def _create_together_session(self) -> None:
        self._leave_together_session(refresh=False)
        try:
            self.together_host = TogetherHost()
            self._together_share_url = self.together_host.share_url()
            self.toast_overlay.add_toast(Adw.Toast(title=_("Sessão Listen Together criada")))
            self.show_settings()
        except OSError as exc:
            self.toast_overlay.add_toast(
                Adw.Toast(title=_("Não foi possível criar a sessão: {error}").format(error=exc))
            )

    def _join_together_session(self, url: str) -> None:
        try:
            client = TogetherClient(url)
        except ValueError as exc:
            self.toast_overlay.add_toast(Adw.Toast(title=str(exc)))
            return

        def connected(state, error):
            if error:
                self.toast_overlay.add_toast(
                    Adw.Toast(
                        title=_("Não foi possível entrar na sessão: {error}").format(error=error)
                    )
                )
                return False
            self._leave_together_session(refresh=False)
            self.together_client = client
            self._together_revision = -1
            self._apply_together_state(state)
            self.toast_overlay.add_toast(Adw.Toast(title=_("Listen Together conectado")))
            self.show_settings()
            return False

        self._optional_worker("together-join", client.fetch, connected)

    def _leave_together_session(self, *, refresh: bool = True) -> None:
        if self.together_host:
            self.together_host.close()
        self.together_host = None
        self.together_client = None
        self._together_share_url = ""
        self._together_revision = -1
        self._together_pending_state = None
        if refresh and getattr(self, "main_view", "") == "settings":
            self.show_settings()

    def _optional_tick(self) -> bool:
        if self.together_host:
            self.together_host.update(
                TogetherState(
                    list(self.queue),
                    max(0, self.queue_index),
                    self._playback_position_us() // 1000,
                    self._playback_is_playing(),
                )
            )
        elif self.together_client and not self._together_fetching:
            self._together_fetching = True

            def completed(state, error):
                self._together_fetching = False
                if not error and state.revision > self._together_revision:
                    self._apply_together_state(state)
                return False

            self._optional_worker("together-sync", self.together_client.fetch, completed)
        return GLib.SOURCE_CONTINUE

    def _apply_together_state(self, state: TogetherState) -> None:
        self._together_revision = state.revision
        if not state.queue:
            return
        state.index = min(state.index, len(state.queue) - 1)
        target = state.queue[state.index]
        position_ms = state.corrected_position_ms()
        current = getattr(self, "current_item", None)
        self._together_applying = True
        try:
            if current is None or current.id != target.id:
                self.queue = list(state.queue)
                self.queue_index = state.index
                self._restored_position_ms = position_ms
                self._together_pending_state = state
                self._render_queue()
                self.play_item(target)
                return
            self.queue = list(state.queue)
            self.queue_index = state.index
            if abs(self._playback_position_us() // 1000 - position_ms) > 1_500:
                self._seek_playback(position_ms * 1000)
            if state.playing != self._playback_is_playing():
                self._toggle_player()
        finally:
            self._together_applying = False

    def _optional_stream_started(self) -> None:
        state = self._together_pending_state
        if state:
            self._together_pending_state = None
            if not state.playing and self._playback_is_playing():
                GLib.timeout_add(300, lambda: self._pause() or GLib.SOURCE_REMOVE)
