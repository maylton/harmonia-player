import pytest

pytest.importorskip("gi")

from harmonia import video_sync


def test_first_sync_settles_within_a_second():
    assert video_sync.is_settled(0)
    assert video_sync.is_settled(-1_000_000) and video_sync.is_settled(1_000_000)
    assert not video_sync.is_settled(1_000_001)


def test_drift_is_corrected_past_half_a_second_at_most_once_a_second():
    assert not video_sync.needs_correction(500_000, last_seek=0.0, now=10.0)
    assert video_sync.needs_correction(500_001, last_seek=0.0, now=10.0)
    assert video_sync.needs_correction(-600_000, last_seek=9.0, now=10.0)
    assert not video_sync.needs_correction(-600_000, last_seek=9.5, now=10.0)


class Player:
    def __init__(self, *accepts):
        self.accepts = list(accepts)
        self.calls = []

    def seek_simple(self, fmt, flags, position):
        self.calls.append((flags, position))
        return self.accepts.pop(0)


def test_an_accurate_seek_falls_back_to_a_key_unit_seek():
    from gi.repository import Gst

    player = Player(True)
    assert video_sync.seek(player, 1_500_000) == (True, "accurate")
    assert player.calls == [(Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE, 1_500_000_000)]

    player = Player(False, True)
    assert video_sync.seek(player, 2_000) == (True, "key-unit-fallback")
    assert player.calls[1] == (Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, 2_000_000)

    player = Player(False)
    assert video_sync.seek(player, -5, accurate=False) == (False, "key-unit")
    assert player.calls == [(Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, 0)]
