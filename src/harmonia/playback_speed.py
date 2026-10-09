"""Speed and pitch for GStreamer's ``pitch`` element.

Separate, the tempo changes without the pitch and the pitch moves in
semitones. Linked, the speed drives both, like a record played faster: the
element's ``rate`` resamples, so the pitch setting no longer applies.
"""

from __future__ import annotations

MIN_SPEED, MAX_SPEED = 0.5, 2.0
MIN_SEMITONES, MAX_SEMITONES = -12, 12


def pitch_properties(speed: float, semitones: float, linked: bool) -> dict[str, float]:
    speed = max(MIN_SPEED, min(MAX_SPEED, speed))
    if linked:
        return {"tempo": 1.0, "pitch": 1.0, "rate": speed}
    semitones = max(MIN_SEMITONES, min(MAX_SEMITONES, semitones))
    return {"tempo": speed, "pitch": 2 ** (semitones / 12), "rate": 1.0}
