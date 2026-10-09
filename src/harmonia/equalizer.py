"""The equalizer's choices: built-in presets and imported AutoEQ profiles.

The preference holds a preset key ("bass") or "autoeq:<name>" for a profile
stored by storage/eq_profiles.py; equalizer_gains() turns either into the
10 band gains the player applies.
"""

from __future__ import annotations

from collections.abc import Mapping

PRESETS: dict[str, tuple[float, ...]] = {
    "flat": (0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    "bass": (6, 5, 3, 1, 0, 0, -1, -1, 0, 0),
    "vocal": (-2, -1, 0, 2, 4, 4, 2, 1, 0, -1),
    "treble": (-2, -1, 0, 0, 1, 2, 3, 4, 5, 6),
}
PROFILE_PREFIX = "autoeq:"


def profile_key(name: str) -> str:
    return f"{PROFILE_PREFIX}{name}"


def profile_of(key: str) -> str | None:
    """The profile name in a preference value, or None for a preset."""
    return key[len(PROFILE_PREFIX) :] if key.startswith(PROFILE_PREFIX) else None


def equalizer_gains(key: str, profiles: Mapping[str, tuple[float, ...]]) -> tuple[float, ...]:
    """The band gains of a preset or profile; flat when it no longer exists."""
    name = profile_of(key)
    if name is not None:
        return tuple(profiles.get(name, PRESETS["flat"]))
    return PRESETS.get(key, PRESETS["flat"])
