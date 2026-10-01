import json
import re
from pathlib import Path

import pytest

from harmonia.preferences import Preferences
from harmonia.theming import (
    ACCENT_PRESETS,
    ADWAITA_SURFACES,
    DEFAULT_THEME,
    THEMES_DIR,
    TOKENS,
    VARIANTS,
    Theme,
    ThemeError,
    accent_preset,
    builtin_themes,
    get_theme,
    render_gtk_css,
    scale_corners,
)

SOURCE = Path(__file__).resolve().parents[1] / "src" / "harmonia"
BASE_CSS = (SOURCE / "style.css").read_text(encoding="utf-8")

# The values style.css used before it was tokenized. The default theme must keep
# them so the original look is preserved pixel for pixel.
LEGACY_DARK = {
    "bg": "#242424", "sidebar_bg": "#1e1e1e", "headerbar_bg": "#303030", "border": "#1a1a1a",
    "hover_bg": "#3a3a3a", "selected_bg": "#4a4a4a", "chip_bg": "#333333",
    "chip_hover_bg": "#414141", "fg": "#ffffff", "fg_secondary": "#deddda",
    "fg_tertiary": "#d0cfcc", "fg_muted": "#b5b3b0", "fg_subtle": "#aaa8a5", "fg_dim": "#9a9996",
    "overlay": "#ffffff", "shadow": "#000000", "inverse_bg": "#ffffff", "inverse_fg": "#111111",
    "inverse_hover_bg": "#eeeeec", "destructive_fg": "#ffb4ab", "destructive_bg": "#c01c28",
    "destructive_border": "#f66151", "warning_bg": "#e5a50a", "warning_fg": "#f8e45c",
}  # fmt: skip

# (foreground, background, minimum WCAG contrast ratio)
CONTRAST = [
    ("fg", "bg", 4.5), ("fg_secondary", "bg", 4.5), ("fg_tertiary", "bg", 4.5),
    ("fg_muted", "bg", 4.5), ("fg_subtle", "bg", 4.5), ("fg_dim", "bg", 3.0),
    ("fg_dim", "sidebar_bg", 3.0), ("fg_muted", "sidebar_bg", 4.5), ("fg", "headerbar_bg", 4.5),
    ("fg", "hover_bg", 4.5), ("fg", "selected_bg", 4.5), ("inverse_fg", "inverse_bg", 4.5),
    ("inverse_fg", "inverse_hover_bg", 4.5), ("destructive_fg", "bg", 3.0),
    ("warning_fg", "bg", 3.0),
]  # fmt: skip


def luminance(color: str) -> float:
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def literal_palettes():
    for theme in builtin_themes().values():
        for variant, palette in theme.palettes.items():
            if all(re.fullmatch(r"#[0-9a-f]{6}", value) for value in palette.values()):
                yield theme, variant, palette


def test_builtin_themes_load_with_the_default_first():
    themes = builtin_themes()
    assert next(iter(themes)) == DEFAULT_THEME
    assert {"harmonia", "adwaita", "elementary", "breeze"} <= set(themes)
    assert get_theme("does-not-exist").id == DEFAULT_THEME


def test_default_theme_keeps_the_original_palette():
    assert get_theme(DEFAULT_THEME).palette(dark=True) == LEGACY_DARK


def test_stylesheet_only_uses_known_tokens():
    used = set(re.findall(r"@harmonia_([a-z_]+)", BASE_CSS))
    assert used <= set(TOKENS)
    assert used == set(TOKENS), f"tokens sem uso: {sorted(set(TOKENS) - used)}"


@pytest.mark.parametrize("css_variables", [False, True])
def test_every_theme_renders_complete_css(css_variables):
    for theme in builtin_themes().values():
        for dark in (True, False):
            css = render_gtk_css(theme, dark=dark, base_css=BASE_CSS, css_variables=css_variables)
            defined = set(re.findall(r"@define-color harmonia_([a-z_]+) ", css))
            assert defined == set(TOKENS)
            assert css.count("{") == css.count("}")


def test_readable_contrast_in_every_literal_palette():
    checked = 0
    for theme, variant, palette in literal_palettes():
        for fg, bg, minimum in CONTRAST:
            ratio = contrast(palette[fg], palette[bg])
            assert ratio >= minimum, f"{theme.id}/{variant}: {fg} sobre {bg} = {ratio:.2f}"
        accent = theme.accent.get(variant)
        if accent:
            assert contrast(accent["accent_fg"], accent["accent_bg"]) >= 3.0
            assert contrast(accent["accent"], palette["bg"]) >= 3.0
        checked += 1
    assert checked >= 6


def test_themes_that_restyle_libadwaita_use_literal_colors():
    # CSS custom properties cannot reference GTK named colours.
    for theme in builtin_themes().values():
        if not theme.restyle_adwaita:
            continue
        for palette in theme.palettes.values():
            for token in set(ADWAITA_SURFACES.values()):
                assert palette[token].startswith("#"), (theme.id, token)


