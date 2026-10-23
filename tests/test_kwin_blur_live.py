"""kwin_blur.py against a real KWin, on GTK's own Wayland connection.

Run by CI's linux-blur job, which starts a headless kwin_wayland and points
WAYLAND_DISPLAY at it; skipped elsewhere.
"""

from __future__ import annotations

import ctypes
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("HARMONIA_LIVE_KWIN"), reason="needs the headless KWin of CI"
)


def gtk_on_wayland():
    import gi

    gi.require_version("Gdk", "4.0")
    gi.require_version("GdkWayland", "4.0")
    gi.require_version("Gtk", "4.0")
    # GdkWayland brings get_wl_display() to the display, as kwin_blur.connect does.
    from gi.repository import Gdk, GdkWayland, GLib, Gtk  # noqa: F401

    Gtk.init()
    display = Gdk.Display.get_default()
    assert "Wayland" in type(display).__name__, type(display).__name__
    return display, GLib, Gtk


def test_globals_are_bound_on_a_queue_of_our_own():
    from harmonia import kwin_blur

    display, _glib, _gtk = gtk_on_wayland()
    blur = kwin_blur.WaylandBlur(kwin_blur.wayland_display(display))

    assert b"wl_compositor" in blur.globals, sorted(blur.globals)
    # The same calls the blur makes: a region, rectangles in it, its destruction.
    compositor = blur._bind_global(b"wl_compositor", blur.compositor_interface, 4)
    region = blur._call(compositor, 1, blur.region_interface, ctypes.c_void_p(None))
    for rect in kwin_blur.rounded_rect_region(0, 0, 300, 200, 8):
        blur._call(region, 1, None, *(ctypes.c_int32(value) for value in rect))
    blur._call(region, 0, None, flags=kwin_blur.DESTROY)
    lib = blur._lib
    assert lib.wl_display_roundtrip_queue(blur._display, blur._queue) >= 0
    assert lib.wl_display_get_error(blur._display) == 0  # KWin accepted every request


def test_blur_is_requested_for_a_window_when_kwin_offers_it():
    from harmonia import kwin_blur

    display, glib, gtk = gtk_on_wayland()
    backend = kwin_blur.connect(display)
    if backend is None:
        pytest.skip("this KWin does not offer org_kde_kwin_blur (no OpenGL blur effect)")
    window = gtk.Window(default_width=320, default_height=240)
    window.present()
    context = glib.MainContext.default()
    for _ in range(50):
        context.iteration(False)
    handle = kwin_blur.surface_handle(window.get_surface())
    backend.set_region(handle, kwin_blur.rounded_rect_region(0, 0, 320, 240, 8))
    backend.unset(handle)
    lib = backend._lib
    assert lib.wl_display_roundtrip_queue(backend._display, backend._queue) >= 0
    assert lib.wl_display_get_error(backend._display) == 0
