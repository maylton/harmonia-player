"""Blur behind the window on Linux: KWin on request, Blur my Shell on GNOME."""

from __future__ import annotations

import os
import struct

import pytest

gi = pytest.importorskip("gi")

from harmonia import dconf_db, gnome_blur, kwin_blur  # noqa: E402

APP = "io.github.harmonia.Harmonia"
APPS = gnome_blur.APPLICATIONS


def test_rounded_region_covers_the_window_but_its_corners():
    rects = kwin_blur.rounded_rect_region(10, 20, 400, 300, 8)
    covered = {(px, py) for x, y, w, h in rects for px in range(x, x + w) for py in range(y, y + h)}
    assert all(10 <= px < 410 and 20 <= py < 320 for px, py in covered)
    assert (10 + 200, 20 + 150) in covered  # the middle
    assert (10, 20) not in covered and (409, 319) not in covered  # the corners' tips
    assert (10, 20 + 8) in covered and (10 + 8, 20) in covered  # where the arcs end
    assert sum(w * h for *_xy, w, h in rects) == len(covered)  # no overlaps
    assert kwin_blur.rounded_rect_region(0, 0, 50, 40, 0) == [(0, 0, 50, 40)]


def gvdb(entries: dict[str, gi.repository.GLib.Variant]) -> bytes:
    """A GVDB file like dconf's: one directory item and its keys."""
    from gi.repository import GLib

    directory = APPS.encode()
    names = [directory, *(key.encode() for key in entries)]
    values = [GLib.Variant("v", value).get_data_as_bytes().get_data() for value in entries.values()]
    item_count = len(names)
    root_start = 24
    items_start = root_start + 8
    data_start = items_start + 24 * item_count
    blob, items = b"", []
    for index, name in enumerate(names):
        key_start = data_start + len(blob)
        blob += name
        if index == 0:
            items.append(
                struct.pack("<IIIHccII", 0, 0xFFFFFFFF, key_start, len(name), b"L", b"\0", 0, 0)
            )
            continue
        value_start = data_start + len(blob)
        blob += values[index - 1]
        items.append(struct.pack(
            "<IIIHccII", 0, 0, key_start, len(name), b"v", b"\0",
            value_start, value_start + len(values[index - 1]),
        ))  # fmt: skip
    header = struct.pack("<IIIIII", 0x72615647, 0x746E6169, 0, 0, root_start, data_start)
    return header + struct.pack("<II", 0, 0) + b"".join(items) + blob


def test_dconf_database_values_under_a_path():
    from gi.repository import GLib

    data = gvdb({"blur": GLib.Variant("b", True), "whitelist": GLib.Variant("as", [APP, "x"])})
    values = dconf_db.read_values(data, APPS)
    assert values == {APPS + "blur": True, APPS + "whitelist": [APP, "x"]}
    assert dconf_db.read_values(data, "/org/other/") == {}
    assert dconf_db.read_values(b"not a database", APPS) == {}


@pytest.mark.skipif(not os.environ.get("CI"), reason="writes to the user's dconf")
def test_dconf_write_and_read_back_through_the_real_service():
    """In CI only: a real dconf service and database, under a test path."""
    from gi.repository import GLib

    path = "/io/github/harmonia/test/blur/"
    if not dconf_db.write({path + "whitelist": GLib.Variant("as", [APP])}):
        pytest.skip("no dconf service")
    assert dconf_db.read(path) == {path + "whitelist": [APP]}
    dconf_db.write({path + "whitelist": None})


@pytest.mark.parametrize(
    ("values", "covered"),
    [
        ({}, False),  # application blur off by default
        ({APPS + "blur": True}, False),  # on, but Harmonia not listed
        ({APPS + "blur": True, APPS + "whitelist": [APP]}, True),
        ({APPS + "blur": True, APPS + "enable-all": True}, True),
        ({APPS + "blur": True, APPS + "enable-all": True, APPS + "blacklist": [APP]}, False),
        ({APPS + "blur": False, APPS + "whitelist": [APP]}, False),
    ],
)
def test_blur_my_shell_coverage(values, covered):
    assert gnome_blur.covers(values, APP) is covered


def test_including_harmonia_turns_blur_on_and_lists_it(monkeypatch):
    written = {}
    monkeypatch.setattr(gnome_blur.dconf_db, "read", lambda _path: {APPS + "whitelist": ["kitty"]})
    monkeypatch.setattr(gnome_blur.dconf_db, "write", lambda values: written.update(values) or True)

    assert gnome_blur.include(APP)
    assert written[APPS + "blur"].unpack() is True
    assert written[APPS + "whitelist"].unpack() == ["kitty", APP]


