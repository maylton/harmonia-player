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
    fluent_accent,
    get_theme,
    render_gtk_css,
    scale_corners,
    theme_catalog,
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
    for theme in theme_catalog().values():
        for variant, palette in theme.palettes.items():
            if all(re.fullmatch(r"#[0-9a-f]{6}", value) for value in palette.values()):
                yield theme, variant, palette


def test_builtin_themes_load_with_the_default_first():
    themes = builtin_themes()
    assert next(iter(themes)) == DEFAULT_THEME
    assert {"harmonia", "adwaita", "elementary", "breeze"} <= set(themes)
    assert get_theme("does-not-exist").id == DEFAULT_THEME


def test_windows_11_theme_is_offered_only_on_windows(monkeypatch):
    from harmonia import host

    assert theme_catalog()["windows11"].platforms == ("windows",)
    monkeypatch.setattr(host, "PLATFORM", "linux")
    assert "windows11" not in builtin_themes()
    assert get_theme("windows11").id == DEFAULT_THEME
    saved = Preferences.load(MemoryStorage({"theme": "windows11"}))
    assert saved.theme == DEFAULT_THEME

    monkeypatch.setattr(host, "PLATFORM", "windows")
    assert "windows11" in builtin_themes()
    assert get_theme("windows11").id == "windows11"
    assert Preferences.load(MemoryStorage({"theme": "windows11"})).theme == "windows11"


def test_platform_names_are_validated():
    data = json.loads((SOURCE / "themes" / "windows11.json").read_text(encoding="utf-8"))
    with pytest.raises(ThemeError):
        Theme.from_dict({**data, "platforms": ["macos"]})


def test_fluent_accent_follows_the_windows_palette():
    palette = ["#99ebff", "#4cc2ff", "#0091f8", "#0078d4", "#0067c0", "#003e92", "#001a68"]
    assert fluent_accent(palette, dark=True) == {
        "accent_bg": "#4cc2ff",
        "accent_fg": "#000000",
        "accent": "#99ebff",
    }
    assert fluent_accent(palette, dark=False) == {
        "accent_bg": "#0067c0",
        "accent_fg": "#ffffff",
        "accent": "#003e92",
    }
    assert fluent_accent(None, dark=True) is None
    assert fluent_accent(palette[:3], dark=True) is None


def test_windows_material_turns_only_the_window_surfaces_translucent():
    windows = theme_catalog()["windows11"]
    assert windows.backdrop
    solid = windows.palette(dark=True)
    see_through = windows.palette(dark=True, translucent=True)
    assert see_through["sidebar_bg"] == "transparent"
    assert see_through["bg"].startswith("rgba(")
    # Cards and buttons lighten the material with white, as Fluent's fills do,
    # so they keep its tint instead of greying it out.
    assert see_through["chip_bg"] == "rgba(255, 255, 255, 0.0605)"
    assert windows.palette(dark=False, translucent=True)["chip_bg"] == "rgba(255, 255, 255, 0.7)"
    assert see_through["fg"] == solid["fg"]

    for css_variables in (False, True):
        css = render_gtk_css(
            windows, dark=True, base_css="", css_variables=css_variables, translucent=True
        )
        assert "@define-color harmonia_sidebar_bg transparent;" in css
        # Menus and dialogs float over the window without any material behind.
        assert f"@define-color popover_bg_color {solid['headerbar_bg']};" in css
        assert f"@define-color dialog_bg_color {solid['bg']};" in css
    opaque = render_gtk_css(windows, dark=True, base_css="", css_variables=False)
    assert "transparent;" not in opaque.split("\n\n")[0]

    # Themes without a material ignore the request.
    breeze = get_theme("breeze")
    assert breeze.palette(dark=True, translucent=True) == breeze.palette(dark=True)


def test_windows_material_reaches_cards_and_controls_but_not_floating_surfaces():
    css = (THEMES_DIR / "windows11.css").read_text(encoding="utf-8")
    rules = {
        selectors.strip(): body.strip()
        for selectors, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)
    }
    # Cards, the playlist button, drop-downs and text boxes use the chip
    # token, which turns translucent with the material.
    filled = [selectors for selectors, body in rules.items() if "@harmonia_chip_bg" in body]
    for control in ("list.boxed-list", ".sidebar-create", "dropdown > button", "entry"):
        assert any(control in selectors for selectors in filled), control
    # Floating surfaces have no material behind them and keep the opaque chip.
    floating = next(
        selectors
        for selectors in rules
        if "popover.background" in selectors and "harmonia-backdrop" in selectors
    )
    assert "tooltip.background" in floating and "toast" in floating
    assert rules[floating] == "background-color: @harmonia_opaque_chip_bg;"
    windows = theme_catalog()["windows11"]
    rendered = render_gtk_css(
        windows, dark=True, base_css="", css_variables=False, translucent=True
    )
    assert f"@define-color harmonia_opaque_chip_bg {windows.palette(dark=True)['chip_bg']};" in (
        rendered
    )


