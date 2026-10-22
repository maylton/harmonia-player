"""The play queue and the related tracks, as the player bar's popover and the
expanded player's "A seguir" column show them.

Plain widget builders: they get the queue and what to do on each action, and
read nothing from the window.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .i18n import _  # noqa: E402
from .models import LibraryItem  # noqa: E402
from .ui import mark_explicit, media_row  # noqa: E402

RELATED_IN_POPOVER = 12
# YouTube Music's Up next shows 25 tracks at a time (numItemsToShow of its
# radio panel) out of a batch of 50, and the radio is fetched again when the
# queue runs out instead of being paged without end.
UP_NEXT_LIMIT = 25


@dataclass(frozen=True, slots=True)
class QueueActions:
    select: Callable[[int], None]
    move: Callable[[int, int], None]  # position, -1 up or 1 down
    remove: Callable[[int], None]
    promote: Callable[[LibraryItem, bool], None]  # related track, play next
    play: Callable[[LibraryItem], None] | None = None  # a related track, now


def _later(callback, *args) -> Callable:
    # The queue is rebuilt by these actions: run them after the click handler,
    # not while the button that was clicked is being destroyed.
    return lambda *_ignored: GLib.idle_add(callback, *args)


def _icon_button(icon: str, tooltip: str) -> Gtk.Button:
    button = Gtk.Button(icon_name=icon, tooltip_text=tooltip)
    button.add_css_class("flat")
    return button


def queue_row(item: LibraryItem, current: bool) -> Adw.ActionRow:
    """A queue entry, marked when it is the track playing."""
    row = Adw.ActionRow(activatable=True)
    row.set_use_markup(False)
    row.set_title(item.title)
    row.set_subtitle(item.subtitle)
    if current:
        row.add_prefix(Gtk.Image.new_from_icon_name("audio-volume-high-symbolic"))
        row.add_css_class("current-track")
    mark_explicit(row, item)
    return row


def related_row(item: LibraryItem, actions: QueueActions, *, play_next: bool) -> Adw.ActionRow:
    row = Adw.ActionRow()
    row.set_use_markup(False)
    row.set_title(item.title)
    row.set_subtitle(item.subtitle)
    mark_explicit(row, item)
    if play_next:
        button = _icon_button("media-playlist-consecutive-symbolic", _("Tocar em seguida"))
        button.connect("clicked", _later(actions.promote, item, True))
        row.add_suffix(button)
    button = _icon_button("list-add-symbolic", _("Adicionar ao fim"))
    button.connect("clicked", _later(actions.promote, item, False))
    row.add_suffix(button)
    return row


def _listing(rows) -> Gtk.ListBox:
    listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    listing.add_css_class("boxed-list")
    for row in rows:
        listing.append(row)
    return listing


def _heading(text: str, css_class: str) -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=0)
    label.add_css_class(css_class)
    return label


def _editable_row(
    position: int, item: LibraryItem, count: int, current: int, actions
) -> Gtk.Widget:
    row = queue_row(item, position == current)
    controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
    up = _icon_button("go-up-symbolic", _("Mover para cima"))
    down = _icon_button("go-down-symbolic", _("Mover para baixo"))
    remove = _icon_button("user-trash-symbolic", _("Remover da fila"))
    up.set_sensitive(position > 0)
    down.set_sensitive(position + 1 < count)
    up.connect("clicked", _later(actions.move, position, -1))
    down.connect("clicked", _later(actions.move, position, 1))
    remove.connect("clicked", _later(actions.remove, position))
    for control in (up, down, remove):
        controls.append(control)
    row.add_suffix(controls)
    row.connect("activated", lambda *_args: actions.select(position))
    return row


def popover_content(
    queue: list[LibraryItem], current: int, related: list[LibraryItem], actions: QueueActions
) -> Gtk.Widget:
    """The player bar's queue: reorder and remove tracks, promote related ones."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.add_css_class("queue-popover")
    box.append(_heading(_("Fila de reprodução"), "section-title"))
    scroll = Gtk.ScrolledWindow(
        hscrollbar_policy=Gtk.PolicyType.NEVER,
        min_content_width=360,
        max_content_height=430,
        propagate_natural_height=True,
    )
    scroll.set_child(
        _listing(
            _editable_row(position, item, len(queue), current, actions)
            for position, item in enumerate(queue)
        )
    )
    box.append(scroll)
    box.append(_heading(_("Relacionadas"), "section-title"))
    if related:
        box.append(
            _listing(
                related_row(item, actions, play_next=True) for item in related[:RELATED_IN_POPOVER]
            )
        )
    else:
        note = Gtk.Label(
            label=_("As recomendações aparecem conforme a fila avança."), xalign=0, wrap=True
        )
        note.add_css_class("dim-label")
        box.append(note)
    return box


def _single_line(row: Adw.ActionRow) -> Adw.ActionRow:
    """A narrow column ellipsizes titles instead of wrapping them."""
    row.set_title_lines(1)
    row.set_subtitle_lines(1)
    return row


def up_next(
    queue: list[LibraryItem], current: int, related: list[LibraryItem], limit: int = UP_NEXT_LIMIT
) -> tuple[list[tuple[int, LibraryItem]], list[LibraryItem]]:
    """What "A seguir" lists: the current track and the rest of the queue, by
    position, then autoplay's tracks, at most ``limit`` in all."""
    start = max(0, current)
    upcoming = list(enumerate(queue))[start : start + limit]
    return upcoming, related[: max(0, limit - len(upcoming))]


def up_next_content(
    queue: list[LibraryItem],
    current: int,
    related: list[LibraryItem],
    actions: QueueActions,
    cover: Callable[[LibraryItem], Gtk.Widget],
) -> Gtk.Widget:
    """The expanded player's "A seguir" column, as YouTube Music's Up next."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.append(_heading(_("A seguir"), "expanded-up-next-title"))
    upcoming, autoplay = up_next(queue, current, related)
    if not upcoming:
        note = Gtk.Label(
            label=_("Escolha uma música para ver as próximas faixas."), xalign=0, wrap=True
        )
        note.add_css_class("dim-label")
        box.append(note)
        return box
    rows = []
    for position, item in upcoming:
        row = _single_line(media_row(item, cover=cover(item)))
        if position == current:
            row.add_css_class("up-next-current")
        row.connect("activated", lambda *_args, selected=position: actions.select(selected))
        rows.append(row)
    box.append(_listing(rows))
    if autoplay:
        box.append(_heading(_("Reprodução automática"), "expanded-up-next-subtitle"))
        rows = []
        for item in autoplay:
            row = _single_line(related_row(item, actions, play_next=True))
            row.add_prefix(cover(item))
            row.set_activatable(actions.play is not None)
            if actions.play is not None:
                row.connect("activated", _later(actions.play, item))
            rows.append(row)
        box.append(_listing(rows))
    return box