class FakeKWin(kwin_blur.WaylandBlur):
    def __init__(self):  # no Wayland here
        self.regions, self.unset_calls = [], []

    def set_region(self, handle, rects):
        self.regions.append((handle, rects))

    def unset(self, handle):
        self.unset_calls.append(handle)


class Surface:
    def get_wl_surface(self):
        return 0xABC

    def connect(self, *_args):
        return 1

    def get_scale_factor(self):
        return 1


class App:
    def get_application_id(self):
        return APP


class Window:
    preferences = type("P", (), {"theme": "harmonia"})()

    def __init__(self):
        self.surface, self.css = Surface(), set()

    def get_display(self):
        return object()

    def get_surface(self):
        return self.surface

    def get_application(self):
        return App()

    def get_surface_transform(self):
        return 24.0, 22.0  # the client-side shadow

    def get_width(self):
        return 900

    def get_height(self):
        return 600

    def is_maximized(self):
        return False

    def is_fullscreen(self):
        return False

    def connect(self, *_args):
        return 1

    def queue_draw(self):
        pass


def backdrops(monkeypatch, desktop, **fakes):
    from harmonia import desktop_wallpaper, linux_backdrop

    monkeypatch.setenv("XDG_CURRENT_DESKTOP", desktop)
    monkeypatch.setattr(desktop_wallpaper, "desktop_prefers_dark", lambda: None)
    monkeypatch.setattr(linux_backdrop, "set_css_class", lambda *_args: None)
    instance = linux_backdrop.LinuxWindowBackdrops.__new__(linux_backdrop.LinuxWindowBackdrops)
    instance.__dict__.update(
        kind="mica", active=False, reason="", wallpaper=None, blur="",
        blur_my_shell_offer=False, _kwin=fakes.get("kwin"), _kwin_display=None,
        _background_effect=fakes.get("effect", False),
        _kwin_surfaces={}, _waiting_realize=False, _timer=0, _provider_display=None,
        _window=Window(),
    )  # fmt: skip
    instance._style = type("S", (), {"get_dark": lambda _self: True})()
    instance._provider = type("P", (), {"load_from_string": lambda _self, css: setattr(
        instance, "css", css)})()  # fmt: skip
    monkeypatch.setattr(instance, "_install_provider", lambda _window: None)
    monkeypatch.setattr(instance, "_kwin_for", lambda _window: fakes.get("kwin"))
    monkeypatch.setattr(
        desktop_wallpaper, "configured_wallpapers", lambda *, dark: fakes.get("wallpapers", [])
    )
    return instance


def test_kwin_blurs_behind_the_window_without_its_shadow(monkeypatch):
    kwin = FakeKWin()
    instance = backdrops(monkeypatch, "KDE", kwin=kwin)

    assert instance._refresh()
    assert instance.blur == "kwin" and instance.reason == "" and instance.wallpaper is None
    ((handle, rects),) = kwin.regions
    assert handle == 0xABC
    assert min(x for x, *_ in rects) == 24 and min(y for _x, y, *_ in rects) == 22
    assert max(x + w for x, _y, w, _h in rects) == 24 + 900
    assert "url(" not in instance.css  # the tint over the real blur, no wallpaper


def test_hyprland_blurs_through_backdrop_filter(monkeypatch):
    # GTK 4.24 gives the window an ext-background-effect object whose region
    # only backdrop-filter fills; without it Hyprland blurs nothing.
    instance = backdrops(monkeypatch, "Hyprland", effect=True)
    assert instance._refresh()
    assert instance.blur == "background-effect" and instance.wallpaper is None
    assert "backdrop-filter: blur(" in instance.css and "url(" not in instance.css

    instance._window.preferences = type("P", (), {"theme": "breeze", "compositor_blur": True})()
    instance.kind = "blur"
    assert instance._refresh()
    assert "background: transparent; backdrop-filter: blur(" in instance.css


def test_kwin_keeps_its_own_protocol_over_backdrop_filter(monkeypatch):
    instance = backdrops(monkeypatch, "KDE", kwin=FakeKWin(), effect=True)
    instance._refresh()
    assert instance.blur == "kwin" and "backdrop-filter" not in instance.css


