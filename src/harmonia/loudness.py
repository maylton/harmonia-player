"""Volume normalisation per track, from the loudness YouTube measures.

YouTube Music reports for each track how far it is above the loudness it
normalises to, about -14 LUFS (``playerConfig.audioConfig.loudnessDb``;
positive is louder). Like YouTube, Harmonia only turns loud tracks down; the
level then shifts every track up or down.

The gain goes to GStreamer's rgvolume as its "fallback" gain, the one it uses
for streams without ReplayGain tags. Local files with tags keep them: their
reference is -18 LUFS, so the pre-amplification brings them level with the
streams. Without a known loudness a track only gets the level.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

LEVELS: dict[str, float] = {"soft": -4.0, "standard": 0.0, "loud": 3.0}
DEFAULT_LEVEL = "standard"
REPLAYGAIN_TO_YOUTUBE_DB = 4.0
MAX_CUT_DB = -20.0
# Room above full scale for the level's boost; rglimiter keeps peaks in range.
HEADROOM_DB = 6.0


@dataclass(frozen=True, slots=True)
class ReplayGainSettings:
    """Properties for rgvolume: result = (tag gain or fallback_gain) + pre_amp."""

    pre_amp: float
    fallback_gain: float
    headroom: float
    limiter: bool


OFF = ReplayGainSettings(pre_amp=0.0, fallback_gain=0.0, headroom=0.0, limiter=False)


def loudness_from_player(
    payload: Mapping[str, Any], audio_format: Mapping | None = None
) -> float | None:
    """The track's loudness in dB relative to YouTube's reference, if reported.

    Some clients (iOS, visionOS) only report it per format, or as the absolute
    loudness next to the target.
    """
    audio_config = (payload.get("playerConfig") or {}).get("audioConfig") or {}
    for value in (audio_config.get("loudnessDb"), (audio_format or {}).get("loudnessDb")):
        if _number(value):
            return float(value)
    absolute = audio_config.get("trackAbsoluteLoudnessLkfs")
    target = audio_config.get("loudnessTargetLkfs")
    if _number(absolute) and _number(target):
        return float(absolute) - float(target)
    return None


def _number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def track_gain(loudness_db: float | None, level: str = DEFAULT_LEVEL) -> float:
    """The gain in dB a track plays with: loud tracks turned down, then the level."""
    offset = LEVELS.get(level, LEVELS[DEFAULT_LEVEL])
    reduction = 0.0 if loudness_db is None else max(MAX_CUT_DB, min(0.0, -loudness_db))
    return reduction + offset


def replaygain_settings(
    enabled: bool, level: str = DEFAULT_LEVEL, loudness_db: float | None = None
) -> ReplayGainSettings:
    """rgvolume properties for the track playing; OFF leaves streams untouched."""
    if not enabled:
        return OFF
    offset = LEVELS.get(level, LEVELS[DEFAULT_LEVEL])
    pre_amp = REPLAYGAIN_TO_YOUTUBE_DB + offset
    return ReplayGainSettings(
        pre_amp=pre_amp,
        fallback_gain=track_gain(loudness_db, level) - pre_amp,
        headroom=HEADROOM_DB,
        limiter=True,
    )
