import ctypes

import pytest

from harmonia import host

windows_only = pytest.mark.skipif(not host.IS_WINDOWS, reason="usa o DWM e o GDK do Windows")


def test_backdrops_are_a_no_op_without_windows_materials(monkeypatch):
    from harmonia.gtk_backdrop import GtkWindowBackdrops

    monkeypatch.setattr(host, "WINDOW_BACKDROPS", False)
    backdrops = GtkWindowBackdrops()
    assert backdrops.set_kind("mica", object()) is False
    assert backdrops.active is False


def test_material_names_match_the_preference_values():
    from harmonia.preferences import Preferences
    from harmonia.windows_backdrop import BACKDROPS

    assert set(BACKDROPS) | {"none"} == set(Preferences.BACKDROPS)


@windows_only
def test_hidden_window_exposes_its_hwnd_and_accepts_a_material():
    from gi.repository import Gtk

    from harmonia import windows_backdrop
    from harmonia.gtk_win32 import window_handle

    window = Gtk.Window()
    assert window_handle(window) is None  # not realized yet
    window.realize()  # creates the native window without showing it
    try:
        hwnd = window_handle(window)
        assert hwnd and ctypes.windll.user32.IsWindow(hwnd)
        applied = windows_backdrop.apply(hwnd, "mica", dark=True)
        assert isinstance(applied, bool)  # False on Windows 10 and early Windows 11
        windows_backdrop.remove(hwnd)
    finally:
        window.destroy()
