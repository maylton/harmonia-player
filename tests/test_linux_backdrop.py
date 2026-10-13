import pytest

gi = pytest.importorskip("gi")


def write_kde_config(folder, image_value):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plasma-org.kde.plasma.desktop-appletsrc").write_text(
        "[Containments][1]\nplugin=org.kde.plasma.folder\n\n"
        "[Containments][1][Wallpaper][org.kde.image][General]\n"
        f"Image={image_value}\nSlidePaths=/usr/share/wallpapers\n",
        encoding="utf-8",
    )


def test_plasma_wallpaper_files_and_packages(monkeypatch, tmp_path):
    from harmonia import desktop_wallpaper

    image = tmp_path / "beach.png"
    image.write_bytes(b"png")
    config = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    write_kde_config(config, image.as_uri())
    assert desktop_wallpaper.kde_wallpapers(dark=False) == [image]

    package = make_package(tmp_path / "Next")
    write_kde_config(config, str(package))
    # The largest image, from images_dark in dark mode.
    (light,) = desktop_wallpaper.kde_wallpapers(dark=False)
    assert (light.parent.name, light.name) == ("images", "3840x2160.png")
    assert desktop_wallpaper.kde_wallpapers(dark=True)[0].parent.name == "images_dark"


def make_package(package):
    (package / "contents" / "images").mkdir(parents=True)
    (package / "contents" / "images_dark").mkdir(parents=True)
    (package / "contents" / "images" / "1920x1080.png").write_bytes(b"x" * 10)
    (package / "contents" / "images" / "3840x2160.png").write_bytes(b"x" * 40)
    (package / "contents" / "images_dark" / "3840x2160.png").write_bytes(b"x" * 30)
    return package


def test_plasma_default_wallpaper_when_none_was_chosen(monkeypatch, tmp_path):
    from harmonia import desktop_wallpaper

    config, data = tmp_path / "config", tmp_path / "data"
    config.mkdir()
    # Plasma writes no Image key until the user picks a wallpaper.
    (config / "plasma-org.kde.plasma.desktop-appletsrc").write_text(
        "[Containments][1][Wallpaper][org.kde.image][General]\nSlidePaths=/x\n",
        encoding="utf-8",
    )
    (config / "kdeglobals").write_text(
        "[KDE]\nLookAndFeelPackage=org.example.desktop\n", encoding="utf-8"
    )
    defaults = data / "plasma" / "look-and-feel" / "org.example.desktop" / "contents"
    defaults.mkdir(parents=True)
    (defaults / "defaults").write_text("[Wallpaper]\nImage=Flow\n", encoding="utf-8")
    make_package(data / "wallpapers" / "Flow")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "none"))
    (image,) = desktop_wallpaper.kde_wallpapers(dark=True)
    assert image.parts[-4:] == ("Flow", "contents", "images_dark", "3840x2160.png")


def test_mica_reports_why_it_is_not_shown(monkeypatch, tmp_path):
    from harmonia import desktop_wallpaper, linux_backdrop

    def configured(*paths):
        monkeypatch.setattr(desktop_wallpaper, "configured_wallpapers", lambda *, dark: list(paths))

    backdrops = linux_backdrop.LinuxWindowBackdrops.__new__(linux_backdrop.LinuxWindowBackdrops)
    configured()
    monkeypatch.setattr(desktop_wallpaper, "in_flatpak", lambda: False)
    assert "não encontrado" in backdrops._mica(True)[1]
    # Named by the settings but out of the sandbox's reach: say how to allow it.
    configured(tmp_path / "Imagens" / "praia.jpg")
    monkeypatch.setattr(desktop_wallpaper, "in_flatpak", lambda: True)
    reason = backdrops._mica(True)[1]
    assert f"--filesystem={tmp_path / 'Imagens'}:ro io.github.harmonia.Harmonia" in reason

    broken = tmp_path / "adwaita-d.jxl"
    broken.write_bytes(b"not an image")
    configured(broken)
    monkeypatch.setattr(linux_backdrop.host, "cache_dir", lambda: tmp_path / "cache")
    image, reason = backdrops._mica(True)
    assert image is None and "JPEG XL" in reason and backdrops.wallpaper is None


def test_the_flatpak_reads_system_wallpapers_and_defaults_under_run_host(monkeypatch, tmp_path):
    from pathlib import Path

    from harmonia import desktop_wallpaper

    host = tmp_path / "host"
    image = host / "usr" / "share" / "backgrounds" / "warty-final-ubuntu.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"png")
    schemas = host / "usr" / "share" / "glib-2.0" / "schemas"
    schemas.mkdir(parents=True)
    (schemas / "00_plain.gschema.override").write_text(
        "[org.gnome.desktop.background]\npicture-uri='file:///plain.png'\n", encoding="utf-8"
    )
    (schemas / "10_ubuntu-settings.gschema.override").write_text(
        "[org.gnome.desktop.background:ubuntu]\n"
        "picture-uri='file:///usr/share/backgrounds/warty-final-ubuntu.png'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(desktop_wallpaper, "HOST_ROOT", host)
    monkeypatch.setattr(desktop_wallpaper, "in_flatpak", lambda: True)
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "ubuntu:GNOME")

    default = desktop_wallpaper.host_schema_default(desktop_wallpaper.GNOME_SCHEMA, "picture-uri")
    assert default == "file:///usr/share/backgrounds/warty-final-ubuntu.png"
    assert desktop_wallpaper.local_path(default) == image
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    assert desktop_wallpaper.host_schema_default(desktop_wallpaper.GNOME_SCHEMA, "picture-uri") == (
        "file:///plain.png"
    )
    # Paths outside the system folders are left alone.
    assert desktop_wallpaper.host_path(Path("/home/eu/x.png")) == Path("/home/eu/x.png")


