import inspect

import pytest

from harmonia.innertube import parse_library_items, parse_watch_queue
from harmonia.innertube.parsers import _linked_pages
from harmonia.models import LibraryItem
from harmonia.ui import track_artist
from harmonia.window_detail import radio_queue, track_byline


def run(text, browse_id=None, page_type=None):
    item = {"text": text}
    if browse_id:
        item["navigationEndpoint"] = {
            "browseEndpoint": {
                "browseId": browse_id,
                "browseEndpointContextSupportedConfigs": {
                    "browseEndpointContextMusicConfig": {"pageType": page_type}
                },
            }
        }
    return item


def track_renderer():
    return {
        "musicResponsiveListItemRenderer": {
            "flexColumns": [
                {"musicResponsiveListItemFlexColumnRenderer": {"text": {"runs": [run("Águas de Março")]}}},
                {
                    "musicResponsiveListItemFlexColumnRenderer": {
                        "text": {
                            "runs": [
                                run("Elis Regina", "UCelis", "MUSIC_PAGE_TYPE_ARTIST"),
                                run(" & "),
                                run("Tom Jobim", "UCtom", "MUSIC_PAGE_TYPE_ARTIST"),
                            ]
                        }
                    }
                },
                {
                    "musicResponsiveListItemFlexColumnRenderer": {
                        "text": {"runs": [run("Elis & Tom", "MPREb_elis", "MUSIC_PAGE_TYPE_ALBUM")]}
                    }
                },
            ],
            "playlistItemData": {"videoId": "vid1"},
            "navigationEndpoint": {"watchEndpoint": {"videoId": "vid1"}},
        }
    }  # fmt: skip


def test_tracks_keep_the_first_linked_artist_and_album():
    renderer = track_renderer()["musicResponsiveListItemRenderer"]
    assert _linked_pages(renderer) == {
        "artist": "Elis Regina", "artist_id": "UCelis", "album": "Elis & Tom", "album_id": "MPREb_elis",
        "links": (
            ("artist", "Elis Regina", "UCelis"),
            ("artist", "Tom Jobim", "UCtom"),
            ("album", "Elis & Tom", "MPREb_elis"),
        ),
    }  # fmt: skip
    (item,) = parse_library_items({"contents": [track_renderer()]}, kind="songs")
    assert (item.artist_id, item.album_id) == ("UCelis", "MPREb_elis")


def test_radio_queue_items_keep_their_links():
    payload = {
        "playlistPanelVideoRenderer": {
            "videoId": "vid2",
            "title": {"runs": [run("Mas que Nada")]},
            "longBylineText": {
                "runs": [
                    run("Jorge Ben", "UCjorge", "MUSIC_PAGE_TYPE_ARTIST"),
                    run(" • "),
                    run("Samba Esquema Novo", "MPREb_samba", "MUSIC_PAGE_TYPE_ALBUM"),
                ]
            },
        }
    }
    (item,) = parse_watch_queue(payload)
    assert (item.artist, item.album_id) == ("Jorge Ben", "MPREb_samba")


def test_unlinked_bylines_leave_navigation_empty():
    assert _linked_pages({"subtitle": {"runs": [run("Artista sem link")]}}) == {}


def test_byline_drops_the_duration_column_and_artist_falls_back_to_text():
    track = LibraryItem("v", "T", "Gal Costa · Aquarela do Brasil · 3:45", kind="songs")
    assert track_byline(track) == "Gal Costa · Aquarela do Brasil"
    assert track_artist(track) == "Gal Costa"
    assert track_artist(LibraryItem("v", "T", "4:01", kind="songs")) == ""
    linked = LibraryItem("v", "T", "x", kind="songs", artist="Elis Regina", artist_id="UC1")
    assert track_artist(linked) == "Elis Regina"


def test_radio_starts_with_its_seed_without_repeating_it():
    seed = LibraryItem("a", "A", kind="songs")
    items = [LibraryItem("a", "A", kind="songs"), LibraryItem("b", "B", kind="songs")]
    assert [item.id for item in radio_queue(seed, items)] == ["a", "b"]


def gtk_or_skip():
    gi = pytest.importorskip("gi")
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, Gtk

    if Gdk.Display.get_default() is None:
        pytest.skip("sem display")
    return Gtk


class Downloads:
    def __init__(self, offline=()):
        self.offline = set(offline)

    def offline_path(self, item_id):
        return "/tmp/x" if item_id in self.offline else None


def menu_labels(collection, track, offline=()):
    Gtk = gtk_or_skip()
    from harmonia.window_detail import WindowDetailMixin
    from harmonia.window_item_menu import WindowItemMenuMixin
    from harmonia.window_playback import WindowPlaybackMixin

    class Window(WindowDetailMixin, WindowItemMenuMixin, WindowPlaybackMixin):
        downloads = Downloads(offline)
        sections = {"songs": []}

    box = Window()._track_menu(collection, track, Gtk.Popover())
    labels, stack = [], [box]
    while stack:
        widget = stack.pop(0)
        if isinstance(widget, Gtk.Label):
            labels.append(widget.get_label())
        child = widget.get_first_child()
        while child:
            stack.append(child)
            child = child.get_next_sibling()
    return labels