def test_libadwaita_overrides_follow_the_gtk_version():
    breeze = get_theme("breeze")
    modern = render_gtk_css(breeze, dark=True, base_css="", css_variables=True)
    legacy = render_gtk_css(breeze, dark=True, base_css="", css_variables=False)
    assert "--accent-bg-color: #1d99f3;" in modern and "--window-bg-color: #202326;" in modern
    assert "@define-color accent_bg_color #1d99f3;" in modern
    assert "@define-color accent_bg_color #1d99f3;" in legacy
    assert "@define-color window_bg_color @harmonia_bg;" in legacy
    harmonia = render_gtk_css(get_theme("harmonia"), dark=True, base_css="", css_variables=True)
    assert ":root" not in harmonia and "accent_bg_color" not in harmonia


def test_corner_scale_keeps_pills_round():
    css = ".a { border-radius: 12px; } .b { border-radius: 9999px; } .c { border-radius: 8px 4px; }"
    scaled = scale_corners(css, 0.5)
    assert "border-radius: 6px;" in scaled
    assert "border-radius: 9999px;" in scaled
    assert "border-radius: 4px 2px;" in scaled
    assert scale_corners(css, 1) == css


def test_variant_preference_resolves_against_the_theme_default():
    harmonia, elementary = get_theme("harmonia"), get_theme("elementary")
    assert harmonia.color_scheme("theme") == "dark"
    assert elementary.color_scheme("theme") == "system"
    assert elementary.color_scheme("light") == "light"
    assert harmonia.color_scheme("bogus") == "dark"
    assert set(VARIANTS) == {"theme", "system", "light", "dark"}


def test_invalid_theme_files_are_rejected():
    data = json.loads((SOURCE / "themes" / "harmonia.json").read_text(encoding="utf-8"))
    del data["palettes"]["light"]["fg"]
    with pytest.raises(ThemeError):
        Theme.from_dict(data)
    with pytest.raises(ThemeError):
        Theme.from_dict({**data, "id": "Bad Id"})


class MemoryStorage:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get_setting(self, key, default=""):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value


def test_theme_preferences_round_trip_and_validate():
    storage = MemoryStorage()
    preferences = Preferences.load(storage)
    assert (preferences.theme, preferences.theme_variant) == (DEFAULT_THEME, "theme")
    preferences.theme, preferences.theme_variant, preferences.accent = "breeze", "light", "purple"
    preferences.save(storage)
    loaded = Preferences.load(storage)
    assert (loaded.theme, loaded.theme_variant, loaded.accent) == ("breeze", "light", "purple")

    broken = Preferences.load(
        MemoryStorage({"theme": "nope", "theme_variant": "neon", "accent": "gold"})
    )
    assert (broken.theme, broken.theme_variant, broken.accent) == (DEFAULT_THEME, "theme", "theme")


def test_gtk_controller_applies_themes_live():
    gi = pytest.importorskip("gi")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk

    display = Gdk.Display.get_default()
    if display is None:
        pytest.skip("sem display")
    from harmonia.gtk_theme import GtkThemeController

    controller = GtkThemeController(display)
    controller.apply("breeze", "light")
    assert controller.style_manager.get_dark() is False
    assert controller._rendered == ("breeze", False, "theme")
    controller.apply("harmonia", accent="purple")
    assert controller.style_manager.get_dark() is True
    assert controller._rendered == ("harmonia", True, "purple")


def test_accent_presets_are_readable_on_every_literal_palette():
    for name, preset in ACCENT_PRESETS.items():
        assert contrast(preset["accent_fg"], preset["accent_bg"]) >= 3.0, name
    for theme, variant, palette in literal_palettes():
        for name in ACCENT_PRESETS:
            tone = accent_preset(name, dark=variant == "dark")["accent"]
            ratio = contrast(tone, palette["bg"])
            assert ratio >= 3.0, f"{name} sobre {theme.id}/{variant}: {ratio:.2f}"


def test_accent_preference_overrides_the_theme_accent():
    breeze = get_theme("breeze")
    css = render_gtk_css(breeze, dark=True, base_css="", css_variables=False, accent="purple")
    assert "@define-color accent_bg_color #a56de2;" in css
    assert "#1d99f3" not in css
    default = render_gtk_css(get_theme("harmonia"), dark=False, base_css="", css_variables=False)
    assert "accent_bg_color" not in default


def test_structural_layers_exist_and_only_use_known_colors():
    named = set(TOKENS) | {
        "window_bg_color", "window_fg_color", "view_bg_color", "headerbar_bg_color",
        "sidebar_bg_color", "accent_bg_color", "accent_fg_color", "accent_color",
    }  # fmt: skip
    layered = [theme for theme in builtin_themes().values() if theme.stylesheet]
    assert {theme.id for theme in layered} == {"adwaita", "elementary", "breeze"}
    for theme in layered:
        css = (THEMES_DIR / theme.stylesheet).read_text(encoding="utf-8")
        assert css.count("{") == css.count("}"), theme.id
        for name in re.findall(r"@([a-z_]+)", css):
            assert name.removeprefix("harmonia_") in named, (theme.id, name)
        rendered = render_gtk_css(theme, dark=True, base_css=BASE_CSS, css_variables=False)
        assert rendered.index("structural layer") > rendered.index("window { background:")
