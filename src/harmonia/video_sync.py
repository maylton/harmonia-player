"""How the video layers keep a muted video playbin in step with the song.

Shared by the GTK and Qt video layers, which differ only in their widgets
and in the unit of their audio clock. Times here are in microseconds.
"""

from __future__ import annotations

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

# Polls, 40 ms apart, for the video playbin to preroll before giving up.
PREROLL_ATTEMPTS = 100
# Polls, 60 ms apart, for the first seek to land near the audio clock.
SETTLE_ATTEMPTS = 75
# Polls at which the seek is reissued at the audio clock's current position,
# in case the first one took long enough to flush that its target is stale.
RETARGET_AT = (15, 35, 55)
# Below this position the video simply starts from the beginning.
START_WITHOUT_SEEK_US = 250_000
# The first sync counts as done once video and audio are this close.
SETTLED_DRIFT_US = 1_000_000
# While playing, drift beyond this is corrected by seeking the video, at most
# once per cooldown: independent playbins share the wall clock closely enough
# that corrections are rare, and the cooldown prevents seek storms on
# fragmented MP4 while still fixing visible drift quickly.
CORRECTION_DRIFT_US = 500_000
CORRECTION_COOLDOWN_S = 1.0


def is_settled(drift_us: int) -> bool:
    return abs(drift_us) <= SETTLED_DRIFT_US


def needs_correction(drift_us: int, last_seek: float, now: float) -> bool:
    return abs(drift_us) > CORRECTION_DRIFT_US and now - last_seek >= CORRECTION_COOLDOWN_S


def seek(player: Gst.Element, target_us: int, *, accurate: bool = True) -> tuple[bool, str]:
    """Seek ``player``; an accurate seek falls back to a key-unit one.

    Returns whether a seek was accepted and which mode was used.
    """
    target_ns = max(0, int(target_us)) * 1000
    flags = Gst.SeekFlags.FLUSH | (Gst.SeekFlags.ACCURATE if accurate else Gst.SeekFlags.KEY_UNIT)
    accepted = bool(player.seek_simple(Gst.Format.TIME, flags, target_ns))
    mode = "accurate" if accurate else "key-unit"
    if not accepted and accurate:
        accepted = bool(
            player.seek_simple(
                Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, target_ns
            )
        )
        mode = "key-unit-fallback"
    return accepted, mode