def test_gtk_decodes_what_gdkpixbuf_cannot(monkeypatch, tmp_path):
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf, GLib

    from harmonia import linux_backdrop

    wallpaper = tmp_path / "wallpaper.png"
    source = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 800, 400)
    source.fill(0x3366CCFF)
    source.savev(str(wallpaper), "png", [], [])

    def no_loader(*_args):
        raise GLib.Error("formato desconhecido")

    monkeypatch.setattr(GdkPixbuf.Pixbuf, "new_from_file_at_scale", no_loader)
    scaled = linux_backdrop.load_scaled(wallpaper, 320)
    assert (scaled.get_width(), scaled.get_height()) == (320, 160)


def test_gnome_slideshows_resolve_to_their_only_image(tmp_path):
    from harmonia.desktop_wallpaper import resolve_image

    image = tmp_path / "morning.jpg"
    image.write_bytes(b"jpg")
    slideshow = tmp_path / "timed.xml"
    slideshow.write_text(
        f"<background><static><duration>3600</duration><file>{image}</file></static></background>",
        encoding="utf-8",
    )
    assert resolve_image(slideshow, dark=False) == image
    assert resolve_image(tmp_path / "notes.txt", dark=False) is None


def timed_wallpaper(folder):
    """Day from 07:00 for 12 h, a 1 h fade to night, night for 10 h, a 1 h fade back."""
    for name in ("day", "night", "night-small"):
        (folder / f"{name}.jpg").write_bytes(b"jpg")
    slideshow = folder / "dynamic.xml"
    slideshow.write_text(
        "<background>"
        "<starttime><year>2020</year><month>1</month><day>1</day>"
        "<hour>7</hour><minute>0</minute><second>0</second></starttime>"
        f"<static><duration>43200</duration><file>{folder}/day.jpg</file></static>"
        "<transition type='overlay'><duration>3600</duration>"
        f"<from>{folder}/day.jpg</from><to>{folder}/night.jpg</to></transition>"
        "<static><duration>36000</duration><file>"
        f"<size width='1280' height='720'>{folder}/night-small.jpg</size>"
        f"<size width='3840' height='2160'>{folder}/night.jpg</size>"
        "</file></static>"
        "<transition type='overlay'><duration>3600</duration>"
        f"<from>{folder}/night.jpg</from><to>{folder}/day.jpg</to></transition>"
        "</background>",
        encoding="utf-8",
    )
    return slideshow


@pytest.mark.parametrize(
    ("clock", "image", "changes_in"),
    [
        ("2026-10-13 07:00", "day", 12 * 3600),
        ("2026-10-13 18:59", "day", 60),
        ("2026-10-13 19:20", "day", 10 * 60),  # first half of the fade
        ("2026-10-13 19:40", "night", 20 * 60),  # second half
        ("2026-10-13 23:00", "night", 7 * 3600),  # the largest <size>
        ("2026-10-14 06:45", "day", 15 * 60),
    ],
)
def test_gnome_timed_wallpapers_follow_the_clock(tmp_path, clock, image, changes_in):
    from datetime import datetime

    from harmonia import gnome_slideshow

    slideshow = timed_wallpaper(tmp_path)
    now = datetime.strptime(clock, "%Y-%m-%d %H:%M")
    shown, seconds = gnome_slideshow.current_image(slideshow, now)
    assert (shown.stem, round(seconds)) == (image, changes_in)


def test_resolving_a_timed_wallpaper_records_when_it_changes(tmp_path):
    from harmonia import desktop_wallpaper

    slideshow = timed_wallpaper(tmp_path)
    desktop_wallpaper._next_change = None
    assert desktop_wallpaper.resolve_image(slideshow, dark=False).stem in {"day", "night"}
    assert 0 < desktop_wallpaper.seconds_until_change() <= 12 * 3600
    desktop_wallpaper._next_change = None


