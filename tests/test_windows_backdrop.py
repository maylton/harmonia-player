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


def test_material_is_restored_after_focus_display_and_composition_changes():
    from harmonia.windows_backdrop import (
        WM_ACTIVATE,
        WM_DISPLAYCHANGE,
        WM_DWMCOMPOSITIONCHANGED,
        needs_reapply,
    )

    assert needs_reapply(WM_ACTIVATE, 1)  # WA_ACTIVE
    assert needs_reapply(WM_ACTIVATE, 2 | (1 << 16))  # WA_CLICKACTIVE, high word set
    assert not needs_reapply(WM_ACTIVATE, 0)  # WA_INACTIVE: Windows shows its colour
    assert needs_reapply(WM_DWMCOMPOSITIONCHANGED, 0)  # fullscreen games
    assert needs_reapply(WM_DISPLAYCHANGE, 0)
    assert not needs_reapply(0x0005, 0)  # WM_SIZE


def test_a_burst_of_messages_restores_the_material_once(monkeypatch):
    from harmonia.gtk_backdrop import GtkWindowBackdrops

    queued, applied, refreshed = [], [], []
    monkeypatch.setattr(
        "harmonia.gtk_backdrop.GLib.idle_add",
        lambda callback, window: queued.append((callback, window)),
    )
    monkeypatch.setattr("harmonia.windows_backdrop.refresh_frame", refreshed.append)

    class WindowStub:
        pass

    backdrops = GtkWindowBackdrops.__new__(GtkWindowBackdrops)
    backdrops.kind = "mica"
    backdrops._apply = lambda window: applied.append(window) or True
    backdrops._hwnd = lambda window: 42

    window = WindowStub()
    for _ in range(3):
        backdrops._schedule_restore(window)
    assert len(queued) == 1
    callback, target = queued[0]
    callback(target)
    assert applied == [window] and refreshed == [42]
    backdrops._schedule_restore(window)  # a later message queues again
    assert len(queued) == 2

    backdrops.kind = "none"
    window._harmonia_restore_queued = False
    backdrops._schedule_restore(window)
    assert len(queued) == 2


@windows_only
def test_subclass_sees_messages_after_gdk_and_does_not_loop():
    from gi.repository import Gtk

    from harmonia import windows_backdrop
    from harmonia.gtk_win32 import window_handle

    window = Gtk.Window()
    window.realize()
    hwnd = window_handle(window)
    seen = []
    try:
        windows_backdrop.watch(hwnd, lambda: seen.append("restore"))
        windows_backdrop.watch(hwnd, lambda: seen.append("second watcher"))  # ignored
        send = ctypes.windll.user32.SendMessageW
        send(hwnd, windows_backdrop.WM_DWMCOMPOSITIONCHANGED, 0, 0)
        send(hwnd, windows_backdrop.WM_ACTIVATE, 0, 0)  # inactive: nothing to do
        assert seen == ["restore"]
        windows_backdrop.refresh_frame(hwnd)  # must not trigger another restore
        assert seen == ["restore"]
    finally:
        windows_backdrop.unwatch(hwnd)
        window.destroy()
    assert hwnd not in windows_backdrop._watchers


@windows_only
def test_material_replaces_gdk_blur_behind_transparency(monkeypatch):
    from harmonia import windows_backdrop

    calls = []
    monkeypatch.setattr(
        windows_backdrop, "_blur_behind", lambda hwnd, enable: calls.append(("blur", enable))
    )
    monkeypatch.setattr(
        windows_backdrop,
        "_attribute",
        lambda hwnd, attribute, value: calls.append(("attribute", attribute)) or True,
    )

    class Dwm:
        def DwmExtendFrameIntoClientArea(self, hwnd, margins):
            calls.append(("extend", margins._obj.left))
            return 0

    monkeypatch.setattr(windows_backdrop.ctypes, "windll", type("W", (), {"dwmapi": Dwm()})())
    assert windows_backdrop.apply(1, "mica", dark=True) is True
    # Blur-behind goes off before the frame and the material are set.
    order = [call for call in calls if call[0] != "attribute" or call[1] == 38]
    assert order == [("blur", False), ("extend", -1), ("attribute", 38)]

    calls.clear()
    windows_backdrop.remove(1)
    assert ("blur", True) in calls and ("extend", 0) in calls


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
