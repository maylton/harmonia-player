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

    empty = queue_view.expanded_content([], -1, related, actions)
    assert not find(empty, Gtk.ListBox)  # just the "Nada na fila" page