def test_gnome_uses_blur_my_shell_or_offers_it(monkeypatch):
    instance = backdrops(monkeypatch, "ubuntu:GNOME")
    monkeypatch.setattr(gnome_blur, "state", lambda _app: gnome_blur.BlurMyShell(True, True))
    instance._refresh()
    assert instance.blur == "blur-my-shell" and not instance.blur_my_shell_offer

    monkeypatch.setattr(gnome_blur, "state", lambda _app: gnome_blur.BlurMyShell(True, False))
    instance._refresh()
    # Mica falls back to the wallpaper, and Preferences offer to add Harmonia.
    assert instance.blur == "" and instance.blur_my_shell_offer
    assert "não encontrado" in instance.reason


def test_compositor_blur_can_be_turned_off(monkeypatch):
    kwin = FakeKWin()
    instance = backdrops(monkeypatch, "KDE", kwin=kwin)
    preferences = type("P", (), {"theme": "harmonia", "compositor_blur": False})()
    instance._window.preferences = preferences
    instance._refresh()
    assert instance.blur == "" and not kwin.regions
    preferences.compositor_blur = True
    instance._refresh()
    assert instance.blur == "kwin"


def test_mica_falls_back_to_the_wallpaper_without_a_compositor_blur(monkeypatch, tmp_path):
    from gi.repository import GdkPixbuf

    from harmonia import linux_backdrop

    wallpaper = tmp_path / "wall.png"
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 64, 32)
    pixbuf.fill(0x336699FF)
    pixbuf.savev(str(wallpaper), "png", [], [])
    instance = backdrops(monkeypatch, "GNOME", wallpapers=[wallpaper])
    monkeypatch.setattr(gnome_blur, "state", lambda _app: gnome_blur.BlurMyShell(False, False))
    monkeypatch.setattr(linux_backdrop.host, "cache_dir", lambda: tmp_path / "cache")

    instance._refresh()
    assert instance.blur == "" and instance.wallpaper == wallpaper
    assert "url(" in instance.css


def test_switching_to_a_theme_without_mica_clears_it_before_set_kind(monkeypatch):
    # A theme change can switch the colour scheme, which refreshes the material
    # before set_kind() hears of the new theme, whose palette may hold named
    # colours (Adwaita's) that cannot tint it.
    instance = backdrops(monkeypatch, "KDE", kwin=FakeKWin())
    instance._window.preferences = type("P", (), {"theme": "adwaita"})()
    assert instance._refresh() is False
    assert instance.kind == "none" and instance.css == ""


def test_other_themes_get_the_compositors_blur_alone(monkeypatch):
    # Every theme but Harmonia: no Mica, the window clears for the blur.
    kwin = FakeKWin()
    instance = backdrops(monkeypatch, "KDE", kwin=kwin)
    instance._window.preferences = type("P", (), {"theme": "breeze", "compositor_blur": True})()
    instance.kind = "blur"
    assert instance._refresh() is True
    assert instance.blur == "kwin" and kwin.regions
    assert "background: transparent" in instance.css and "url(" not in instance.css


def test_other_themes_stay_opaque_without_a_blur_or_a_wallpaper(monkeypatch):
    instance = backdrops(monkeypatch, "GNOME")
    monkeypatch.setattr(gnome_blur, "state", lambda _app: gnome_blur.BlurMyShell(False, False))
    instance._window.preferences = type("P", (), {"theme": "adwaita", "compositor_blur": True})()
    instance.kind = "blur"
    assert instance._refresh() is False and instance.css == ""


def test_other_themes_fall_back_to_the_wallpaper_blurred_by_harmonia(monkeypatch, tmp_path):
    from gi.repository import GdkPixbuf

    from harmonia import linux_backdrop

    wallpaper = tmp_path / "wall.png"
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 64, 32)
    pixbuf.fill(0x336699FF)
    pixbuf.savev(str(wallpaper), "png", [], [])
    instance = backdrops(monkeypatch, "GNOME", wallpapers=[wallpaper])
    monkeypatch.setattr(gnome_blur, "state", lambda _app: gnome_blur.BlurMyShell(False, False))
    monkeypatch.setattr(linux_backdrop.host, "cache_dir", lambda: tmp_path / "cache")
    instance._window.preferences = type("P", (), {"theme": "breeze", "compositor_blur": True})()
    instance.kind = "blur"
    assert instance._refresh() is True
    assert instance.blur == "" and instance.wallpaper == wallpaper
    # The wallpaper as it is blurred, with no Mica tint: the surfaces carry it.
    assert "url(" in instance.css and "linear-gradient" not in instance.css
