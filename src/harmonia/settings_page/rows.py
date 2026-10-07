"""Preference rows the settings groups are built from."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk  # noqa: E402

ENTRY_WIDTH = 260


def combo_row(
    title: str,
    values: Sequence[tuple[str, Any]],
    current: Any,
    on_change: Callable[[Any], None],
) -> Adw.ComboRow:
    """A choice among (label, value) pairs, calling ``on_change(value)``."""
    row = Adw.ComboRow(title=title, model=Gtk.StringList.new([label for label, _v in values]))
    keys = [key for _label, key in values]
    row.set_selected(keys.index(current) if current in keys else 0)
    row.connect("notify::selected", lambda widget, _pspec: on_change(keys[widget.get_selected()]))
    return row


def switch_row(
    title: str, subtitle: str, active: bool, on_change: Callable[[bool], None]
) -> Adw.SwitchRow:
    row = Adw.SwitchRow(title=title, subtitle=subtitle)
    row.set_active(active)
    row.connect("notify::active", lambda widget, _pspec: on_change(widget.get_active()))
    return row


def entry_row(
    title: str,
    subtitle: str,
    text: str,
    placeholder: str,
    on_change: Callable[[str], None],
) -> Adw.ActionRow:
    """A row with a text entry, calling ``on_change`` with the stripped text."""
    row = Adw.ActionRow(title=title, subtitle=subtitle)
    entry = Gtk.Entry(text=text, placeholder_text=placeholder, valign=Gtk.Align.CENTER)
    entry.set_size_request(ENTRY_WIDTH, -1)
    entry.connect("changed", lambda widget: on_change(widget.get_text().strip()))
    row.add_suffix(entry)
    return row


def scale_row(
    title: str,
    bounds: tuple[float, float, float],
    value: float,
    on_change: Callable[[float], None],
    digits: int = 1,
) -> Adw.ActionRow:
    """A row with a slider over (lower, upper, step)."""
    row = Adw.ActionRow(title=title)
    scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, *bounds)
    scale.set_draw_value(True)
    scale.set_digits(digits)
    scale.set_value(value)
    scale.set_size_request(ENTRY_WIDTH, -1)
    scale.set_valign(Gtk.Align.CENTER)
    scale.connect("value-changed", lambda widget: on_change(widget.get_value()))
    row.add_suffix(scale)
    return row


def pill_button(label: str, on_click: Callable[[], None], *css_classes: str) -> Gtk.Button:
    button = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
    button.add_css_class("pill")
    for name in css_classes:
        button.add_css_class(name)
    button.connect("clicked", lambda *_: on_click())
    return button
