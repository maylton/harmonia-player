"""When a crossfade starts and how the two volumes cross, without GStreamer.

The track playing ends early for the windows, which then start the next one as
usual; the ending track keeps playing until it fades out under the new one.
"""

from __future__ import annotations

import math

MAX_SECONDS = 12
CHOICES = (0, 3, 5, 8, 12)  # 0 is off
# Tracks shorter than this many crossfades play whole.
SHORT_TRACK_FACTOR = 3
# Below this the ending track is too close to its end to fade: it is cut.
MIN_FADE_US = 300_000


def clamp_seconds(value: float) -> int:
    try:
        return max(0, min(MAX_SECONDS, round(float(value))))
    except (TypeError, ValueError):
        return 0


def should_start(position_us: int, duration_us: int, seconds: int) -> bool:
    """True once the track is within ``seconds`` of its end."""
    if seconds <= 0 or duration_us <= 0 or position_us <= 0:
        return False
    fade_us = seconds * 1_000_000
    if duration_us < SHORT_TRACK_FACTOR * fade_us:
        return False
    return duration_us - position_us <= fade_us


def fade_length_us(seconds: int, remaining_us: int) -> int:
    """How long the volumes cross: the setting, or what is left of the ending track."""
    return max(0, min(seconds * 1_000_000, remaining_us))


def gains(progress: float) -> tuple[float, float]:
    """Volumes of the ending and the starting track; equal power, so no dip midway."""
    progress = max(0.0, min(1.0, progress))
    return math.cos(progress * math.pi / 2), math.sin(progress * math.pi / 2)
