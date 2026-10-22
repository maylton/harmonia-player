import json

import pytest

from harmonia import material_scheme
from harmonia.theming import get_theme, material_roles, render_gtk_css

CAELESTIA = {
    "name": "oldworld",
    "mode": "dark",
    "colours": {
        role: f"{index:06x}" for index, role in enumerate(material_scheme.ROLES, start=0x101010)
    },
}


def test_caelestia_scheme_is_read_with_its_mode(tmp_path):
    path = tmp_path / "scheme.json"
    path.write_text(json.dumps(CAELESTIA), encoding="utf-8")
    roles, dark = material_scheme.load_caelestia_scheme(path)
    assert dark is True
    assert roles["primary"] == "#" + CAELESTIA["colours"]["primary"]
    assert set(roles) == set(material_scheme.ROLES)
    light = {**CAELESTIA, "mode": "light"}
    assert material_scheme.parse_scheme(light)[1] is False
    # Missing or broken schemes are ignored, never half used.
    broken = {**CAELESTIA, "colours": {**CAELESTIA["colours"], "primary": "blue"}}
    assert material_scheme.parse_scheme(broken) is None
    assert material_scheme.load_caelestia_scheme(tmp_path / "missing.json") is None
    path.write_text("{not json", encoding="utf-8")
    assert material_scheme.load_caelestia_scheme(path) is None


