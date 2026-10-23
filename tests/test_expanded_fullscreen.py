"""Full screen for the expanded player: the button, F and F11, and Esc."""

import pytest

gi = pytest.importorskip("gi")
from gi.repository import Gdk  # noqa: E402

from harmonia.window_expanded import IDLE_CSS_CLASS, WindowExpandedPlayerMixin  # noqa: E402


class Widget:
    def __init__(self):
        self.visible, self.css, self.cursor, self.icon, self.tooltip = True, set(), None, "", ""

    def set_visible(self, visible):
        self.visible = visible

    def add_css_class(self, name):
        self.css.add(name)

    def remove_css_class(self, name):
        self.css.discard(name)

    def set_cursor(self, cursor):
        self.cursor = cursor

    def set_cursor_from_name(self, name):
        self.cursor = name

    def set_icon_name(self, name):
        self.icon = name

    def set_tooltip_text(self, text):
        self.tooltip = text


class Revealer(Widget):
    revealed = False

    def get_reveal_child(self):
        return self.revealed


class Window(WindowExpandedPlayerMixin):
    def __init__(self, *, playing=True):
        self.full = False
        self.playing = playing
        self.expanded_revealer = Revealer()
        self.expanded_up_next_slot = Widget()
        self.expanded_fullscreen_button = Widget()
        self.expanded_surface = Widget()
        self.player_bar = Widget()

    def _show_expanded_player(self):
        self.expanded_revealer.revealed = self.playing

    def is_fullscreen(self):
        return self.full

    def fullscreen(self):
        self.full = True
        self._fullscreen_changed()

    def unfullscreen(self):
        self.full = False
        self._fullscreen_changed()

    def get_surface(self):
        return None


def press(window, keyval, state=0):
    return window._expanded_key_pressed(None, keyval, 0, Gdk.ModifierType(state))


def test_full_screen_opens_the_expanded_player_without_up_next():
    window = Window()
    window._toggle_fullscreen()
    assert window.full and window.expanded_revealer.revealed
    assert not window.expanded_up_next_slot.visible
    assert window.expanded_fullscreen_button.icon == "view-restore-symbolic"
    window._toggle_fullscreen()
    assert not window.full and window.expanded_up_next_slot.visible
    assert window.expanded_fullscreen_button.icon == "view-fullscreen-symbolic"


def test_full_screen_needs_something_playing():
    window = Window(playing=False)
    window._toggle_fullscreen()
    assert not window.full


def test_escape_leaves_full_screen_before_collapsing_the_player():
    window = Window()
    window._toggle_fullscreen()
    assert press(window, Gdk.KEY_Escape)
    assert not window.full and window.expanded_revealer.revealed


def test_f_toggles_only_over_the_expanded_player_and_without_modifiers():
    window = Window()
    assert not press(window, Gdk.KEY_f)  # the pages may hold a search entry
    window.expanded_revealer.revealed = True
    assert not press(window, Gdk.KEY_f, Gdk.ModifierType.CONTROL_MASK)
    assert press(window, Gdk.KEY_f) and window.full
    assert press(window, Gdk.KEY_F11) and not window.full


def test_controls_rest_then_wake_and_stop_resting_out_of_full_screen():
    window = Window()
    window._toggle_fullscreen()
    assert window._fullscreen_idle_source
    window._rest_fullscreen_controls()
    assert IDLE_CSS_CLASS in window.expanded_surface.css
    assert window.expanded_surface.cursor == "none"
    window._wake_fullscreen_controls()
    assert IDLE_CSS_CLASS not in window.expanded_surface.css
    assert window.expanded_surface.cursor is None
    window.unfullscreen()
    assert not window._fullscreen_idle_source


def test_media_frame_keeps_its_size_out_of_full_screen():
    assert Window()._expanded_media_scale() == 1.0
