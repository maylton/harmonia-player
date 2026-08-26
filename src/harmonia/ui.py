"""Reusable GTK presentation primitives for Harmonia's visual system."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .i18n import _

ACTION_ROLES = {"primary", "accent", "secondary", "destructive"}
ICON_SIZES = {"sm", "md", "lg"}
PAGE_WIDTHS = {"content": 1280, "reading": 980}


def _install_view_stack_transition_compatibility() -> None:
    """Keep newer ViewStack transition calls harmless on libadwaita 1.5."""

    def set_enable_transitions(_stack, _enabled: bool) -> None:
        return None

    def set_transition_duration(_stack, _duration: int) -> None:
        return None

    if not hasattr(Adw.ViewStack, "set_enable_transitions"):
        setattr(Adw.ViewStack, "set_enable_transitions", set_enable_transitions)
    if not hasattr(Adw.ViewStack, "set_transition_duration"):
        setattr(Adw.ViewStack, "set_transition_duration", set_transition_duration)


_install_view_stack_transition_compatibility()


def set_action_role(widget: Gtk.Widget, role: str) -> Gtk.Widget:
    if role not in ACTION_ROLES:
        raise ValueError(f"Unknown action role: {role}")
    for candidate in ACTION_ROLES:
        widget.remove_css_class(f"app-action-{candidate}")
    widget.add_css_class(f"app-action-{role}")
    return widget


def style_action(widget: Gtk.Widget, role: str = "secondary") -> Gtk.Widget:
    widget.add_css_class("pill")
    widget.add_css_class("app-action")
    set_action_role(widget, role)
    widget.set_valign(Gtk.Align.CENTER)
    return widget


def action_button(
    label: str,
    icon_name: str | None = None,
    *,
    role: str = "secondary",
    tooltip: str | None = None,
) -> Gtk.Button:
    button = Gtk.Button(label=label, tooltip_text=tooltip)
    if icon_name:
        button.set_icon_name(icon_name)
    return style_action(button, role)  # type: ignore[return-value]


def style_icon_button(
    widget: Gtk.Widget,
    size: str = "sm",
    *,
    destructive: bool = False,
) -> Gtk.Widget:
    if size not in ICON_SIZES:
        raise ValueError(f"Unknown icon button size: {size}")
    widget.add_css_class("flat")
    widget.add_css_class("circular")
    widget.add_css_class("app-icon-button")
    widget.add_css_class(f"app-icon-button-{size}")
    if destructive:
        widget.add_css_class("app-icon-button-destructive")
    widget.set_valign(Gtk.Align.CENTER)
    return widget


def icon_button(
    icon_name: str,
    tooltip: str,
    *,
    size: str = "sm",
    destructive: bool = False,
) -> Gtk.Button:
    button = Gtk.Button(icon_name=icon_name, tooltip_text=tooltip)
    return style_icon_button(button, size, destructive=destructive)  # type: ignore[return-value]


def set_menu_action_content(button: Gtk.Button, label: str, icon_name: str) -> None:
    """Render icon and text together; GtkButton's native properties are exclusive."""
    content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    icon = Gtk.Image.new_from_icon_name(icon_name)
    icon.set_pixel_size(18)
    text = Gtk.Label(label=label, xalign=0, hexpand=True)
    content.append(icon)
    content.append(text)
    button.set_child(content)
    button.set_tooltip_text(label)


def menu_action_button(
    label: str,
    icon_name: str,
    *,
    destructive: bool = False,
) -> Gtk.Button:
    button = Gtk.Button()
    button.add_css_class("flat")
    button.add_css_class("app-menu-action")
    if destructive:
        button.add_css_class("destructive-action")
    set_menu_action_content(button, label, icon_name)
    return button


def media_play_button(
    tooltip: str | None = None,
    *,
    size: str = "lg",
) -> Gtk.Button:
    tooltip = tooltip or _("Reproduzir")
    button = icon_button("media-playback-start-symbolic", tooltip, size=size)
    button.add_css_class("app-media-play")
    return button


def set_icon_selected(widget: Gtk.Widget, selected: bool) -> None:
    if selected:
        widget.add_css_class("app-icon-selected")
    else:
        widget.remove_css_class("app-icon-selected")


@dataclass(slots=True)
class PageShell:
    scroll: Gtk.ScrolledWindow
    content: Gtk.Box
    clamp: Adw.Clamp


def page_shell(
    kind: str = "content",
    *,
    spacing: int = 24,
    css_classes: Iterable[str] = (),
) -> PageShell:
    if kind not in PAGE_WIDTHS:
        raise ValueError(f"Unknown page shell: {kind}")
    scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    content.add_css_class("app-page")
    content.add_css_class(f"app-page-{kind}")
    for css_class in css_classes:
        content.add_css_class(css_class)
    clamp = Adw.Clamp(
        maximum_size=PAGE_WIDTHS[kind],
        tightening_threshold=1040 if kind == "content" else 760,
    )
    clamp.set_child(content)
    scroll.set_child(clamp)
    return PageShell(scroll, content, clamp)


def page_header(
    title: str,
    subtitle: str = "",
    *,
    actions: Iterable[Gtk.Widget] = (),
) -> Gtk.Widget:
    header = Adw.WrapBox(
        orientation=Gtk.Orientation.HORIZONTAL,
        child_spacing=16,
        line_spacing=12,
        natural_line_length=900,
        wrap_policy=Adw.WrapPolicy.NATURAL,
    )
    header.set_child_spacing_unit(Adw.LengthUnit.PX)
    header.set_line_spacing_unit(Adw.LengthUnit.PX)
    header.set_natural_line_length_unit(Adw.LengthUnit.PX)
    header.add_css_class("app-page-header")
    copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
    heading = Gtk.Label(label=title, xalign=0, wrap=True)
    heading.add_css_class("hero-title")
    copy.append(heading)
    if subtitle:
        description = Gtk.Label(label=subtitle, xalign=0, wrap=True)
        description.add_css_class("hero-subtitle")
        copy.append(description)
    header.append(copy)
    action_box = Adw.WrapBox(
        orientation=Gtk.Orientation.HORIZONTAL,
        child_spacing=8,
        line_spacing=8,
        natural_line_length=620,
        wrap_policy=Adw.WrapPolicy.NATURAL,
        halign=Gtk.Align.END,
        valign=Gtk.Align.CENTER,
    )
    action_box.set_child_spacing_unit(Adw.LengthUnit.PX)
    action_box.set_line_spacing_unit(Adw.LengthUnit.PX)
    action_box.set_natural_line_length_unit(Adw.LengthUnit.PX)
    action_box.add_css_class("app-page-header-actions")
    for action in actions:
        action_box.append(action)
    if action_box.get_first_child():
        header.append(action_box)
    return header


def section_link(label: str, callback: Callable[[], None]) -> Gtk.Button:
    button = Gtk.Button(label=label, icon_name="go-next-symbolic")
    button.add_css_class("flat")
    button.add_css_class("section-link")
    button.set_valign(Gtk.Align.CENTER)
    button.connect("clicked", lambda *_: callback())
    return button
