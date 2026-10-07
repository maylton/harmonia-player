import re
from pathlib import Path

import pytest

from harmonia import blur_textures

STYLE = Path(__file__).resolve().parents[1] / "src" / "harmonia" / "style.css"


def test_every_css_blurred_backdrop_has_a_prerendered_radius():
    css = STYLE.read_text(encoding="utf-8")
    for name, radius in blur_textures.BLUR_RADII.items():
        block = re.search(rf"\.{re.escape(name)}\s*\{{([^}}]*)\}}", css).group(1)
        assert f"blur({radius}px)" in block, name
    assert "picture.prerendered-blur { filter: none; }" in css


def test_wider_blurs_keep_fewer_pixels():
    wide = blur_textures.shrunk_size(128, 1280, 720)
    narrow = blur_textures.shrunk_size(18, 1280, 720)
    assert max(wide) < max(narrow)
    assert wide[0] > wide[1]  # aspect ratio kept
    assert min(blur_textures.shrunk_size(128, 4000, 10)) >= 2


def test_only_windows_software_rendering_swaps_the_css_blur(monkeypatch):
    class PictureStub:
        def has_css_class(self, name):
            return name == "expanded-backdrop"

    monkeypatch.setattr(blur_textures, "renders_in_software", lambda widget: True)
    monkeypatch.setattr(blur_textures.host, "IS_WINDOWS", False)
    assert not blur_textures.wanted(PictureStub())
    monkeypatch.setattr(blur_textures.host, "IS_WINDOWS", True)
    assert blur_textures.wanted(PictureStub())
    monkeypatch.setattr(blur_textures, "renders_in_software", lambda widget: False)
    assert not blur_textures.wanted(PictureStub())


def test_blurred_texture_is_small_and_smooth(tmp_path):
    gi = pytest.importorskip("gi")
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    source = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 400, 200)
    source.fill(0x3366CCFF)
    path = tmp_path / "cover.png"
    source.savev(str(path), "png", [], [])
    texture = blur_textures.blurred_texture(str(path), 128)
    assert max(texture.get_width(), texture.get_height()) == blur_textures.SMOOTH_SIZE
    assert texture.get_width() == 2 * texture.get_height()