def test_caelestia_scheme_path_is_the_hosts_inside_flatpak(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("HOST_XDG_STATE_HOME", raising=False)
    monkeypatch.setattr(material_scheme.os.path, "exists", lambda path: False)
    assert material_scheme.caelestia_scheme_path() == tmp_path / "state/caelestia/scheme.json"
    monkeypatch.setattr(material_scheme.os.path, "exists", lambda path: path == "/.flatpak-info")
    monkeypatch.setattr(material_scheme.Path, "home", lambda: tmp_path)
    assert material_scheme.caelestia_scheme_path() == (
        tmp_path / ".local/state/caelestia/scheme.json"
    )


def test_material_roles_become_css_names_and_palette():
    assert material_scheme.css_name("onSecondaryContainer") == "md_on_secondary_container"
    assert material_scheme.css_name("primary") == "md_primary"
    roles = get_theme("material").material["dark"]
    palette = material_scheme.palette(roles)
    assert palette["bg"] == roles["surface"] and palette["fg"] == roles["onSurface"]
    assert palette["selected_bg"] == roles["secondaryContainer"]


def test_material_theme_follows_caelestia_then_the_accent():
    theme = get_theme("material")
    desktop = dict(material_scheme.parse_scheme(CAELESTIA)[0])
    css = render_gtk_css(theme, dark=True, base_css="", css_variables=False, desktop_roles=desktop)
    assert f"@define-color md_primary {desktop['primary']};" in css
    assert f"@define-color accent_bg_color {desktop['primary']};" in css
    assert f"@define-color harmonia_bg {desktop['surface']};" in css
    # A desktop accent (GNOME, elementary) retints the baseline scheme.
    system = {"accent_bg": "#3584e4", "accent_fg": "#ffffff", "accent": "#3584e4"}
    tinted = material_roles(theme, dark=True, system_accent=system)
    assert tinted["primary"] == "#3584e4"
    assert tinted["secondaryContainer"] != theme.material["dark"]["secondaryContainer"]
    # An accent chosen in Preferences wins over the desktop's scheme.
    chosen = material_roles(theme, dark=True, accent="green", desktop_roles=desktop)
    assert chosen["primary"] == "#9bdb4d"
    assert material_roles(theme, dark=False) == theme.material["light"]


def test_expressive_curves_overshoot_like_caelestias():
    from harmonia.gtk_expressive import DEFAULT_SPATIAL, FAST_SPATIAL, cubic_bezier

    fast = cubic_bezier(*FAST_SPATIAL[1])
    assert fast(0) == 0 and fast(1) == 1
    assert max(fast(step / 100) for step in range(101)) > 1.05  # the spring overshoot
    default = cubic_bezier(*DEFAULT_SPATIAL[1])
    assert default(0.5) > 0.5
    linear = cubic_bezier(0, 0, 1, 1)
    assert linear(0.25) == pytest.approx(0.25, abs=1e-3)


def test_cookie_is_closed_and_fits_its_square():
    from harmonia.gtk_expressive import COOKIE_9

    assert len(COOKIE_9) == 19
    for current, following in zip(COOKIE_9, COOKIE_9[1:] + COOKIE_9[:1], strict=True):
        assert current[6:] == following[:2]
    values = [value for cubic in COOKIE_9 for value in cubic]
    assert min(values) >= 0 and max(values) <= 1


def test_button_row_pushes_neighbours_like_caelestia():
    gi = pytest.importorskip("gi")
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    from harmonia.gtk_expressive import ButtonRow

    row = ButtonRow()
    buttons = [Gtk.Button() for _ in range(5)]
    for index, button in enumerate(buttons):
        row.append(button, fill=index == 2, narrow=index in (0, 4))
    row.set_expressive(True)
    placed = []
    import harmonia.gtk_expressive as expressive

    original = expressive._place
    expressive._place = lambda child, x, y, w, h: placed.append((x, w, h))
    try:
        row.do_size_allocate(400, 48, -1)
        widths = [w for _x, w, _h in placed]
        assert widths[0] == widths[4] == 36 and widths[1] == widths[3] == 48
        assert sum(widths) + 4 * 4 == 344  # the play button takes the rest
        assert all(h == 48 for _x, _w, h in placed)
        placed.clear()
        row._morph[buttons[1]].jump_to(24)  # previous pressed
        row.do_size_allocate(400, 48, -1)
        pressed = [w for _x, w, _h in placed]
        assert pressed[1] == 72 and pressed[0] == 24 and pressed[2] == widths[2] - 12
        assert sum(pressed) == sum(widths)
    finally:
        expressive._place = original


def test_explicit_badge_sits_after_the_title_not_before_the_cover():
    gi = pytest.importorskip("gi")
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk

    from harmonia.models import LibraryItem
    from harmonia.ui import mark_explicit, row_label

    row = Adw.ActionRow(title="Work Bitch")
    cover = Gtk.Box()
    row.add_prefix(cover)
    mark_explicit(row, LibraryItem(id="x", title="Work Bitch", kind="songs", explicit=True))
    title = row_label(row, "title")
    badge = title.get_next_sibling()
    assert badge is not None and badge.has_css_class("explicit-badge")
    assert title.get_parent().has_css_class("explicit-title-line")
    assert cover.get_prev_sibling() is None or not cover.get_prev_sibling().has_css_class(
        "explicit-badge"
    )
    row.set_title("Outro")
    assert title.get_label() == "Outro"


def test_pages_are_clipped_to_the_material_frame_curves():
    import inspect

    from harmonia import app
    from harmonia.ui import PageStack
    from harmonia.window_chrome import player_bar

    # GTK's overflow clip is rectangular: pages with their own background
    # (album, artist) covered the curves until the stack clipped them itself.
    assert "PageStack(" in inspect.getsource(app.HarmoniaWindow._build_layout)
    stack = PageStack()
    assert stack.corner_radius == 0
    stack.set_corner_radius(player_bar.EXPRESSIVE_CONTENT_RADIUS)
    assert stack.corner_radius == 25


def test_the_media_switch_survives_the_cookie_shaped_artwork():
    gi = pytest.importorskip("gi")
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    from harmonia.gtk_expressive import CookieCover
    from harmonia.gtk_video import GtkVideoMixin

    # The artwork used to sit right under its frame; the cookie wrapper made
    # the video feature skip the Música/Vídeo switch in every theme.
    class Window(GtkVideoMixin):
        def __init__(self):
            frame = Gtk.AspectFrame()
            overlay = Gtk.Overlay()
            self.expanded_cover = Gtk.Picture()
            overlay.set_child(self.expanded_cover)
            self.expanded_cover_shape = CookieCover(overlay)
            frame.set_child(self.expanded_cover_shape)
            self.frame = frame

        def _prepare_gtk_video_sink(self, _picture):
            pass

        def _sync_media_mode_ui(self):
            pass

    window = Window()
    window._video_feature_init()
    assert window._media_audio_button.get_label() and window._media_video_button
    assert window._media_stack.get_child_by_name("audio") is window.expanded_cover_shape