def test_plasma_uses_the_active_wallpaper_plugin(monkeypatch, tmp_path):
    from harmonia import desktop_wallpaper

    old, dynamic = tmp_path / "old.png", tmp_path / "dynamic.avif"
    old.write_bytes(b"png")
    dynamic.write_bytes(b"avif")
    slides = tmp_path / "slides" / "a"
    slides.mkdir(parents=True)
    (slides / "b.jpg").write_bytes(b"jpg")
    config = tmp_path / "config"
    config.mkdir()
    applets = config / "plasma-org.kde.plasma.desktop-appletsrc"

    def write(plugin):
        applets.write_text(
            "[Containments][7]\nplugin=org.kde.panel\n\n"
            f"[Containments][2]\nplugin=org.kde.plasma.folder\nwallpaperplugin={plugin}\n\n"
            # Left behind by the image plugin used before.
            f"[Containments][2][Wallpaper][org.kde.image][General]\nImage={old.as_uri()}\n\n"
            "[Containments][2][Wallpaper][com.github.zzag.dynamic][General]\n"
            f"Image={dynamic.as_uri()}\n\n"
            "[Containments][2][Wallpaper][org.kde.slideshow][General]\n"
            f"SlidePaths={tmp_path / 'slides'}\n",
            encoding="utf-8",
        )

    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    write("com.github.zzag.dynamic")
    assert desktop_wallpaper.kde_wallpapers(dark=False) == [dynamic]
    write("org.kde.slideshow")
    assert desktop_wallpaper.kde_wallpapers(dark=False) == [slides / "b.jpg"]
    write("org.kde.image")
    assert desktop_wallpaper.kde_wallpapers(dark=False) == [old]


def test_mica_takes_the_variant_the_desktop_shows(monkeypatch, tmp_path):
    from harmonia import desktop_wallpaper, linux_backdrop

    asked = []
    monkeypatch.setattr(
        desktop_wallpaper, "configured_wallpapers", lambda *, dark: asked.append(dark) or []
    )
    monkeypatch.setattr(desktop_wallpaper, "desktop_prefers_dark", lambda: False)
    monkeypatch.setattr(linux_backdrop, "material_css", lambda *_args, **_kwargs: "")

    class Style:
        def get_dark(self):
            return True  # Harmonia dark, the desktop light

    class Window:
        def get_display(self):
            return None

    backdrops = linux_backdrop.LinuxWindowBackdrops.__new__(linux_backdrop.LinuxWindowBackdrops)
    backdrops.kind, backdrops._window, backdrops._style = "mica", Window(), Style()
    backdrops._provider = type("Provider", (), {"load_from_string": lambda *_: None})()
    backdrops._provider_display, backdrops._timer, backdrops.wallpaper = None, 0, None
    backdrops._kwin, backdrops._kwin_surfaces = None, {}
    # No compositor blur: Mica comes from the wallpaper.
    monkeypatch.setattr(backdrops, "_compositor_blur", lambda _window: "")
    monkeypatch.setattr(backdrops, "_install_provider", lambda _window: None)
    monkeypatch.setattr(backdrops, "_tint", lambda _dark: "rgba(0,0,0,0.5)")
    monkeypatch.setattr(linux_backdrop, "set_css_class", lambda *_args: None)

    backdrops._refresh()
    assert asked == [False]


def test_mica_blurs_the_wallpaper_once(tmp_path):
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    from harmonia.linux_backdrop import MICA_SIZE, mica_image

    wallpaper = tmp_path / "wallpaper.png"
    source = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 400, 200)
    source.fill(0x3366CCFF)
    source.savev(str(wallpaper), "png", [], [])
    cache = tmp_path / "cache"
    image = mica_image(wallpaper, cache)
    blurred = GdkPixbuf.Pixbuf.new_from_file(str(image))
    assert max(blurred.get_width(), blurred.get_height()) == MICA_SIZE
    assert mica_image(wallpaper, cache) == image  # cached
    assert len(list(cache.glob("mica-*.png"))) == 1


def test_material_css_tints_mica_and_acrylic(tmp_path):
    from harmonia.linux_backdrop import material_css, rgba

    tint = rgba("#202020", 0.78)
    assert tint == "rgba(32, 32, 32, 0.78)"
    mica = material_css("mica", tint, tmp_path / "mica.png")
    assert "linear-gradient(rgba(32, 32, 32, 0.78)" in mica and 'url("file://' in mica
    assert "background-size: cover" in mica
    acrylic = material_css("acrylic", tint, None)
    assert "background-color: rgba(32, 32, 32, 0.78)" in acrylic
    # Mica without a wallpaper is not shown at all: the theme stays opaque.
    assert material_css("mica", tint, None) == ""


def test_windows_keeps_dwm_and_linux_gets_the_simulated_materials(monkeypatch):
    from harmonia import gtk_backdrop, host

    monkeypatch.setattr(host, "IS_WINDOWS", False)
    from harmonia.linux_backdrop import LinuxWindowBackdrops

    assert isinstance(gtk_backdrop.window_backdrops(), LinuxWindowBackdrops)


def test_dwm_only_rules_need_the_dwm_class():
    from pathlib import Path

    css = (
        Path(__file__).resolve().parents[1] / "src" / "harmonia" / "themes" / "windows11.css"
    ).read_text(encoding="utf-8")
    # GTK's shadow and resize band are dropped only where DWM draws its own.
    assert "window.harmonia-backdrop.csd" not in css
    assert "window.harmonia-backdrop.harmonia-dwm.csd" in css