def test_translucent_colours_require_a_backdrop_and_known_tokens():
    data = json.loads((SOURCE / "themes" / "windows11.json").read_text(encoding="utf-8"))
    with pytest.raises(ThemeError):
        Theme.from_dict({**data, "backdrop": False})
    with pytest.raises(ThemeError):
        Theme.from_dict({**data, "translucent": {"dark": {"nope": "transparent"}}})
    with pytest.raises(ThemeError):
        Theme.from_dict({**data, "translucent": {"dark": {"bg": "url(evil)"}}})


def test_backdrop_preference_round_trips_and_validates():
    storage = MemoryStorage()
    assert Preferences.load(storage).backdrop == "mica"
    preferences = Preferences.load(storage)
    preferences.backdrop = "acrylic"
    preferences.save(storage)
    assert Preferences.load(storage).backdrop == "acrylic"
    assert Preferences.load(MemoryStorage({"backdrop": "glass"})).backdrop == "mica"


def test_system_accent_applies_only_to_themes_that_follow_it():
    system = {"accent_bg": "#4cc2ff", "accent_fg": "#000000", "accent": "#99ebff"}
    windows = theme_catalog()["windows11"]
    css = render_gtk_css(windows, dark=True, base_css="", css_variables=False, system_accent=system)
    assert "@define-color accent_bg_color #4cc2ff;" in css
    # An explicit accent choice still wins, and without the palette the theme's own is used.
    chosen = render_gtk_css(
        windows, dark=True, base_css="", css_variables=False, accent="green", system_accent=system
    )
    assert "@define-color accent_bg_color #3a9104;" in chosen
    fallback = render_gtk_css(windows, dark=True, base_css="", css_variables=False)
    assert "@define-color accent_bg_color #60cdff;" in fallback
    breeze = render_gtk_css(
        get_theme("breeze"), dark=True, base_css="", css_variables=False, system_accent=system
    )
    assert "#4cc2ff" not in breeze


def test_default_theme_keeps_the_original_palette():
    assert get_theme(DEFAULT_THEME).palette(dark=True) == LEGACY_DARK


def test_stylesheet_only_uses_known_tokens():
    used = set(re.findall(r"@harmonia_([a-z_]+)", BASE_CSS))
    assert used <= set(TOKENS)
    assert used == set(TOKENS), f"tokens sem uso: {sorted(set(TOKENS) - used)}"


@pytest.mark.parametrize("css_variables", [False, True])
def test_every_theme_renders_complete_css(css_variables):
    for theme in theme_catalog().values():
        for dark in (True, False):
            css = render_gtk_css(theme, dark=dark, base_css=BASE_CSS, css_variables=css_variables)
            defined = set(re.findall(r"@define-color harmonia_([a-z_]+) ", css))
            fallbacks = {name for name in defined if name.startswith("opaque_")}
            assert defined - fallbacks == set(TOKENS)
            assert {name.removeprefix("opaque_") for name in fallbacks} <= set(TOKENS)
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
    for theme in theme_catalog().values():
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
    layered = [theme for theme in theme_catalog().values() if theme.stylesheet]
    assert {theme.id for theme in layered} == {"adwaita", "elementary", "breeze", "windows11"}
    for theme in layered:
        css = (THEMES_DIR / theme.stylesheet).read_text(encoding="utf-8")
        assert css.count("{") == css.count("}"), theme.id
        rendered = render_gtk_css(theme, dark=True, base_css=BASE_CSS, css_variables=False)
        # Themes with a window material also get the opaque colours of their
        # translucent tokens, for the out-of-focus fallback.
        opaque = set(re.findall(r"@define-color harmonia_(opaque_[a-z_]+) ", rendered))
        for name in re.findall(r"@([a-z_]+)", css):
            assert name.removeprefix("harmonia_") in named | opaque, (theme.id, name)
        assert rendered.index("structural layer") > rendered.index("window { background:")


def test_window_material_falls_back_to_opaque_colours_out_of_focus():
    windows = theme_catalog()["windows11"]
    solid = windows.palette(dark=True)
    rendered = render_gtk_css(
        windows, dark=True, base_css="", css_variables=False, translucent=True
    )
    for token in ("bg", "sidebar_bg", "headerbar_bg"):
        assert f"@define-color harmonia_opaque_{token} {solid[token]};" in rendered
    css = (THEMES_DIR / "windows11.css").read_text(encoding="utf-8")
    assert "window.harmonia-backdrop:backdrop .sidebar" in css
    assert "transition: background-color 250ms" in css
    # Themes without a material define no fallback colours.
    assert "harmonia_opaque_" not in render_gtk_css(
        get_theme("breeze"), dark=True, base_css="", css_variables=False
    )


def test_elementary_layer_follows_the_flat_elementary_os_8_style():
    css = (THEMES_DIR / "elementary.css").read_text(encoding="utf-8")
    assert "linear-gradient" not in css
    # The source-list selection is neutral in io.elementary.stylesheet.
    active = re.search(r"\.sidebar-active, \.sidebar-active:hover \{([^}]*)\}", css).group(1)
    assert "accent" not in active
    assert get_theme("elementary").palette(dark=True)["bg"] == "#333333"  # BLACK_500
