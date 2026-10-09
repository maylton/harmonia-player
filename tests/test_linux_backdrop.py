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

    monkeypatch.setattr(desktop_wallpaper, "wallpaper_candidates", lambda *, dark: [])
    monkeypatch.setattr(desktop_wallpaper, "in_flatpak", lambda: False)
    assert "não encontrado" in linux_backdrop.LinuxWindowBackdrops._mica(True)[1]
    monkeypatch.setattr(desktop_wallpaper, "in_flatpak", lambda: True)
    assert "Flatpak" in linux_backdrop.LinuxWindowBackdrops._mica(True)[1]

    broken = tmp_path / "adwaita-d.jxl"
    broken.write_bytes(b"not an image")
    monkeypatch.setattr(desktop_wallpaper, "wallpaper_candidates", lambda *, dark: [broken])
    monkeypatch.setattr(linux_backdrop.host, "cache_dir", lambda: tmp_path / "cache")
    image, reason = linux_backdrop.LinuxWindowBackdrops._mica(True)
    assert image is None and "JPEG XL" in reason


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


def test_gnome_slideshows_resolve_to_their_first_image(tmp_path):
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
