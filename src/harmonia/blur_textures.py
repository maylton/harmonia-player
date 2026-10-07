"""Pre-blurred artwork for backdrops when GTK renders in software.

The artwork backdrops (expanded player, ambient background, album and
artist headers) are blurred with CSS filters. GPU renderers do that for
free, but GTK's Cairo renderer, which Windows builds use, recomputes the
blur on every frame that touches the backdrop: the expanded player's lyrics
and queue then draw at about 11 frames per second. A heavily blurred image
is just a few soft colours, so shrinking the artwork to a handful of pixels
and scaling it back up with smoothing gives the same look once, when the
artwork changes, at no cost per frame.
"""

from __future__ import annotations

import logging

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gsk, Gtk  # noqa: E402

from . import host  # noqa: E402

LOGGER = logging.getLogger(__name__)
# Blur radius of each backdrop class in style.css.
BLUR_RADII = {
    "expanded-backdrop": 128,
    "ambient-background": 64,
    "expanded-backdrop-base": 48,
    "detail-backdrop": 28,
    "artist-backdrop": 18,
}
CSS_CLASS = "prerendered-blur"  # style.css turns the CSS filter off
SMOOTH_SIZE = 256  # smoothed result; Gtk.Picture scales it to fit


def blur_radius(picture: Gtk.Picture) -> int | None:
    return next(
        (radius for name, radius in BLUR_RADII.items() if picture.has_css_class(name)), None
    )


def shrunk_size(radius: int, width: int, height: int) -> tuple[int, int]:
    """Size the artwork shrinks to: the wider the blur, the fewer pixels survive."""
    longest = max(6, round(1600 / radius))
    scale = longest / max(width, height)
    return max(2, round(width * scale)), max(2, round(height * scale))


def renders_in_software(widget: Gtk.Widget) -> bool:
    native = widget.get_native()
    renderer = native.get_renderer() if native is not None else None
    return isinstance(renderer, Gsk.CairoRenderer)


def wanted(picture: Gtk.Picture) -> bool:
    """Only Windows builds, which render with Cairo, swap their CSS blur."""
    return host.IS_WINDOWS and blur_radius(picture) is not None and renders_in_software(picture)


def blurred_texture(path: str, radius: int) -> Gdk.Texture:
    source = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 160, 160, True)
    width, height = shrunk_size(radius, source.get_width(), source.get_height())
    tiny = source.scale_simple(width, height, GdkPixbuf.InterpType.HYPER)
    scale = SMOOTH_SIZE / max(width, height)
    smooth = tiny.scale_simple(
        max(1, round(width * scale)), max(1, round(height * scale)), GdkPixbuf.InterpType.BILINEAR
    )
    memory_format = Gdk.MemoryFormat.R8G8B8A8 if smooth.get_has_alpha() else Gdk.MemoryFormat.R8G8B8
    return Gdk.MemoryTexture.new(
        smooth.get_width(),
        smooth.get_height(),
        memory_format,
        smooth.read_pixel_bytes(),
        smooth.get_rowstride(),
    )


def show(picture: Gtk.Picture, path: str) -> bool:
    """Show ``path`` in ``picture``; pre-blurred when that saves per-frame work.

    Returns whether the pre-blurred version was used; otherwise the caller
    shows the file as usual and the CSS filter blurs it.
    """
    if not wanted(picture):
        picture.remove_css_class(CSS_CLASS)
        return False
    try:
        texture = blurred_texture(path, blur_radius(picture))
    except GLib.Error:
        LOGGER.debug("Não foi possível pré-desfocar %s", path, exc_info=True)
        picture.remove_css_class(CSS_CLASS)
        return False
    picture.add_css_class(CSS_CLASS)
    picture.set_paintable(texture)
    return True
