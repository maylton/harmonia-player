"""Sources the window adds to the main loop end when their work is done."""

from gi.repository import GLib

from harmonia.window_expanded import WindowExpandedPlayerMixin


def test_focusing_the_expanded_close_button_removes_its_idle_source():
    # gtk_widget_grab_focus() returns True: handed to idle_add() as is, it
    # kept the main loop busy on a whole core from the first expansion on.
    focused = []
    window = type("W", (), {})()
    window.expanded_close_button = type(
        "B", (), {"grab_focus": lambda _self: focused.append(1) or True}
    )()

    assert WindowExpandedPlayerMixin._focus_expanded_close(window) is GLib.SOURCE_REMOVE
    assert focused == [1]
