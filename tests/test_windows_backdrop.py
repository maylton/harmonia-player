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
    monkeypatch.setattr(gtk_backdrop, "window_backdrops", FakeBackdrops)
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
    drawn = []
    WindowStub.queue_draw = lambda self: drawn.append(self)

    window = WindowStub()
    for _ in range(3):
        backdrops._schedule_restore(window)
    assert len(queued) == 1
    callback, target = queued[0]
    callback(target)
    # Cairo only repaints damaged regions: the whole window is redrawn.
    assert applied == [window] and refreshed == [42] and drawn == [window]
    backdrops._schedule_restore(window)  # a later message queues again
    assert len(queued) == 2

    backdrops.kind = "none"
    window._harmonia_restore_queued = False
    backdrops._schedule_restore(window)
    assert len(queued) == 2


def test_messages_route_to_restore_rebuild_or_cloak_watch(monkeypatch):
    from harmonia import windows_backdrop
    from harmonia.gtk_backdrop import GtkWindowBackdrops

    restores, watched, rebuilt = [], [], []
    monkeypatch.setattr(
        "harmonia.gtk_backdrop.GLib.idle_add", lambda callback, window: restores.append(window)
    )
    monkeypatch.setattr(windows_backdrop, "rebuild", rebuilt.append)
    monkeypatch.setattr(windows_backdrop, "refresh_frame", lambda hwnd: None)

    class WindowStub:
        def queue_draw(self):
            pass

    backdrops = GtkWindowBackdrops.__new__(GtkWindowBackdrops)
    backdrops.kind = "mica"
    backdrops._apply = lambda window: True
    backdrops._hwnd = lambda window: 42
    backdrops._watch_cloaking = watched.append
    window = WindowStub()

    backdrops._on_message(window, windows_backdrop.WM_ACTIVATE, 0)  # focus lost
    assert watched == [window] and restores == []

    backdrops._on_message(window, windows_backdrop.WM_ACTIVATE, 1)  # focus back
    assert restores == [window]
    backdrops._restore(window)
    assert rebuilt == []  # an ordinary focus switch needs no rebuild

    backdrops._on_message(window, windows_backdrop.WM_DWMCOMPOSITIONCHANGED, 0)
    backdrops._restore(window)
    assert rebuilt == [42]  # after a fullscreen game the visual is recreated once
    backdrops._restore(window)
    assert rebuilt == [42]


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
        windows_backdrop.watch(hwnd, lambda message, wparam: seen.append((message, wparam)))
        windows_backdrop.watch(hwnd, lambda *_: seen.append("second watcher"))  # ignored
        send = ctypes.windll.user32.SendMessageW
        send(hwnd, windows_backdrop.WM_DWMCOMPOSITIONCHANGED, 0, 0)
        send(hwnd, windows_backdrop.WM_ACTIVATE, 0, 0)
        expected = [
            (windows_backdrop.WM_DWMCOMPOSITIONCHANGED, 0),
            (windows_backdrop.WM_ACTIVATE, 0),
        ]
        assert seen == expected
        windows_backdrop.refresh_frame(hwnd)  # must not report anything new
        windows_backdrop.rebuild(hwnd)
        assert seen == expected
        assert windows_backdrop.is_cloaked(hwnd) is False  # uncloaked again
        state = windows_backdrop.backdrop_state(hwnd)
        assert state["composition"] is True and state["foreground"] is False
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
    # Blur-behind goes off first, then the material passes through "none" so
    # DWM rebuilds it even when the type did not change.
    order = [call for call in calls if call[0] != "attribute" or call[1] == 38]
    assert order == [("blur", False), ("attribute", 38), ("extend", -1), ("attribute", 38)]

    calls.clear()
    windows_backdrop.remove(1)
    assert ("blur", True) in calls and ("extend", 0) in calls


