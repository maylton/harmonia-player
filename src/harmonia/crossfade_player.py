"""Crossfade between tracks with two GStreamer players behind one interface.

CrossfadingPlayer offers NativePlayer's interface, so both frontends keep
using ``self.player`` as before. With a crossfade set, it reports the end of
the track a few seconds early (``on_eos``); when the frontend then plays the
next track, that track starts on the second player while the first one fades
out, and the two swap roles. Anything else the frontend does (pause, seek,
stop, a source swap) cuts the fading track at once. Each player sends its own
output to the system, which mixes them on Windows and Linux alike.

Only the active player reaches the frontend's callbacks; a second player is
created the first time a crossfade happens.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from functools import partial

from gi.repository import GLib

from . import crossfade

LOGGER = logging.getLogger(__name__)
WATCH_MS = 250
RAMP_MS = 50


class CrossfadingPlayer:
    def __init__(self, on_state=None, on_error=None, on_eos=None, *, factory=None) -> None:
        if factory is None:
            from .player import NativePlayer

            factory = NativePlayer
        self.on_state = on_state
        self.on_error = on_error
        self.on_eos = on_eos
        # Set by the frontend: False while a crossfade would be wrong (video, cast).
        self.crossfade_allowed: Callable[[], bool] = lambda: True
        self._factory = factory
        self._players: list = []
        self._audio_settings: dict = {}
        self._active = self._new_player()
        self._outgoing = None
        self._awaiting_next = False
        self._ramp_pending = False
        self._seconds = 0
        self._loudness: float | None = None
        self._user_volume = self._active.volume
        self._watch_source = 0
        self._ramp_source = 0
        self._ramp_started = 0.0
        self._ramp_us = 0

    def __getattr__(self, name: str):
        # Everything else NativePlayer offers (video_sink, _source_uri, ...).
        active = self.__dict__.get("_active")
        if active is None:
            raise AttributeError(name)
        return getattr(active, name)

    # Settings

    @property
    def crossfade_seconds(self) -> int:
        return self._seconds

    def set_crossfade(self, seconds: float) -> None:
        self._seconds = crossfade.clamp_seconds(seconds)
        if self._seconds and not self._watch_source:
            self._watch_source = GLib.timeout_add(WATCH_MS, self._watch)

    def apply_audio_settings(self, **settings) -> None:
        self._audio_settings = settings
        for player in self._players:
            player.apply_audio_settings(**settings)

    def set_track_loudness(self, loudness_db: float | None) -> None:
        """The loudness of the next track to play; the fading one keeps its own."""
        self._loudness = loudness_db
        if not self._awaiting_next:
            self._active.set_track_loudness(loudness_db)

    # Transport

    def play(self, uri: str) -> None:
        outgoing = self._active
        if self._awaiting_next and self._seconds and outgoing.playing and self.crossfade_allowed():
            remaining = outgoing.duration_us - outgoing.position_us
            if crossfade.fade_length_us(self._seconds, remaining) >= crossfade.MIN_FADE_US:
                self._start_fade(uri)
                return
        self._awaiting_next = False
        self._cut()
        self._active.set_track_loudness(self._loudness)
        self._active.volume = self._user_volume
        self._active.play(uri)

    def replace(self, *args, **kwargs) -> None:
        self._awaiting_next = False
        self._cut()
        self._active.replace(*args, **kwargs)

    def toggle(self) -> None:
        self._cut()
        self._active.toggle()

    def stop(self) -> None:
        self._awaiting_next = False
        self._cut()
        self._active.stop()

    def seek(self, position_us: int) -> bool:
        self._awaiting_next = False
        self._cut()
        return self._active.seek(position_us)

    def close(self) -> None:
        for source in (self._watch_source, self._ramp_source):
            if source:
                GLib.source_remove(source)
        self._watch_source = self._ramp_source = 0
        for player in self._players:
            player.close()

    @property
    def volume(self) -> float:
        return self._user_volume

    @volume.setter
    def volume(self, value: float) -> None:
        self._user_volume = max(0.0, min(1.0, float(value)))
        if self._outgoing is None:
            self._active.volume = self._user_volume
        elif self._ramp_pending:
            self._outgoing.volume = self._user_volume
        # During the ramp, _step applies it on the next tick.

    @property
    def playing(self) -> bool:
        return self._active.playing

    @property
    def position_us(self) -> int:
        return self._active.position_us

    @property
    def duration_us(self) -> int:
        return self._active.duration_us

    # Crossfade

    def _new_player(self):
        player = self._factory()
        player.on_state = partial(self._player_state, player)
        player.on_error = partial(self._player_error, player)
        player.on_eos = partial(self._player_eos, player)
        if self._audio_settings:
            player.apply_audio_settings(**self._audio_settings)
        self._players.append(player)
        return player

    def _standby(self):
        for player in self._players:
            if player is not self._active:
                return player
        return self._new_player()

    def _watch(self) -> bool:
        if not self._seconds:
            self._watch_source = 0
            return GLib.SOURCE_REMOVE
        self.check_crossfade()
        return GLib.SOURCE_CONTINUE

    def check_crossfade(self) -> None:
        """End the track early for the frontend once it is near its end."""
        active = self._active
        if (
            self._awaiting_next
            or self._outgoing is not None
            or not active.playing
            or not self.crossfade_allowed()
            or not crossfade.should_start(active.position_us, active.duration_us, self._seconds)
        ):
            return
        self._awaiting_next = True
        if self.on_eos:
            GLib.idle_add(self.on_eos)

    def _start_fade(self, uri: str) -> None:
        self._cut()
        incoming = self._standby()
        incoming.set_track_loudness(self._loudness)
        incoming.volume = 0.0
        self._outgoing, self._active = self._active, incoming
        self._awaiting_next = False
        # The volumes cross once the new track is actually playing.
        self._ramp_pending = True
        incoming.play(uri)

    def _begin_ramp(self) -> None:
        self._ramp_pending = False
        outgoing = self._outgoing
        remaining = outgoing.duration_us - outgoing.position_us
        self._ramp_us = crossfade.fade_length_us(self._seconds, remaining)
        if self._ramp_us < crossfade.MIN_FADE_US:
            self._finish_fade()
            return
        self._ramp_started = time.monotonic()
        self._ramp_source = GLib.timeout_add(RAMP_MS, self._step)

    def _step(self) -> bool:
        if self._outgoing is None:
            self._ramp_source = 0
            return GLib.SOURCE_REMOVE
        progress = (time.monotonic() - self._ramp_started) * 1_000_000 / self._ramp_us
        fading, rising = crossfade.gains(progress)
        self._outgoing.volume = self._user_volume * fading
        self._active.volume = self._user_volume * rising
        if progress < 1:
            return GLib.SOURCE_CONTINUE
        self._ramp_source = 0
        self._finish_fade()
        return GLib.SOURCE_REMOVE

    def _finish_fade(self) -> None:
        if self._ramp_source:
            GLib.source_remove(self._ramp_source)
            self._ramp_source = 0
        self._ramp_pending = False
        outgoing, self._outgoing = self._outgoing, None
        if outgoing is not None:
            outgoing.stop()
        self._active.volume = self._user_volume

    _cut = _finish_fade

    # Callbacks of the two players: only the active one reaches the frontend.

    def _player_state(self, player, playing: bool):
        if player is not self._active:
            return False
        if playing and self._ramp_pending:
            self._begin_ramp()
        return self.on_state(playing) if self.on_state else False

    def _player_error(self, player, error: str):
        if player is not self._active:
            LOGGER.debug("Erro na faixa que saía no crossfade: %s", error)
            if player is self._outgoing:
                self._finish_fade()
            return False
        return self.on_error(error) if self.on_error else False

    def _player_eos(self, player):
        if player is self._outgoing:
            self._finish_fade()
            return False
        if player is not self._active:
            return False
        if self._awaiting_next:
            # The frontend already moved on when the crossfade began.
            self._awaiting_next = False
            return False
        return self.on_eos() if self.on_eos else False
