"""Continuous animations: at most 60 draws a second, and no endless tweens."""

import pytest

pytest.importorskip("gi")
from harmonia.gtk_expressive import FrameLoop


class Widget:
    def __init__(self):
        self.draws, self.mapped = 0, True

    def connect(self, *_args):
        return 1

    def get_mapped(self):
        return self.mapped

    def queue_draw(self):
        self.draws += 1


def test_running_loops_share_one_sixty_hertz_timer(monkeypatch):
    from harmonia import gtk_expressive

    timers, removed = [], []
    monkeypatch.setattr(
        gtk_expressive.GLib, "timeout_add", lambda ms, callback: timers.append(ms) or 7
    )
    monkeypatch.setattr(gtk_expressive.GLib, "source_remove", removed.append)
    clock = iter((1_000_000, 1_016_000))
    monkeypatch.setattr(gtk_expressive.GLib, "get_monotonic_time", lambda: next(clock))
    cover, slider, steps = Widget(), Widget(), []
    loops = FrameLoop(cover, steps.append), FrameLoop(slider, lambda _elapsed: None)

    for loop in loops:
        loop.set_running(True)
    assert timers == [gtk_expressive.FRAME_INTERVAL_MS] and 1000 / timers[0] >= 60
    for _ in range(2):
        assert FrameLoop._frame_all()
    assert steps == [0, 16_000] and cover.draws == slider.draws == 2
    loops[0].set_running(False)
    assert not removed  # the slider still runs
    slider.mapped = False
    loops[1]._update()
    assert removed == [7] and not FrameLoop._running


def test_the_playing_progress_moves_without_a_tween_on_every_frame():
    from gi.repository import Gtk

    from harmonia.gtk_expressive import ExpressiveSlider

    adjustment = Gtk.Adjustment(lower=0, upper=100, value=0)
    slider = ExpressiveSlider(adjustment, wavy=True)
    slider.get_width = lambda: 400
    eased = []
    slider.fill.animate_to = eased.append

    adjustment.set_value(0.5)  # playback's half-second step: two pixels
    assert slider.fill.value == pytest.approx(0.005) and not eased
    adjustment.set_value(60)  # a seek eases
    assert eased == [pytest.approx(0.6)]


def test_a_title_too_long_goes_round_without_widening_its_line():
    from gi.repository import Gtk

    from harmonia.gtk_expressive import MarqueeLabel

    title = MarqueeLabel()
    title.set_label("Um título muito longo para caber na linha do player expandido")
    assert title.measure(Gtk.Orientation.HORIZONTAL, -1)[:2] == (0, 0)

    title._text_width = 500  # wider than its line
    title._advance(1_900_000)
    assert title._offset == 0  # still resting at its start
    title._advance(100_000)
    title._advance(1_000_000)
    assert title._offset == pytest.approx(MarqueeLabel.SPEED)
    title._advance(round((500 + MarqueeLabel.GAP) / MarqueeLabel.SPEED * 1_000_000))
    # Its copy has taken its place: back at the start, resting again.
    assert title._offset == 0 and title._rest == MarqueeLabel.PAUSE_US
