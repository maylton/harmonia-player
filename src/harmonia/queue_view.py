"""The play queue and the related tracks, as the player bar's popover and the
expanded player show them.

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
from .ui import mark_explicit  # noqa: E402

RELATED_IN_POPOVER = 12


@dataclass(frozen=True, slots=True)
class QueueActions:
    select: Callable[[int], None]
    move: Callable[[int, int], None]  # position, -1 up or 1 down
    remove: Callable[[int], None]
    promote: Callable[[LibraryItem, bool], None]  # related track, play next


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


def expanded_content(
    queue: list[LibraryItem], current: int, related: list[LibraryItem], actions: QueueActions
) -> Gtk.Widget:
    """The expanded player's "Relacionadas" page: the queue, then related tracks."""
    clamp = Adw.Clamp(maximum_size=760, tightening_threshold=620)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.append(_heading(_("Fila"), "expanded-related-title"))
    if not queue:
        box.append(
            Adw.StatusPage(
                icon_name="media-playlist-consecutive-symbolic",
                title=_("Nada na fila"),
                description=_("Escolha uma música para ver as próximas faixas."),
            )
        )
    else:
        rows = []
        for position, item in enumerate(queue):
            row = queue_row(item, position == current)
            row.add_css_class("media-row")
            row.connect("activated", lambda *_args, selected=position: actions.select(selected))
            rows.append(row)
        box.append(_listing(rows))
        box.append(_heading(_("Relacionadas"), "expanded-related-title"))
        if related:
            box.append(_listing(related_row(item, actions, play_next=False) for item in related))
    clamp.set_child(box)
    return clamp
