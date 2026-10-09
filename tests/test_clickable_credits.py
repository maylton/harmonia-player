import json

import pytest

from harmonia.models import LibraryItem
from harmonia.ui import CREDIT_SCHEME, credits_markup, item_credits

ELIS = ("artist", "Elis Regina", "UCelis")
TOM = ("artist", "Tom Jobim", "UCtom")
ALBUM = ("album", "Elis & Tom", "MPREb_elis")


def test_every_credit_is_linked_in_order_and_text_is_escaped():
    markup, linked = credits_markup("Elis Regina & Tom Jobim · Elis & Tom", [ELIS, TOM, ALBUM])
    assert linked == [ELIS, TOM, ALBUM]
    assert markup.count("<a ") == 3
    assert "&amp;" in markup and " & " not in markup.replace("&amp;", "")
    assert f'href="{CREDIT_SCHEME}2"' in markup


def test_self_titled_albums_link_the_second_occurrence_to_the_album():
    _markup, linked = credits_markup(
        "Construção · Construção", [("artist", "Construção", "UC1"), ("album", "Construção", "MP1")]
    )
    assert [kind for kind, *_ in linked] == ["artist", "album"]


def test_names_missing_from_the_text_are_skipped():
    markup, linked = credits_markup("Álbum · Elis Regina", [("artist", "Outro", "UC9"), ELIS])
    assert linked == [ELIS]
    assert markup.startswith("Álbum · <a ")


def test_cached_tracks_fall_back_to_an_artist_search_but_playlists_do_not():
    cached = LibraryItem("v", "Águas de Março", "Elis Regina · 3:17", kind="songs")
    assert item_credits(cached) == [("search", "Elis Regina", "Elis Regina")]
    playlist = LibraryItem("PL", "Mix", "Playlist · Maylton", kind="playlists")
    assert item_credits(playlist) == []
    linked = LibraryItem("v", "T", "x", kind="songs", links=(ELIS, ALBUM))
    assert item_credits(linked) == [ELIS, ALBUM]


def test_items_survive_json_and_ignore_fields_from_other_versions():
    from dataclasses import asdict

    item = LibraryItem("v", "T", "Elis Regina", kind="songs", links=(ELIS,))

    payload = json.loads(json.dumps(asdict(item)))
    payload["campo_do_futuro"] = 1
    restored = LibraryItem.from_dict(payload)
    assert restored == item
    assert isinstance(restored.links[0], tuple)


def gtk_or_skip():
    gi = pytest.importorskip("gi")
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk

    if Gdk.Display.get_default() is None:
        pytest.skip("sem display")
    Adw.init()
    return Adw, Gtk


def test_credits_label_routes_links_to_navigation():
    _adw, _gtk = gtk_or_skip()
    from harmonia.ui import CreditsLabel

    calls = []
    label = CreditsLabel(lambda *args: calls.append(args))
    label.show_item(
        LibraryItem("v", "T", "Elis Regina · Elis & Tom", kind="songs", links=(ELIS, ALBUM))
    )
    assert label.emit("activate-link", f"{CREDIT_SCHEME}1") is True
    assert calls == [("album", "MPREb_elis", "Elis & Tom")]
    # Re-showing another item updates the targets without stacking handlers.
    label.show_item(LibraryItem("w", "T", "Tom Jobim", kind="songs", links=(TOM,)))
    label.emit("activate-link", f"{CREDIT_SCHEME}0")
    assert calls[-1] == ("artist", "UCtom", "Tom Jobim") and len(calls) == 2


def test_action_row_subtitles_become_clickable():
    Adw, Gtk = gtk_or_skip()
    from harmonia.ui import link_row_subtitle

    calls = []
    row = Adw.ActionRow()
    item = LibraryItem(
        "v", "Rock & Roll", "Elis Regina · Elis & Tom", kind="songs", links=(ELIS, ALBUM)
    )
    link_row_subtitle(row, item, lambda *args: calls.append(args))
    assert row.get_title() == "Rock &amp; Roll"  # escaped because the row uses markup
    labels, pending = [], [row]
    while pending:
        widget = pending.pop()
        if isinstance(widget, Gtk.Label) and widget.has_css_class("credits"):
            labels.append(widget)
        child = widget.get_first_child()
        while child:
            pending.append(child)
            child = child.get_next_sibling()
    assert len(labels) == 1
    labels[0].emit("activate-link", f"{CREDIT_SCHEME}0")
    assert calls == [("artist", "UCelis", "Elis Regina")]


def test_card_subtitles_live_outside_the_card_button():
    _adw, Gtk = gtk_or_skip()
    from harmonia.ui import CreditsLabel
    from harmonia.window_artwork import WindowArtworkMixin
    from harmonia.window_home import WindowHomeMixin
    from harmonia.window_item_menu import WindowItemMenuMixin
    from harmonia.window_library import WindowLibraryMixin
    from harmonia.window_playback import WindowPlaybackMixin
    from harmonia.window_shelves import WindowShelvesMixin

    class Window(
        WindowLibraryMixin,
        WindowShelvesMixin,
        WindowArtworkMixin,
        WindowHomeMixin,
        WindowItemMenuMixin,
        WindowPlaybackMixin,
    ):
        def navigate_credit(self, *_args):
            pass

        def _load_artwork(self, *_args, **_kwargs):
            pass

    item = LibraryItem("MP1", "Elis & Tom", "Álbum · Elis Regina", kind="albums", links=(ELIS,))
    card = Window()._media_card_button(item, 168, lambda: None)
    pending, found = [card], []
    while pending:
        widget = pending.pop()
        if isinstance(widget, CreditsLabel):
            found.append(widget)
            ancestor = widget.get_parent()
            while ancestor is not None:
                assert not isinstance(ancestor, Gtk.Button), (
                    "links inside a GtkButton never get clicks"
                )
                ancestor = ancestor.get_parent()
        child = widget.get_first_child()
        while child:
            pending.append(child)
            child = child.get_next_sibling()
    assert len(found) == 1


def test_navigation_opens_artist_album_or_search_and_closes_the_expanded_player():
    from harmonia.window_library import WindowLibraryMixin

    class Revealer:
        def __init__(self):
            self.revealed = True

        def get_reveal_child(self):
            return self.revealed

    class Window(WindowLibraryMixin):
        def __init__(self):
            self.opened, self.searched, self.expanded_revealer = [], [], Revealer()

        def open_item(self, item):
            self.opened.append((item.kind, item.id, item.title))

        def _search_for(self, query):
            self.searched.append(query)

        def _hide_expanded_player(self):
            self.expanded_revealer.revealed = False

    window = Window()
    window.navigate_credit("artist", "UCelis", "Elis Regina")
    assert window.expanded_revealer.revealed is False
    window.navigate_credit("album", "MPREb_elis", "Elis & Tom")
    window.navigate_credit("search", "Elis Regina", "Elis Regina")
    assert window.opened == [
        ("artists", "UCelis", "Elis Regina"),
        ("albums", "MPREb_elis", "Elis & Tom"),
    ]
    assert window.searched == ["Elis Regina"]
