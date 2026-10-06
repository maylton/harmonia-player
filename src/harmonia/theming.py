"""Frontend-neutral theme model shared by the GTK and Qt frontends.

A theme is data: palettes of semantic colour tokens (one per light/dark
variant), optional accent and libadwaita surface overrides, a corner scale and
an optional font family. Each frontend translates these tokens into its own
styling technology; this module only knows how to produce GTK CSS.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import cache, lru_cache
from pathlib import Path

from . import host

THEMES_DIR = Path(__file__).with_name("themes")
DEFAULT_THEME = "harmonia"
VARIANTS = ("theme", "system", "light", "dark")
PLATFORMS = ("linux", "windows")

# Semantic colour roles used by style.css as @harmonia_<token>.
TOKENS = (
    "bg",  # page background
    "sidebar_bg",  # sidebar, player bar, segmented controls
    "headerbar_bg",
    "border",  # separators and hairlines
    "hover_bg",
    "selected_bg",
    "chip_bg",
    "chip_hover_bg",
    "fg",  # primary text and icons
    "fg_secondary",
    "fg_tertiary",
    "fg_muted",
    "fg_subtle",
    "fg_dim",  # least prominent readable text
    "overlay",  # tinted with alpha() for hover/borders over surfaces
    "shadow",
    "inverse_bg",  # high-emphasis pill buttons (play, primary actions)
    "inverse_fg",
    "inverse_hover_bg",
    "destructive_fg",
    "destructive_bg",
    "destructive_border",
    "warning_bg",
    "warning_fg",
)
ACCENT_TOKENS = ("accent_bg", "accent_fg", "accent")

# libadwaita surfaces a theme may restyle so stock widgets (rows, entries,
# popovers, dialogs) match its palette. Values are Harmonia tokens.
ADWAITA_SURFACES = {
    "window_bg_color": "bg",
    "window_fg_color": "fg",
    "view_bg_color": "bg",
    "view_fg_color": "fg",
    "headerbar_bg_color": "headerbar_bg",
    "headerbar_fg_color": "fg",
    "sidebar_bg_color": "sidebar_bg",
    "sidebar_fg_color": "fg",
    "popover_bg_color": "headerbar_bg",
    "popover_fg_color": "fg",
    "dialog_bg_color": "bg",
    "dialog_fg_color": "fg",
}
# Floating surfaces get no window material behind them, so they keep the
# opaque palette even when the window itself is translucent.
OPAQUE_SURFACES = ("popover_bg_color", "dialog_bg_color")
TRANSLUCENT_VALUE = re.compile(
    r"#[0-9a-f]{6}|transparent|rgba\(\s*\d+,\s*\d+,\s*\d+,\s*[0-9.]+\s*\)"
)
ADWAITA_ACCENT = {
    "accent_bg_color": "accent_bg",
    "accent_fg_color": "accent_fg",
    "accent_color": "accent",
}

# Accent presets from the elementary palette. accent_bg/accent_fg colour filled
# controls; "accent" is the standalone tone for text and icons, per variant.
ACCENT_PRESETS: dict[str, dict[str, str]] = {
    "red": {"accent_bg": "#c6262e", "accent_fg": "#ffffff", "dark": "#ed5353", "light": "#a10705"},
    "orange": {
        "accent_bg": "#cc3b02",
        "accent_fg": "#ffffff",
        "dark": "#ffa154",
        "light": "#cc3b02",
    },
    "yellow": {
        "accent_bg": "#f9c440",
        "accent_fg": "#333333",
        "dark": "#ffe16b",
        "light": "#ad5f00",
    },
    "green": {
        "accent_bg": "#3a9104",
        "accent_fg": "#ffffff",
        "dark": "#9bdb4d",
        "light": "#3a9104",
    },
    "mint": {"accent_bg": "#0e9a83", "accent_fg": "#ffffff", "dark": "#43d6b5", "light": "#0b7a68"},
    "blue": {"accent_bg": "#3689e6", "accent_fg": "#ffffff", "dark": "#64baff", "light": "#0d52bf"},
    "purple": {
        "accent_bg": "#a56de2",
        "accent_fg": "#ffffff",
        "dark": "#cd9ef7",
        "light": "#7239b3",
    },
    "pink": {"accent_bg": "#de3e80", "accent_fg": "#ffffff", "dark": "#f4679d", "light": "#bc245d"},
    "brown": {
        "accent_bg": "#715344",
        "accent_fg": "#ffffff",
        "dark": "#a3907c",
        "light": "#57392d",
    },
    "slate": {
        "accent_bg": "#485a6c",
        "accent_fg": "#ffffff",
        "dark": "#95a3ab",
        "light": "#273445",
    },
}
ACCENTS = ("theme", *ACCENT_PRESETS)


def fluent_accent(palette: list[str] | None, *, dark: bool) -> dict[str, str] | None:
    """Map the Windows accent palette to accent tokens the way Fluent does.

    ``palette`` lists the system shades from lightest to darkest (Light3,
    Light2, Light1, base, Dark1, Dark2, Dark3). Dark mode fills controls with
    Light2 under black text and writes accent text in Light3; light mode fills
    with Dark1 under white text and writes in Dark2.
    """
    if not palette or len(palette) < 7:
        return None
    if dark:
        return {"accent_bg": palette[1], "accent_fg": "#000000", "accent": palette[0]}
    return {"accent_bg": palette[4], "accent_fg": "#ffffff", "accent": palette[5]}


def accent_preset(name: str, *, dark: bool) -> dict[str, str] | None:
    preset = ACCENT_PRESETS.get(name)
    if not preset:
        return None
    return {
        "accent_bg": preset["accent_bg"],
        "accent_fg": preset["accent_fg"],
        "accent": preset["dark" if dark else "light"],
    }


_RADIUS = re.compile(r"(border-radius:\s*)([^;}]+)")
_PIXELS = re.compile(r"(\d+(?:\.\d+)?)px")
_PILL_RADIUS = 999


class ThemeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Theme:
    id: str
    name: str
    description: str
    default_variant: str
    palettes: dict[str, dict[str, str]]
    accent: dict[str, dict[str, str]] = field(default_factory=dict)
    restyle_adwaita: bool = False
    corner_scale: float = 1.0
    font_family: str = ""
    stylesheet: str = ""  # optional structural layer in themes/, applied after style.css
    platforms: tuple[str, ...] = ()  # empty: offered everywhere
    system_accent: bool = False  # follow the desktop's exact accent palette when known
    # A window material (Mica, Acrylic) may sit behind the window; "translucent"
    # holds the tokens that turn see-through while it does, per variant.
    backdrop: bool = False
    translucent: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return not self.platforms or host.PLATFORM in self.platforms

    @classmethod
    def from_dict(cls, data: dict) -> Theme:
        try:
            theme = cls(
                id=str(data["id"]),
                name=str(data["name"]),
                description=str(data.get("description", "")),
                default_variant=str(data.get("default_variant", "system")),
                palettes={k: dict(v) for k, v in data["palettes"].items()},
                accent={k: dict(v) for k, v in data.get("accent", {}).items()},
                restyle_adwaita=bool(data.get("restyle_adwaita", False)),
                corner_scale=float(data.get("corner_scale", 1.0)),
                font_family=str(data.get("font_family", "")),
                stylesheet=str(data.get("stylesheet", "")),
                platforms=tuple(str(name) for name in data.get("platforms", ())),
                system_accent=bool(data.get("system_accent", False)),
                backdrop=bool(data.get("backdrop", False)),
                translucent={k: dict(v) for k, v in data.get("translucent", {}).items()},
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ThemeError(f"tema inválido: {exc}") from exc
        theme.validate()
        return theme

    def validate(self) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", self.id):
            raise ThemeError(f"id de tema inválido: {self.id!r}")
        if self.default_variant not in {"system", "light", "dark"}:
            raise ThemeError(f"{self.id}: default_variant inválido")
        if set(self.palettes) != {"light", "dark"}:
            raise ThemeError(f"{self.id}: precisa das paletas light e dark")
        for variant, palette in self.palettes.items():
            missing = set(TOKENS) - set(palette)
            unknown = set(palette) - set(TOKENS)
            if missing or unknown:
                raise ThemeError(
                    f"{self.id}/{variant}: faltando {sorted(missing)}, desconhecidos {sorted(unknown)}"
                )
        for variant, accent in self.accent.items():
            if variant not in self.palettes or set(accent) != set(ACCENT_TOKENS):
                raise ThemeError(f"{self.id}/{variant}: acento precisa de {ACCENT_TOKENS}")
        if self.stylesheet and not re.fullmatch(r"[a-z0-9-]+\.css", self.stylesheet):
            raise ThemeError(f"{self.id}: stylesheet inválido")
        if not 0 <= self.corner_scale <= 2:
            raise ThemeError(f"{self.id}: corner_scale fora de 0 a 2")
        if set(self.platforms) - set(PLATFORMS):
            raise ThemeError(f"{self.id}: plataformas válidas são {PLATFORMS}")
        if self.translucent and not self.backdrop:
            raise ThemeError(f"{self.id}: translucent exige backdrop")
        for variant, colors in self.translucent.items():
            if variant not in self.palettes or set(colors) - set(TOKENS):
                raise ThemeError(f"{self.id}/{variant}: tokens translúcidos inválidos")
            if not all(TRANSLUCENT_VALUE.fullmatch(value) for value in colors.values()):
                raise ThemeError(f"{self.id}/{variant}: cor translúcida inválida")

    def palette(self, dark: bool, *, translucent: bool = False) -> dict[str, str]:
        variant = "dark" if dark else "light"
        palette = self.palettes[variant]
        if translucent and self.backdrop:
            return palette | self.translucent.get(variant, {})
        return palette

    def color_scheme(self, variant: str) -> str:
        """Resolve a user variant preference to 'system', 'light' or 'dark'."""
        if variant not in VARIANTS:
            variant = "theme"
        return self.default_variant if variant == "theme" else variant


@lru_cache(maxsize=1)
def theme_catalog() -> dict[str, Theme]:
    """Every bundled theme, including those meant for another platform."""
    themes = {}
    for path in sorted(THEMES_DIR.glob("*.json")):
        theme = Theme.from_dict(json.loads(path.read_text(encoding="utf-8")))
        if theme.id != path.stem:
            raise ThemeError(f"{path.name}: id {theme.id!r} difere do nome do arquivo")
        themes[theme.id] = theme
    if DEFAULT_THEME not in themes or themes[DEFAULT_THEME].platforms:
        raise ThemeError("o tema padrão não foi encontrado")
    # Keep the default first, then alphabetical, for stable menus.
    return {DEFAULT_THEME: themes[DEFAULT_THEME]} | {
        key: value for key, value in sorted(themes.items()) if key != DEFAULT_THEME
    }


def builtin_themes() -> dict[str, Theme]:
    """The themes offered on this platform; a saved theme missing here falls back."""
    return {key: theme for key, theme in theme_catalog().items() if theme.available}


@cache
def theme_stylesheet(name: str) -> str:
    return (THEMES_DIR / name).read_text(encoding="utf-8") if name else ""


def get_theme(theme_id: str) -> Theme:
    themes = builtin_themes()
    return themes.get(theme_id, themes[DEFAULT_THEME])


def scale_corners(css: str, scale: float) -> str:
    if scale == 1:
        return css

    def radius(match: re.Match) -> str:
        def pixels(px: re.Match) -> str:
            value = float(px.group(1))
            if value >= _PILL_RADIUS:
                return px.group(0)
            return f"{round(value * scale):d}px"

        return match.group(1) + _PIXELS.sub(pixels, match.group(2))

    return _RADIUS.sub(radius, css)


def render_gtk_css(
    theme: Theme,
    *,
    dark: bool,
    base_css: str,
    css_variables: bool,
    accent: str = "theme",
    system_accent: dict[str, str] | None = None,
    translucent: bool = False,
) -> str:
    """Return the full stylesheet for ``theme``.

    ``css_variables`` selects how libadwaita colours are overridden: GTK 4.16+
    with libadwaita 1.6+ reads CSS custom properties, older versions read
    @define-color named colours. ``system_accent`` replaces the theme's own
    accent when the theme follows the desktop accent and none was chosen.
    ``translucent`` is set while a window material sits behind the window.
    """
    solid = theme.palette(dark)
    palette = theme.palette(dark, translucent=translucent)
    lines = [f"/* Harmonia theme: {theme.id} ({'dark' if dark else 'light'}) */"]
    lines += [f"@define-color harmonia_{token} {palette[token]};" for token in TOKENS]

    overrides: dict[str, str] = {}
    if theme.restyle_adwaita:
        overrides |= {name: f"@harmonia_{token}" for name, token in ADWAITA_SURFACES.items()}
        if palette != solid:
            overrides |= {name: solid[ADWAITA_SURFACES[name]] for name in OPAQUE_SURFACES}
    accent_colors = (
        accent_preset(accent, dark=dark)
        or (system_accent if theme.system_accent else None)
        or theme.accent.get("dark" if dark else "light")
    )
    if accent_colors:
        overrides |= {name: accent_colors[token] for name, token in ADWAITA_ACCENT.items()}
    if overrides:
        if css_variables:
            # Custom properties cannot reference named colours, so resolve tokens.
            resolved = {
                name: palette[value.removeprefix("@harmonia_")]
                if value.startswith("@harmonia_")
                else value
                for name, value in overrides.items()
            }
            body = " ".join(
                f"--{name.removesuffix('_color').replace('_', '-')}-color: {value};"
                for name, value in resolved.items()
            )
            lines.append(f":root {{ {body} }}")
        # Named colours too: style.css and older libadwaita rules read them.
        lines += [f"@define-color {name} {value};" for name, value in overrides.items()]

    css = "\n".join(lines) + "\n\n" + scale_corners(base_css, theme.corner_scale)
    if theme.stylesheet:
        css += f"\n/* {theme.id}: structural layer */\n" + theme_stylesheet(theme.stylesheet)
    if theme.font_family:
        css += f'\nwindow {{ font-family: "{theme.font_family}", sans-serif; }}\n'
    return css