def test_track_menu_offers_navigation_radio_playlist_and_download():
    playlist = LibraryItem("PL1", "Minha playlist", kind="playlists")
    track = LibraryItem(
        "vid1", "Águas de Março", "Elis Regina", kind="songs", set_video_id="s1",
        artist="Elis Regina", artist_id="UCelis", album="Elis & Tom", album_id="MPREb_elis",
    )  # fmt: skip
    assert menu_labels(playlist, track) == [
        "Iniciar rádio", "Tocar a seguir", "Adicionar à fila", "Curtir música",
        "Salvar na playlist", "Baixar", "Remover desta playlist", "Compartilhar",
        "Ir para o artista", "Ir para o álbum",
    ]  # fmt: skip


def test_track_menu_adapts_to_album_pages_cached_tracks_and_downloads():
    album = LibraryItem("MPREb_elis", "Elis & Tom", kind="albums")
    cached = LibraryItem("vid1", "Águas de Março", "Elis Regina · 3:17", kind="songs")
    labels = menu_labels(album, cached, offline={"vid1"})
    assert "Ir para o álbum" not in labels  # already on it
    assert "Buscar o artista" in labels  # no artist id in cached rows
    assert "Disponível offline" in labels and "Baixar" not in labels


def test_search_focus_is_detected_inside_the_entry():
    Gtk = gtk_or_skip()
    from harmonia.window_search import search_entry_focused

    window = Gtk.Window()
    entry = Gtk.SearchEntry()
    window.set_child(entry)
    window.present()
    entry.grab_focus()
    context = __import__("gi.repository.GLib", fromlist=["GLib"]).MainContext.default()
    for _ in range(50):
        context.iteration(False)
    assert not entry.has_focus()  # focus lives in the internal GtkText
    assert search_entry_focused(entry)
    window.destroy()


def test_suggestions_never_take_keyboard_focus():
    from harmonia import app, window_search

    header = inspect.getsource(app.HarmoniaWindow._build_header)
    assert "Gtk.Popover(autohide=False" in header
    assert "set_can_focus(False)" in header
    assert '"stop-search"' in header and "EventControllerFocus" in header
    shown = inspect.getsource(window_search.WindowSearchMixin._show_search_suggestions)
    assert "set_focusable(False)" in shown
    assert "has_focus()" not in shown


def test_suggestions_do_not_reopen_for_the_query_just_searched():
    from harmonia.window_search import WindowSearchMixin

    class Popover:
        hidden = 0

        def popdown(self):
            self.hidden += 1

    class Entry:
        def get_text(self):
            return "rock ao vivo"

    class Window(WindowSearchMixin):
        _suggestion_timeout = 0
        _suggestion_request = 0
        _searched_query = "rock ao vivo"
        search_suggestions = Popover()

    window = Window()
    window._search_text_changed(Entry())
    assert window.search_suggestions.hidden == 1
    assert window._suggestion_timeout == 0


class QueueWindow:
    """Just enough of the window for the queue operations."""

    def __init__(self, queue, index):
        from harmonia.models import LibraryItem as Item

        self.queue = [Item(f"q{n}", f"Fila {n}", kind="songs") for n in range(queue)]
        self.queue_index = index
        self.current_item = self.queue[index] if self.queue else None
        self.started, self.toasts = [], []
        self.toast_overlay = type(
            "Toasts", (), {"add_toast": lambda _s, t: self.toasts.append(t)}
        )()

    def set_queue(self, items, index):
        self.started.append([item.id for item in items])

    def _render_queue(self):
        pass

    def _save_playback_state(self):
        pass


def test_play_next_goes_after_the_current_track_and_add_to_queue_at_the_end():
    gtk_or_skip()
    from harmonia.window_playback import WindowPlaybackMixin

    window = QueueWindow(4, 1)
    new = [LibraryItem("a", "A", kind="songs"), LibraryItem("b", "B", kind="songs")]
    WindowPlaybackMixin.enqueue(window, new, next_up=True)
    assert [item.id for item in window.queue] == ["q0", "q1", "a", "b", "q2", "q3"]
    WindowPlaybackMixin.enqueue(window, [LibraryItem("c", "C", kind="songs")], next_up=False)
    assert [item.id for item in window.queue][-1] == "c"
    assert window.started == [] and len(window.toasts) == 2


def test_queueing_with_nothing_playing_starts_playback_and_skips_non_tracks():
    gtk_or_skip()
    from harmonia.window_playback import WindowPlaybackMixin

    window = QueueWindow(0, -1)
    album = LibraryItem("MPRE1", "Álbum", kind="albums")
    WindowPlaybackMixin.enqueue(window, [album, LibraryItem("a", "A", kind="songs")], next_up=False)
    assert window.started == [["a"]]


def test_collection_menu_follows_youtube_music_and_share_links_point_to_it():
    from harmonia.window_item_menu import share_url

    album = LibraryItem("MPREb_x", "Álbum", kind="albums", playlist_id="OLAK5uy_x")
    playlist = LibraryItem("VLPLabc", "Playlist", kind="playlists")
    labels = menu_labels(album, album)
    assert labels == [
        "Aleatório", "Tocar a seguir", "Adicionar à fila", "Salvar na biblioteca", "Baixar",
        "Compartilhar",
    ]  # fmt: skip
    assert share_url(album) == "https://music.youtube.com/playlist?list=OLAK5uy_x"
    assert share_url(playlist) == "https://music.youtube.com/playlist?list=PLabc"
    assert share_url(LibraryItem("v1", "T", kind="songs")) == "https://music.youtube.com/watch?v=v1"
    assert share_url(LibraryItem("local:1", "T", kind="songs")) is None
