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


def test_material_waits_for_the_native_window_then_reapplies(monkeypatch):
    import harmonia.gtk_backdrop as gtk_backdrop
    from harmonia.preferences import Preferences
    from harmonia.window_preferences import WindowPreferencesMixin

    calls = []

    class FakeBackdrops:
        def set_kind(self, kind, window):
            calls.append(kind)
            return True

    class WindowStub(WindowPreferencesMixin):
        realized = False

        def __init__(self):
            self.preferences = Preferences(theme="windows11", backdrop="mica")
            self.handlers = []
            self.reapplied = 0

        def get_realized(self):
            return self.realized

        def connect_after(self, signal, callback):
            self.handlers.append((signal, callback))
            return len(self.handlers)

        def _apply_appearance_preferences(self):
            self.reapplied += 1

    monkeypatch.setattr(host, "WINDOW_BACKDROPS", True)
    monkeypatch.setattr(host, "PLATFORM", "windows")
    monkeypatch.setattr(gtk_backdrop, "GtkWindowBackdrops", FakeBackdrops)
    monkeypatch.setattr("harmonia.window_preferences.GLib.idle_add", lambda callback: callback())

    window = WindowStub()
    # Before realize: opaque for now, and one retry queued for realize.
    assert window._apply_window_backdrop() is False
    assert window._apply_window_backdrop() is False
    assert calls == [] and [signal for signal, _ in window.handlers] == ["realize"]

    window.realized = True
    window.handlers[0][1](window)
    assert window.reapplied == 1
    assert window._apply_window_backdrop() is True
    assert calls == ["mica"]


def test_returning_to_the_window_sets_the_material_again(monkeypatch):
    from harmonia.gtk_backdrop import GtkWindowBackdrops

    applied, kept = [], []

    class WindowStub:
        active = True

        def is_active(self):
            return self.active

        def has_css_class(self, name):
            return True

    backdrops = GtkWindowBackdrops.__new__(GtkWindowBackdrops)
    backdrops.kind = "acrylic"
    backdrops._apply = applied.append
    backdrops._hwnd = lambda window: 42
    monkeypatch.setattr("harmonia.windows_backdrop.keep_active", kept.append)

    window = WindowStub()
    backdrops._activation_changed(window, None)
    assert applied == [window] and kept == []

    window.active = False
    backdrops._activation_changed(window, None)
    assert kept == [42]  # Acrylic stays frosted in the background

    backdrops.kind = "mica"
    backdrops._activation_changed(window, None)
    assert kept == [42]  # Mica follows Windows and turns solid there


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
