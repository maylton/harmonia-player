"""The "E" badge for explicit content, wherever a track is listed or playing."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from harmonia.models import LibraryItem

QML = Path(__file__).resolve().parents[1] / "src" / "harmonia" / "qml"
EXPLICIT = LibraryItem("e1", "Faixa", "Artista • 2:11", kind="songs", explicit=True)
CLEAN = LibraryItem("c1", "Faixa", "Artista • 2:11", kind="songs")


def gtk_or_skip():
    gi = pytest.importorskip("gi")
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk

    if Gdk.Display.get_default() is None:
        pytest.skip("sem display")
    Adw.init()
    return Adw, Gtk


def labels(widget) -> list[str]:
    _adw, Gtk = gtk_or_skip()
    found, pending = [], [widget]
    while pending:
        current = pending.pop()
        if isinstance(current, Gtk.Label) and current.has_css_class("explicit-badge"):
            found.append(current.get_label())
        child = current.get_first_child()
        while child:
            pending.append(child)
            child = child.get_next_sibling()
    return found


def test_titles_get_the_badge_only_when_explicit():
    _adw, Gtk = gtk_or_skip()
    from harmonia.ui import title_with_badge

    plain = Gtk.Label(label="Faixa")
    assert title_with_badge(plain, CLEAN) is plain
    assert labels(title_with_badge(Gtk.Label(label="Faixa"), EXPLICIT)) == ["E"]


def test_queue_and_related_rows_show_the_badge():
    gtk_or_skip()
    from harmonia import queue_view

    actions = queue_view.QueueActions(
        select=lambda *_: None, move=lambda *_: None, remove=lambda *_: None,
        promote=lambda *_: None,
    )  # fmt: skip
    assert labels(queue_view.queue_row(EXPLICIT, current=True)) == ["E"]
    assert labels(queue_view.queue_row(CLEAN, current=False)) == []
    assert labels(queue_view.related_row(EXPLICIT, actions, play_next=True)) == ["E"]


def test_kde_backend_tells_qml_whether_the_current_track_is_explicit():
    pytest.importorskip("PySide6")
    from harmonia.qt_backend import HarmoniaQtBackend as QtBackend

    class Playback:
        current_item = EXPLICIT

    backend = QtBackend.__new__(QtBackend)
    backend.playback = Playback()
    assert QtBackend.currentExplicit.fget(backend) is True
    Playback.current_item = None
    assert QtBackend.currentExplicit.fget(backend) is False


@pytest.mark.parametrize(
    "name",
    [
        "SongShelf.qml", "DetailPage.qml", "SearchPage.qml", "QueuePanel.qml",
        "HistoryPage.qml", "LibraryPage.qml", "DownloadsPage.qml", "ExpandedPlayer.qml",
        "InsightsPage.qml", "MediaShelf.qml",
    ],
)  # fmt: skip
def test_kde_track_lists_put_the_badge_after_each_title(name):
    source = (QML / name).read_text(encoding="utf-8")
    titles = len(re.findall(r"text: modelData\.title\s*$", source, re.MULTILINE))
    badges = source.count("visible: modelData.explicit === true")
    assert titles and badges >= titles - (1 if name == "SearchPage.qml" else 0)


def test_kde_player_shows_the_badge_for_the_current_track():
    for name in ("PlayerBar.qml", "ExpandedPlayer.qml"):
        assert "visible: backend.currentExplicit" in (QML / name).read_text(encoding="utf-8")
