"""Material Design 3 colour roles for the Material Design 3 theme.

The roles come from the desktop when it publishes a Material scheme: Caelestia
Shell writes the one generated from the wallpaper to
``~/.local/state/caelestia/scheme.json`` and rewrites it whenever the
wallpaper or the scheme changes. Without one the theme keeps Material's
baseline scheme, tinted with the desktop accent when there is one (GNOME,
elementary OS, Windows).

Roles are Material's names (``primary``, ``onSecondaryContainer``...); the
theme maps them to Harmonia's palette tokens and exposes them to CSS as
``@md_<role>`` (``@md_on_secondary_container``).
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

LOGGER = logging.getLogger(__name__)

# The roles the theme reads; a scheme missing any of them is not used.
ROLES = (
    "primary",
    "onPrimary",
    "primaryContainer",
    "onPrimaryContainer",
    "secondary",
    "onSecondary",
    "secondaryContainer",
    "onSecondaryContainer",
    "tertiary",
    "onTertiary",
    "error",
    "onError",
    "errorContainer",
    "onErrorContainer",
    "surface",
    "onSurface",
    "surfaceVariant",
    "onSurfaceVariant",
    "surfaceContainerLowest",
    "surfaceContainerLow",
    "surfaceContainer",
    "surfaceContainerHigh",
    "surfaceContainerHighest",
    "outline",
    "outlineVariant",
    "inverseSurface",
    "inverseOnSurface",
    "shadow",
)
_HEX = re.compile(r"#?([0-9a-fA-F]{6})")


def css_name(role: str) -> str:
    """``onSecondaryContainer`` -> ``md_on_secondary_container``."""
    return "md_" + re.sub(r"(?<!^)(?=[A-Z])", "_", role).lower()


def caelestia_scheme_path() -> Path:
    """Caelestia's scheme on the host, also from inside the Flatpak sandbox."""
    state = os.environ.get("HOST_XDG_STATE_HOME") or os.environ.get("XDG_STATE_HOME")
    if os.path.exists("/.flatpak-info"):
        # XDG_STATE_HOME points into the sandbox there.
        state = os.environ.get("HOST_XDG_STATE_HOME")
    return Path(state or Path.home() / ".local" / "state") / "caelestia" / "scheme.json"


def parse_scheme(data) -> tuple[dict[str, str], bool] | None:
    """The roles of a Caelestia scheme and whether it is dark; None if unusable."""
    if not isinstance(data, dict) or not isinstance(data.get("colours"), dict):
        return None
    colours = data["colours"]
    roles: dict[str, str] = {}
    for role in ROLES:
        match = _HEX.fullmatch(str(colours.get(role, "")))
        if match is None:
            return None
        roles[role] = "#" + match.group(1).lower()
    return roles, str(data.get("mode", "dark")).lower() != "light"


def load_caelestia_scheme(path: Path | None = None) -> tuple[dict[str, str], bool] | None:
    path = path or caelestia_scheme_path()
    try:
        return parse_scheme(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        LOGGER.debug("Esquema do Caelestia ilegível em %s", path, exc_info=True)
        return None


def _channels(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def mix(color: str, other: str, amount: float) -> str:
    """``color`` moved ``amount`` (0-1) of the way to ``other``."""
    channels = (
        round(a + (b - a) * amount) for a, b in zip(_channels(color), _channels(other), strict=True)
    )
    return "#" + "".join(f"{channel:02x}" for channel in channels)


def with_accent(roles: dict[str, str], accent: str, *, dark: bool) -> dict[str, str]:
    """Baseline roles retinted around a single desktop accent colour.

    The primary roles take the accent itself; the secondary ones, which fill
    tonal buttons and the empty part of sliders, mix it into the surface the
    way Material's tonal palettes sit between the two.
    """
    surface, on_surface = roles["surface"], roles["onSurface"]
    on_accent = "#000000" if sum(_channels(accent)) > 382 else "#ffffff"
    return roles | {
        "primary": accent,
        "onPrimary": on_accent,
        "primaryContainer": mix(accent, surface, 0.55 if dark else 0.7),
        "onPrimaryContainer": on_surface,
        "secondary": mix(accent, on_surface, 0.45),
        "onSecondary": surface,
        "secondaryContainer": mix(accent, surface, 0.72 if dark else 0.8),
        "onSecondaryContainer": on_surface,
    }


def palette(roles: dict[str, str]) -> dict[str, str]:
    """Harmonia's palette tokens (theming.TOKENS) from Material roles."""
    return {
        "bg": roles["surface"],
        "sidebar_bg": roles["surfaceContainer"],
        "headerbar_bg": roles["surfaceContainer"],
        "border": roles["outlineVariant"],
        "hover_bg": roles["surfaceContainerHigh"],
        "selected_bg": roles["secondaryContainer"],
        "chip_bg": roles["surfaceContainerHigh"],
        "chip_hover_bg": roles["surfaceContainerHighest"],
        "fg": roles["onSurface"],
        "fg_secondary": roles["onSurface"],
        "fg_tertiary": roles["onSurfaceVariant"],
        "fg_muted": roles["onSurfaceVariant"],
        "fg_subtle": roles["onSurfaceVariant"],
        "fg_dim": roles["outline"],
        "overlay": roles["onSurface"],
        "shadow": roles["shadow"],
        "inverse_bg": roles["primary"],
        "inverse_fg": roles["onPrimary"],
        # Material's hover state layer: the content colour at 8%.
        "inverse_hover_bg": mix(roles["primary"], roles["onPrimary"], 0.08),
        "destructive_fg": roles["error"],
        "destructive_bg": roles["error"],
        "destructive_border": roles["error"],
        "warning_bg": roles["tertiary"],
        "warning_fg": roles["tertiary"],
    }


def accent(roles: dict[str, str]) -> dict[str, str]:
    """libadwaita's accent (theming.ACCENT_TOKENS) is Material's primary."""
    return {
        "accent_bg": roles["primary"],
        "accent_fg": roles["onPrimary"],
        "accent": roles["primary"],
    }
