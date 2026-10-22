import pytest

from harmonia.models import LibraryItem

gi = pytest.importorskip("gi")


def rows_of(listbox):
    child, rows = listbox.get_first_child(), []
    while child is not None:
        rows.append(child)
        child = child.get_next_sibling()
    return rows


def find(widget, kind):
    found, stack = [], [widget]
    while stack:
        current = stack.pop()
        if isinstance(current, kind):
            found.append(current)
        child = current.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return found


def test_the_queue_marks_the_current_track_and_offers_the_related_ones():
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    from harmonia import queue_view

    queue = [LibraryItem(f"q{n}", f"Fila {n}", kind="songs") for n in range(3)]
    related = [LibraryItem("r", "Relacionada", kind="songs")]
    selected = []
    actions = queue_view.QueueActions(
        select=selected.append,
        move=lambda *a: None,
        remove=lambda *a: None,
        promote=lambda *a: None,
    )
    popover = queue_view.popover_content(queue, 1, related, actions)
    queue_list, related_list = find(popover, Gtk.ListBox)[::-1]
    rows = rows_of(queue_list)
    assert len(rows) == 3 and len(rows_of(related_list)) == 1
    assert [row.has_css_class("current-track") for row in rows] == [False, True, False]
    rows[2].emit("activated")
    assert selected == [2]

    empty = queue_view.up_next_content([], -1, related, actions, lambda _item: Gtk.Box())
    assert not find(empty, Gtk.ListBox)  # just the note to pick a song


def test_up_next_lists_25_tracks_like_youtube_music():
    from harmonia import queue_view

    queue = [LibraryItem(f"q{n}", f"Fila {n}", kind="songs") for n in range(10)]
    related = [LibraryItem(f"r{n}", f"Rádio {n}", kind="songs") for n in range(50)]
    # From the track playing on, then autoplay fills the rest up to 25.
    upcoming, autoplay = queue_view.up_next(queue, 3, related)
    assert [position for position, _item in upcoming] == list(range(3, 10))
    assert len(upcoming) + len(autoplay) == queue_view.UP_NEXT_LIMIT == 25
    assert autoplay[0].id == "r0"
    # A long queue alone takes all 25 places.
    long_queue = [LibraryItem(f"l{n}", f"Longa {n}", kind="songs") for n in range(80)]
    upcoming, autoplay = queue_view.up_next(long_queue, 0, related)
    assert len(upcoming) == 25 and autoplay == []


def test_up_next_plays_an_autoplay_track_at_once():
    gi.require_version("Gtk", "4.0")
    from gi.repository import GLib, Gtk

    from harmonia import queue_view

    queue = [LibraryItem("q0", "Fila", kind="songs")]
    related = [LibraryItem("r0", "Rádio", kind="songs")]
    played, selected = [], []
    actions = queue_view.QueueActions(
        select=selected.append,
        move=lambda *a: None,
        remove=lambda *a: None,
        promote=lambda *a: None,
        play=played.append,
    )
    column = queue_view.up_next_content(queue, 0, related, actions, lambda _item: Gtk.Box())
    queue_list, autoplay_list = find(column, Gtk.ListBox)[::-1]
    (current,) = rows_of(queue_list)
    assert current.has_css_class("up-next-current")
    rows_of(autoplay_list)[0].emit("activated")
    while GLib.MainContext.default().iteration(False):
        pass
    assert played == related
