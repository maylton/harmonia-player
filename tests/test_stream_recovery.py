"""A stream that ends early resumes where it stopped, then moves on: never twice, never stuck."""

from __future__ import annotations

import pytest

from harmonia.models import LibraryItem
from harmonia.playback_state import StreamEndedEarly, StreamRecovery, stream_recovery

EARLY = StreamEndedEarly("terminou antes (200s de 215s)", 200_400_000, 215_000_000)


def test_stream_ended_early_reads_as_its_message_and_keeps_the_position():
    assert EARLY == "terminou antes (200s de 215s)"
    assert (EARLY.position_us, EARLY.duration_us) == (200_400_000, 215_000_000)


@pytest.mark.parametrize(
    ("error", "attempts", "renewable", "expected"),
    [
        # The first early end renews and resumes where the sound stopped.
        (EARLY, 0, True, StreamRecovery("renew", 200_400)),
        # The second one is the real end of the stream: next track, not a stop.
        (EARLY, 1, True, StreamRecovery("next")),
        # Local files cannot be renewed: their early end is their end.
        (EARLY, 0, False, StreamRecovery("next")),
        # Other errors renew at the current position, then fail with the reason.
        ("HTTP 403", 0, True, StreamRecovery("renew", 61_000)),
        ("HTTP 403", 1, True, StreamRecovery("fail")),
        ("arquivo corrompido", 0, False, StreamRecovery("fail")),
    ],
)
def test_stream_recovery_rule(error, attempts, renewable, expected):
    assert stream_recovery(error, attempts, 61_000, renewable=renewable) == expected


class Toasts:
    def __init__(self):
        self.titles = []

    def add_toast(self, toast):
        self.titles.append(toast.get_title())


class Button:
    def set_sensitive(self, _value):
        pass

    def set_icon_name(self, _value):
        pass


def recovering_window(monkeypatch):
    pytest.importorskip("gi")
    from harmonia import window_playback_recovery

    class Window(window_playback_recovery.WindowPlaybackRecoveryMixin):
        def __init__(self):
            self._play_request = 3
            self._stream_ready = True
            self._stream_recovery_attempts = 0
            self._pending_seek_ms = 0
            self.current_item = LibraryItem("track", "Faixa", "Artista")
            self.play_button = self.expanded_play_button = Button()
            self.toast_overlay = Toasts()
            self.next_calls = 0
            self.position_us = 61_000_000

        def _playback_position_us(self):
            return self.position_us

        def _play_next(self):
            self.next_calls += 1

    started = []
    monkeypatch.setattr(
        window_playback_recovery.threading,
        "Thread",
        lambda target, **_kwargs: type("T", (), {"start": lambda _self: started.append(target)})(),
    )
    monkeypatch.setattr(window_playback_recovery, "playback_report", lambda *_args: "relatório")
    return Window(), started


def test_gtk_resumes_an_early_ended_stream_instead_of_repeating_it(monkeypatch):
    window, started = recovering_window(monkeypatch)

    window._player_error(EARLY)

    assert window._pending_seek_ms == 200_400  # not 0: the track does not start over
    assert window._stream_recovery_attempts == 1 and len(started) == 1
    assert window.next_calls == 0


def test_gtk_moves_on_when_the_stream_ends_early_again(monkeypatch):
    window, started = recovering_window(monkeypatch)
    window._stream_recovery_attempts = 1

    window._player_error(EARLY)

    assert window.next_calls == 1  # it used to stop here, after playing twice
    assert started == [] and window.toast_overlay.titles == []


def test_gtk_resolve_failures_never_resume_the_previous_track_position(monkeypatch):
    window, _started = recovering_window(monkeypatch)

    window._play_request_error(3, "HTTP 500")

    assert window._pending_seek_ms == 0  # the 61 s belong to the track before
