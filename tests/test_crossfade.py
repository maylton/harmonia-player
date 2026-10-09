import math

import pytest

from harmonia import crossfade

gi = pytest.importorskip("gi")


def test_crossfade_starts_near_the_end_of_long_enough_tracks():
    assert crossfade.should_start(196_000_000, 200_000_000, 5)
    assert not crossfade.should_start(190_000_000, 200_000_000, 5)
    assert not crossfade.should_start(196_000_000, 200_000_000, 0)
    assert not crossfade.should_start(0, 200_000_000, 5)  # nothing played yet
    assert not crossfade.should_start(12_000_000, 14_000_000, 5)  # too short to fade
    assert crossfade.fade_length_us(5, 3_000_000) == 3_000_000
    assert crossfade.fade_length_us(5, 9_000_000) == 5_000_000
    assert crossfade.clamp_seconds("99") == crossfade.MAX_SECONDS
    assert crossfade.clamp_seconds("x") == 0


def test_volumes_cross_with_equal_power():
    assert crossfade.gains(0) == (1.0, 0.0)
    fading, rising = crossfade.gains(0.5)
    assert math.isclose(fading**2 + rising**2, 1.0)
    assert crossfade.gains(2)[1] == 1.0


class FakePlayer:
    def __init__(self):
        self.on_state = self.on_error = self.on_eos = None
        self.volume = 1.0
        self.playing = False
        self.position_us = 0
        self.duration_us = 0
        self.uri = None
        self.loudness = "unset"
        self.settings = None
        self.stopped = 0

    def play(self, uri):
        self.uri, self.playing, self.position_us = uri, True, 0

    def stop(self):
        self.playing = False
        self.stopped += 1

    def toggle(self):
        self.playing = not self.playing

    def seek(self, position_us):
        self.position_us = position_us
        return True

    def set_track_loudness(self, loudness_db):
        self.loudness = loudness_db

    def apply_audio_settings(self, **settings):
        self.settings = settings

    def close(self):
        pass

    def _source_uri(self, uri):
        return f"relay:{uri}"


class FakeGLib:
    SOURCE_REMOVE = False
    SOURCE_CONTINUE = True

    @staticmethod
    def idle_add(callback, *args):
        callback(*args)

    @staticmethod
    def timeout_add(_interval, _callback, *_args):
        return 1

    @staticmethod
    def source_remove(_source):
        return True


@pytest.fixture
def setup(monkeypatch):
    from harmonia import crossfade_player

    clock = [100.0]
    monkeypatch.setattr(crossfade_player, "GLib", FakeGLib)
    monkeypatch.setattr(crossfade_player.time, "monotonic", lambda: clock[0])
    events = []
    player = crossfade_player.CrossfadingPlayer(
        lambda playing: events.append(("state", playing)),
        lambda error: events.append(("error", error)),
        lambda: events.append(("eos",)),
        factory=FakePlayer,
    )
    player.apply_audio_settings(normalization=True)
    player.set_crossfade(5)
    first = player._active
    first.play("first")
    first.duration_us, first.position_us = 200_000_000, 196_000_000
    return player, first, events, clock


def test_the_next_track_fades_in_over_the_ending_one(setup):
    player, first, events, clock = setup
    player.check_crossfade()
    player.check_crossfade()
    assert events == [("eos",)]  # the frontend moves on once, early

    # The frontend starts the next track as usual.
    player.set_track_loudness(2.0)
    assert first.loudness == "unset"  # the ending track keeps its volume
    player.play("second")
    second = player._active
    assert second is not first and second.uri == "second"
    assert (second.volume, second.loudness) == (0.0, 2.0)
    assert second.settings == {"normalization": True}
    assert first.playing and player.duration_us == second.duration_us

    # The volumes cross once the new track plays, over what is left of the old one.
    first.on_state(False)
    second.on_state(True)
    assert events[-1] == ("state", True)
    assert player._ramp_us == 4_000_000
    clock[0] += 2.0
    player._step()
    assert math.isclose(first.volume, second.volume)
    clock[0] += 2.0
    player._step()
    assert not first.playing and first.stopped == 1
    assert second.volume == 1.0

    # The next end is reported normally, and the spare player is reused.
    second.on_eos()
    assert events[-1] == ("eos",)
    assert len(player._players) == 2


def test_the_ending_track_ending_first_finishes_the_fade(setup):
    player, first, events, _clock = setup
    player.check_crossfade()
    player.play("second")
    player._active.on_state(True)
    first.on_eos()
    assert player._outgoing is None and player._active.volume == 1.0
    assert events == [("eos",), ("state", True)]


def test_without_a_next_track_the_last_one_plays_to_its_end(setup):
    player, first, events, _clock = setup
    player.check_crossfade()
    first.on_eos()  # its real end: the frontend already had it
    assert events == [("eos",)]
    player.play("later")
    assert player._active is first and first.uri == "later"


def test_user_actions_cut_the_fading_track(setup):
    player, first, _events, _clock = setup
    player.check_crossfade()
    player.play("second")
    player._active.on_state(True)
    player.toggle()
    assert not first.playing and player._outgoing is None


def test_no_crossfade_when_off_or_not_allowed(setup):
    player, first, events, _clock = setup
    player.crossfade_allowed = lambda: False
    player.check_crossfade()
    assert events == []
    player.crossfade_allowed = lambda: True
    player.set_crossfade(0)
    player.check_crossfade()
    player.play("second")
    assert player._active is first and first.uri == "second"
    assert player._source_uri("x") == "relay:x"  # the rest of NativePlayer's interface