def test_popovers_take_the_flyout_material_without_arrow(monkeypatch):
    from harmonia import windows_backdrop
    from harmonia.gtk_backdrop import POPOVER_CSS_CLASS, GtkWindowBackdrops

    applied = []
    monkeypatch.setattr(
        windows_backdrop, "apply", lambda hwnd, kind, dark: applied.append(kind) or True
    )

    class PopoverStub:
        def __init__(self):
            self.arrow = True
            self.classes = set()

        def set_has_arrow(self, value):
            self.arrow = value

        def add_css_class(self, name):
            self.classes.add(name)

        def remove_css_class(self, name):
            self.classes.discard(name)

    class Style:
        def get_dark(self):
            return True

    backdrops = GtkWindowBackdrops.__new__(GtkWindowBackdrops)
    backdrops._style = Style()
    backdrops._hwnd = lambda widget: 7
    popover = PopoverStub()

    backdrops.kind, backdrops.active = "mica", True
    backdrops._apply_popover(popover)
    # Popups are never activated, so they use the transient (flyout) material.
    assert applied == [windows_backdrop.TRANSIENT]
    assert popover.arrow is False and POPOVER_CSS_CLASS in popover.classes

    backdrops.kind = "none"
    backdrops._apply_popover(popover)
    assert popover.arrow is True and POPOVER_CSS_CLASS not in popover.classes


def test_popover_attachment_is_a_no_op_without_windows_materials(monkeypatch):
    from harmonia.gtk_backdrop import GtkWindowBackdrops

    monkeypatch.setattr(host, "WINDOW_BACKDROPS", False)
    connected = []

    class PopoverStub:
        def connect(self, *args):
            connected.append(args)

    GtkWindowBackdrops().attach_popover(PopoverStub())
    assert connected == []


def test_windows_material_replaces_the_cover_on_detail_pages():
    from pathlib import Path

    css = (
        Path(__file__).resolve().parents[1] / "src" / "harmonia" / "themes" / "windows11.css"
    ).read_text(encoding="utf-8")
    for name in (".detail-backdrop", ".artist-backdrop", ".detail-backdrop-shade"):
        assert f"window.harmonia-backdrop {name}" in css
    assert "window.harmonia-backdrop .detail-surface" in css
    assert "popover.background.harmonia-backdrop-popover" in css


def test_expanded_player_shows_the_material_once_revealed(monkeypatch):
    from harmonia.preferences import Preferences
    from harmonia.window_preferences import WindowPreferencesMixin

    class Widget:
        def __init__(self):
            self.visible, self.opacity, self.classes, self.handlers = True, 1.0, set(), {}

        def set_visible(self, value):
            self.visible = value

        def set_opacity(self, value):
            self.opacity = value

        def add_css_class(self, name):
            self.classes.add(name)

        def remove_css_class(self, name):
            self.classes.discard(name)

        def has_css_class(self, name):
            return name in self.classes

        def connect(self, signal, callback):
            self.handlers[signal] = callback

    class Revealer(Widget):
        reveal = revealed = False

        def get_reveal_child(self):
            return self.reveal

        def get_child_revealed(self):
            return self.revealed

    class Style(Widget):
        def get_dark(self):
            return True

    class WindowStub(WindowPreferencesMixin):
        def __init__(self):
            self.preferences = Preferences(theme="windows11")
            self.expanded_surface = Widget()
            self.expanded_backdrop_base = Widget()
            self.expanded_backdrop = Widget()
            self.expanded_backdrop_shade = Widget()
            self.expanded_revealer = Revealer()
            self.root = Widget()
            self.ambient_background = Widget()

    monkeypatch.setattr(host, "WINDOW_BACKDROPS", True)
    monkeypatch.setattr("harmonia.window_preferences.Adw.StyleManager.get_default", Style)
    window = WindowStub()
    window._apply_expanded_material(True)
    assert not window.expanded_backdrop.visible
    assert "expanded-material" in window.expanded_surface.classes

    # Sliding in: still opaque over the pages.
    window.expanded_revealer.reveal = True
    window._update_expanded_reveal()
    assert window.root.opacity == 1 and "expanded-revealed" not in window.expanded_surface.classes
    # Revealed: the pages are hidden and only the material shows.
    window.expanded_revealer.revealed = True
    window._update_expanded_reveal()
    assert window.root.opacity == 0 and "expanded-revealed" in window.expanded_surface.classes
    # Hiding: opaque again at once.
    window.expanded_revealer.reveal = False
    window._update_expanded_reveal()
    assert window.root.opacity == 1 and "expanded-revealed" not in window.expanded_surface.classes

    window.preferences.expanded_cover = True
    window._apply_expanded_material(True)
    assert window.expanded_backdrop.visible
    assert "expanded-material" not in window.expanded_surface.classes


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
