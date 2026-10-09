"""Listen Together in the KDE frontend: hosting a session or following one."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QTimer

from .i18n import _
from .qt_integration_context import IntegrationContext, Job
from .together import TogetherClient, TogetherHost, TogetherState


class TogetherBridge:
    def __init__(self, context: IntegrationContext, changed: Callable[[], None]) -> None:
        self.context = context
        self.changed = changed
        self.host: TogetherHost | None = None
        self.client: TogetherClient | None = None
        self.share_url = ""
        self._revision = -1
        self._fetching = False
        self._generation = 0
        self._pending_playing: bool | None = None

    @property
    def active(self) -> bool:
        return bool(self.host or self.client)

    @property
    def status(self) -> str:
        if self.host:
            return _("Você está compartilhando a reprodução")
        if self.client:
            return _("Sincronizado com o anfitrião")
        return _("Nenhuma sessão ativa")

    def create(self) -> None:
        self.leave()
        try:
            self.host = TogetherHost()
            self.share_url = self.host.share_url()
        except OSError as exc:
            self.context.set_status(
                _("Não foi possível criar a sessão: {error}").format(error=exc), error=True
            )
            return
        self.changed()
        self.context.set_status(_("Sessão Listen Together criada."))

    def join(self, share_url: str) -> None:
        try:
            client = TogetherClient(share_url)
        except ValueError as exc:
            self.context.set_status(str(exc), error=True)
            return
        self.leave()
        generation = self._generation
        self.context.set_status(_("Entrando na sessão Listen Together…"))
        self.context.run(
            Job(
                "together-join",
                lambda state: self._joined(generation, client, state),
                None,
                _("Não foi possível entrar na sessão"),
            ),
            client.fetch,
        )

    def leave(self) -> None:
        self._generation += 1
        if self.host:
            self.host.close()
        self.host = None
        self.client = None
        self.share_url = ""
        self._revision = -1
        self._fetching = False
        self._pending_playing = None
        self.changed()

    def tick(self) -> None:
        """Publish the playback to the guests, or fetch the host's."""
        playback = self.context.playback
        if self.host:
            self.host.update(
                TogetherState(
                    list(playback.queue),
                    max(0, playback.queue_index),
                    playback.position,
                    playback.playing,
                )
            )
            return
        if self.client and not self._fetching:
            self._fetching = True
            client = self.client
            self.context.run(
                Job("together-sync", lambda state: self._synced(client, state), self._sync_failed),
                client.fetch,
            )

    def track_started(self) -> None:
        """A shared state paused at the host stays paused here once its track loads."""
        pending, self._pending_playing = self._pending_playing, None
        if pending is False:
            QTimer.singleShot(300, self._pause)

    def _pause(self) -> None:
        if self.context.playback.playing:
            self.context.playback.toggle_playback()

    def _joined(self, generation: int, client: TogetherClient, state: TogetherState) -> None:
        if generation != self._generation:
            return
        self.client = client
        self._revision = -1
        self.apply(state)
        self.changed()
        self.context.set_status(_("Listen Together conectado."))

    def _synced(self, client: TogetherClient, state: TogetherState) -> None:
        self._fetching = False
        if client is self.client:
            self.apply(state)

    def _sync_failed(self, _error: str) -> None:
        self._fetching = False

    def apply(self, state: TogetherState) -> None:
        if state.revision <= self._revision:
            return
        self._revision = state.revision
        if not state.queue:
            return
        playback = self.context.playback
        index = min(state.index, len(state.queue) - 1)
        position_ms = state.corrected_position_ms()
        current = playback.current_item
        if current is None or current.id != state.queue[index].id:
            self._pending_playing = state.playing
            playback.load_shared_state(state.queue, index, position_ms)
            return
        playback.queue = list(state.queue)
        playback.queue_index = index
        playback.queueChanged.emit()
        if abs(playback.position - position_ms) > 1500:
            playback.seek(position_ms)
        if state.playing != playback.playing:
            playback.toggle_playback()
