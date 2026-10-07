import sys
from pathlib import Path
from types import ModuleType

from harmonia.app import HarmoniaWindow
from harmonia.models import LyricLine, LyricsDocument


class LibraryNavigationStub:
    library_origin = "local"
    library_filter = "songs"
    nav_buttons = {"artists": object()}

    def __init__(self):
        self.rendered = 0
        self.active = None

    def show_library(self):
        self.rendered += 1

    def _set_active_nav(self, key):
        self.active = key


def test_sidebar_category_keeps_the_library_shell():
    window = LibraryNavigationStub()
    HarmoniaWindow.show_category(window, "artists")
    assert (window.library_origin, window.library_filter) == ("youtube", "artists")
    assert window.rendered == 1
    assert window.active == "artists"


def test_unknown_library_category_is_ignored():
    window = LibraryNavigationStub()
    HarmoniaWindow.show_category(window, "unknown")
    assert window.rendered == 0
    assert (window.library_origin, window.library_filter) == ("local", "songs")


def test_login_opens_the_platform_browser_module(monkeypatch):
    import harmonia.window_account as window_account

    opened = []

    class FakeLoginWindow:
        def __init__(self, parent, data_dir, on_success, on_manual):
            opened.append((parent, data_dir, on_success, on_manual))

        def present(self):
            opened.append("presented")

    class Storage:
        web_data_dir = Path("web-auth")

    class LoginStub:
        storage = Storage()

        def _integrated_login_done(self, cookie):
            pass

        def manual_login_dialog(self):
            raise AssertionError("the platform browser should have opened")

    module = ModuleType("harmonia.fake_login")
    module.LoginWindow = FakeLoginWindow
    monkeypatch.setitem(sys.modules, "harmonia.fake_login", module)
    monkeypatch.setattr(window_account.host, "INTEGRATED_LOGIN", True)
    monkeypatch.setattr(window_account.host, "LOGIN_MODULE", "fake_login")
    window = LoginStub()
    HarmoniaWindow.login_dialog(window)

    assert opened[0][0] is window and opened[0][1] == Path("web-auth")
    assert opened[-1] == "presented"


def test_login_skips_the_embedded_browser_where_none_exists(monkeypatch):
    import harmonia.window_account as window_account

    class LoginStub:
        manual = 0

        def manual_login_dialog(self):
            self.manual += 1

    monkeypatch.setattr(window_account.host, "INTEGRATED_LOGIN", False)
    # Importing auth.py would fail, and the fallback path needs a toast overlay
    # the stub lacks, so only the direct route to the manual dialog passes.
    monkeypatch.setitem(sys.modules, "harmonia.auth", None)
    window = LoginStub()
    HarmoniaWindow.login_dialog(window)
    assert window.manual == 1


def test_lyrics_scroll_targets_differ_between_footer_and_expanded_player():
    footer = HarmoniaWindow._lyric_scroll_destination(500, 60, 300, 0, 1000, expanded=False)
    expanded = HarmoniaWindow._lyric_scroll_destination(500, 60, 300, 0, 1000, expanded=True)
    assert footer == 404
    assert expanded == 380
    assert HarmoniaWindow._lyric_scroll_destination(20, 60, 300, 0, 1000, expanded=True) == 0
    assert HarmoniaWindow._lyric_scroll_destination(980, 60, 300, 0, 1000, expanded=True) == 700

    # compute_bounds() is viewport-relative after scrolling; converting back
    # to content coordinates must preserve the same target.
    viewport_row_top = 500 - 240
    assert (
        HarmoniaWindow._lyric_scroll_destination(
            viewport_row_top + 240, 60, 300, 0, 1000, expanded=False
        )
        == footer
    )


def test_stale_lyrics_follow_request_is_discarded_before_touching_scroll():
    view = {"follow_generation": 4}

    result = HarmoniaWindow._follow_lyric_line(None, view, 8, follow_generation=3)

    assert result == 0


class LyricsProgressStub:
    lyrics_offset_ms = 0
    current_lyrics_document = LyricsDocument(
        provider="teste",
        plain="",
        synced=[
            LyricLine(0, "zero"),
            LyricLine(10_000, "um"),
            LyricLine(20_000, "dois"),
        ],
    )
    _lyric_views = []
    _active_lyric_index = 2


def test_synced_lyrics_ignore_transient_backward_player_position():
    window = LyricsProgressStub()

    HarmoniaWindow._update_synced_lyrics(window, 500)

    assert window._active_lyric_index == 2


def test_synced_lyrics_accept_explicit_backward_seek():
    window = LyricsProgressStub()

    HarmoniaWindow._update_synced_lyrics(window, 10_500, allow_backward=True)

    assert window._active_lyric_index == 1


def test_google_artwork_url_requests_context_specific_resolution():
    source = "https://lh3.googleusercontent.com/asset=w120-h120-p-l90-rj"
    assert HarmoniaWindow._sized_artwork_url(source, 1024) == (
        "https://lh3.googleusercontent.com/asset=w1024-h1024-p-l90-rj"
    )
    assert HarmoniaWindow._sized_artwork_url(source) == source
    external = "https://example.com/cover-w120-h120.jpg"
    assert HarmoniaWindow._sized_artwork_url(external, 1024) == external


def test_expanded_player_uses_a_supported_gtk_revealer_transition() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "src" / "harmonia" / "window_chrome" / "expanded_player.py").read_text(
        encoding="utf-8"
    )

    assert "Gtk.RevealerTransitionType.FADE_SLIDE_UP" not in source
    assert "Gtk.RevealerTransitionType.SLIDE_UP" in source


class StackStub:
    def __init__(self):
        self.children = {}
        self.visible = None

    def get_child_by_name(self, name):
        return self.children.get(name)

    def get_visible_child(self):
        return self.visible


def test_late_page_loads_never_pull_the_user_back():
    from harmonia.window_detail import WindowDetailMixin

    window = type("Window", (), {"stack": StackStub()})()
    loading, newer, library = object(), object(), object()
    window.stack.children["detail"] = loading
    window.stack.visible = loading
    assert WindowDetailMixin._loaded_page_visible(window, "detail", loading) is True
    # The user went to another page while the album loaded: update it quietly.
    window.stack.visible = library
    assert WindowDetailMixin._loaded_page_visible(window, "detail", loading) is False
    # Another album was opened meanwhile: this reply is stale.
    window.stack.children["detail"] = newer
    assert WindowDetailMixin._loaded_page_visible(window, "detail", loading) is None
