from harmonia.app import HarmoniaWindow
from harmonia.window_account import WindowAccountMixin
from harmonia.window_actions import WindowActionsMixin
from harmonia.window_detail import WindowDetailMixin
from harmonia.window_history import WindowHistoryMixin
from harmonia.window_home import WindowHomeMixin
from harmonia.window_insights import WindowInsightsMixin
from harmonia.window_library import WindowLibraryMixin
from harmonia.window_lyrics import WindowLyricsMixin
from harmonia.window_playback import WindowPlaybackMixin
from harmonia.window_preferences import WindowPreferencesMixin
from harmonia.window_search import WindowSearchMixin

DOMAIN_METHODS = {
    WindowPreferencesMixin: "show_settings",
    WindowHistoryMixin: "_render_history",
    WindowInsightsMixin: "show_insights",
    WindowHomeMixin: "_render_home",
    WindowLibraryMixin: "_render",
    WindowDetailMixin: "_show_detail",
    WindowSearchMixin: "search",
    WindowActionsMixin: "_mutate",
    WindowLyricsMixin: "_render_lyrics",
    WindowPlaybackMixin: "play_item",
    WindowAccountMixin: "sync",
}


def test_window_delegates_each_domain_to_a_mixin():
    for mixin, method_name in DOMAIN_METHODS.items():
        assert mixin in HarmoniaWindow.__mro__
        assert method_name not in HarmoniaWindow.__dict__
        assert getattr(HarmoniaWindow, method_name) is mixin.__dict__[method_name]


def test_window_keeps_only_composition_and_chrome_methods():
    direct_methods = {name for name, value in HarmoniaWindow.__dict__.items() if callable(value)}

    assert len(direct_methods) <= 30
    assert {"__init__", "_build_header", "_build_sidebar", "_build_player_bar"} <= direct_methods
