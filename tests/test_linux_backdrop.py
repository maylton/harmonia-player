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
    assert desktop_wallpaper.kde_wallpaper(dark=False) == image

    package = tmp_path / "Next"
    (package / "contents" / "images").mkdir(parents=True)
    (package / "contents" / "images_dark").mkdir(parents=True)
    (package / "contents" / "images" / "1920x1080.png").write_bytes(b"x" * 10)
    (package / "contents" / "images" / "3840x2160.png").write_bytes(b"x" * 40)
    (package / "contents" / "images_dark" / "3840x2160.png").write_bytes(b"x" * 30)
    write_kde_config(config, str(package))
    # The largest image, from images_dark in dark mode.
    assert desktop_wallpaper.kde_wallpaper(dark=False).parent.name == "images"
    assert desktop_wallpaper.kde_wallpaper(dark=False).name == "3840x2160.png"
    assert desktop_wallpaper.kde_wallpaper(dark=True).parent.name == "images_dark"


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
