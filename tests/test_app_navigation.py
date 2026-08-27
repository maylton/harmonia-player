from pathlib import Path

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
    source = (root / "src" / "harmonia" / "app.py").read_text(encoding="utf-8")

    assert "Gtk.RevealerTransitionType.FADE_SLIDE_UP" not in source
    assert "Gtk.RevealerTransitionType.SLIDE_UP" in source
