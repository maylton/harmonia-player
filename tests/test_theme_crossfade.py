"""A theme change fades over a picture of the window, or applies at once."""

import pytest

pytest.importorskip("gi")
from harmonia.window_preferences import WindowPreferencesMixin


class Unshown(WindowPreferencesMixin):
    app_overlay = None

    def get_native(self):
        return None

    def get_mapped(self):
        return False


def test_a_window_not_on_screen_changes_at_once_without_a_picture():
    applied = []
    Unshown()._crossfade(lambda: applied.append(True))
    assert applied == [True]
