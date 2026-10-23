"""The expanded player: the Música and Letras tabs, and "A seguir"."""

from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk

from ..gtk_expressive import ButtonRow, CookieCover, MarqueeLabel
from ..i18n import _
from ..ui import CreditsLabel, explicit_badge, icon_button
from .player_bar import expressive_progress


def build_expanded_player(window) -> None:
    window.expanded_revealer = Gtk.Revealer(
        transition_type=Gtk.RevealerTransitionType.SLIDE_UP,
        transition_duration=500,
        hexpand=True,
        vexpand=True,
        halign=Gtk.Align.FILL,
        valign=Gtk.Align.FILL,
    )
    window.expanded_revealer.set_can_target(False)
    window.expanded_revealer.connect(
        "notify::child-revealed",
        lambda revealer, _pspec: revealer.set_can_target(revealer.get_child_revealed()),
    )

    surface = Gtk.Overlay(hexpand=True, vexpand=True)
    surface.add_css_class("expanded-player")
    surface.set_child(Gtk.Box(hexpand=True, vexpand=True))
    window.expanded_surface = surface

    shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
    shell.add_css_class("expanded-shell")
    window.expanded_stack = Adw.ViewStack()
    window.expanded_stack.set_enable_transitions(True)
    window.expanded_stack.set_transition_duration(250)
    window.expanded_stack.set_vexpand(True)
    shell.append(_header(window))
    for page, name, title, icon in (
        (_music_page(window), "music", _("Música"), "audio-headphones-symbolic"),
        (_lyrics_page(window), "lyrics", _("Letras"), "audio-input-microphone-symbolic"),
    ):
        window.expanded_stack.add_titled(page, name, title).set_icon_name(icon)
    window.expanded_stack.connect("notify::visible-child-name", window._expanded_page_changed)
    shell.append(window.expanded_stack)
    surface.add_overlay(shell)
    window.expanded_revealer.set_child(surface)
    window.app_overlay.add_overlay(window.expanded_revealer)
    window.app_overlay.set_measure_overlay(window.expanded_revealer, False)

    key = Gtk.EventControllerKey()
    key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
    key.connect("key-pressed", window._expanded_key_pressed)
    window.add_controller(key)

    # In full screen the header and the controls fade out while the pointer rests.
    motion = Gtk.EventControllerMotion()
    motion.connect("motion", lambda *_: window._wake_fullscreen_controls())
    surface.add_controller(motion)
    window.connect("notify::fullscreened", lambda *_: window._fullscreen_changed())


def _header(window) -> Gtk.Widget:
    top = Gtk.CenterBox()
    top.add_css_class("expanded-header")
    window.expanded_close_button = icon_button(
        "go-down-symbolic", _("Recolher player (Esc)"), size="md"
    )
    window.expanded_close_button.set_halign(Gtk.Align.START)
    window.expanded_close_button.connect("clicked", lambda *_: window._hide_expanded_player())
    top.set_start_widget(window.expanded_close_button)
    switcher = Adw.ViewSwitcher(stack=window.expanded_stack, policy=Adw.ViewSwitcherPolicy.WIDE)
    switcher.add_css_class("expanded-switcher")
    top.set_center_widget(switcher)
    window.expanded_fullscreen_button = icon_button(
        "view-fullscreen-symbolic", _("Tela cheia (F)"), size="md"
    )
    window.expanded_fullscreen_button.set_halign(Gtk.Align.END)
    window.expanded_fullscreen_button.connect("clicked", lambda *_: window._toggle_fullscreen())
    top.set_end_widget(window.expanded_fullscreen_button)
    return top


# The artwork sits above the track and its controls, which keep its width so
# the timeline does not stretch across the window.
EXPANDED_COVER_SIZE = 360
EXPANDED_INFO_WIDTH = 420
# "A seguir" beside the player, as YouTube Music's Up next; narrower windows
# leave it to the player bar's queue.
UP_NEXT_WIDTH = 380
UP_NEXT_MIN_WINDOW = "max-width: 1000px"


def _music_page(window) -> Gtk.Widget:
    page = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, hexpand=True, vexpand=True)
    page.append(_player_column(window))
    page.append(_up_next_column(window))
    narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(UP_NEXT_MIN_WINDOW))
    narrow.add_setter(window.expanded_up_next_scroll, "visible", False)
    window.add_breakpoint(narrow)
    return page


def _up_next_column(window) -> Gtk.Widget:
    scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
    scroll.set_size_request(UP_NEXT_WIDTH, -1)
    scroll.add_css_class("expanded-up-next")
    window.expanded_up_next = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    scroll.set_child(window.expanded_up_next)
    window.expanded_up_next_scroll = scroll
    # The breakpoint hides the column itself; full screen hides this slot.
    window.expanded_up_next_slot = Gtk.Box()
    window.expanded_up_next_slot.append(scroll)
    return window.expanded_up_next_slot


def _player_column(window) -> Gtk.Widget:
    scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, hexpand=True)
    # The artwork grows with the space the column has (window_expanded.py).
    window.expanded_player_scroll = scroll
    for adjustment in (scroll.get_hadjustment(), scroll.get_vadjustment()):
        adjustment.connect("notify::page-size", window._expanded_space_changed)
    column = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=32,
        halign=Gtk.Align.CENTER,
        valign=Gtk.Align.CENTER,
        vexpand=True,
    )
    column.add_css_class("expanded-music-content")
    column.append(_cover(window))

    info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22, halign=Gtk.Align.CENTER)
    info.set_size_request(EXPANDED_INFO_WIDTH, -1)
    info.add_css_class("expanded-info")
    info.append(_heading(window))
    info.append(_timeline(window))
    info.append(_transport(window))
    column.append(info)
    scroll.set_child(column)
    return scroll


def _cover(window) -> Gtk.Widget:
    cover = Gtk.AspectFrame(ratio=1.0, obey_child=False)
    cover.set_size_request(EXPANDED_COVER_SIZE, EXPANDED_COVER_SIZE)
    cover.set_halign(Gtk.Align.CENTER)
    cover.set_valign(Gtk.Align.CENTER)
    cover.set_overflow(Gtk.Overflow.HIDDEN)
    cover.add_css_class("expanded-cover")
    cover_overlay = Gtk.Overlay(hexpand=True, vexpand=True)
    placeholder = Gtk.Image.new_from_icon_name("audio-x-generic-symbolic")
    placeholder.set_pixel_size(104)
    placeholder.add_css_class("expanded-cover-placeholder")
    cover_overlay.set_child(placeholder)
    window.expanded_cover = Gtk.Picture(
        content_fit=Gtk.ContentFit.COVER,
        can_shrink=True,
        hexpand=True,
        vexpand=True,
    )
    cover_overlay.add_overlay(window.expanded_cover)
    window.expanded_cover_shape = CookieCover(cover_overlay)
    cover.set_child(window.expanded_cover_shape)
    return cover


def _heading(window) -> Gtk.Widget:
    heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
    title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
    # Neither widens the controls below: a long title goes round on its line
    # and a long subtitle ellipsizes.
    window.expanded_explicit = explicit_badge()
    window.expanded_explicit.set_visible(False)
    window.expanded_title = MarqueeLabel(suffix=window.expanded_explicit)
    window.expanded_title.set_hexpand(True)
    window.expanded_title.add_css_class("expanded-title")
    window.expanded_subtitle = CreditsLabel(
        window.navigate_credit, xalign=0, ellipsize=3, max_width_chars=1
    )
    window.expanded_subtitle.add_css_class("expanded-subtitle")
    title_box.append(window.expanded_title)
    title_box.append(window.expanded_subtitle)
    heading.append(title_box)
    window.expanded_like_button = icon_button("non-starred-symbolic", _("Curtir música"), size="md")
    window.expanded_like_button.add_css_class("expanded-like")
    window.expanded_like_button.connect("clicked", lambda *_: window._toggle_current_song_like())
    window.like_buttons.append(window.expanded_like_button)
    heading.append(window.expanded_like_button)
    return heading


def _timeline(window) -> Gtk.Widget:
    timeline = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    window.expanded_elapsed_label = Gtk.Label(label=_("0:00"), width_chars=5, xalign=1)
    window.expanded_elapsed_label.add_css_class("expanded-time")
    timeline.append(window.expanded_elapsed_label)
    window.expanded_progress = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 0.1)
    window.expanded_progress.add_css_class("player-scale")
    window.expanded_progress.set_draw_value(False)
    window.expanded_progress.set_hexpand(True)
    window.expanded_progress.set_sensitive(False)
    window.expanded_progress.connect("change-value", window._seek_requested)
    timeline.append(window.expanded_progress)
    window.expanded_wavy_progress = expressive_progress(
        window, window.expanded_progress, window.expanded_elapsed_label
    )
    timeline.append(window.expanded_wavy_progress)
    window.expanded_duration_label = Gtk.Label(label=_("0:00"), width_chars=5, xalign=0)
    window.expanded_duration_label.add_css_class("expanded-time")
    timeline.append(window.expanded_duration_label)
    return timeline


def _control(icon: str, tooltip: str, *css_classes: str) -> Gtk.Button:
    button = Gtk.Button(icon_name=icon, tooltip_text=tooltip)
    for name in css_classes:
        button.add_css_class(name)
    return button


def _transport(window) -> Gtk.Widget:
    controls = ButtonRow(spacing=21, width=EXPANDED_INFO_WIDTH)
    window.expanded_button_row = controls
    shuffle = _control(
        "media-playlist-shuffle-symbolic",
        _("Ordem aleatória"),
        "flat",
        "expanded-secondary-control",
    )
    shuffle.connect("clicked", lambda button: window._toggle_shuffle(button))
    window.shuffle_buttons.append(shuffle)
    previous = _control(
        "media-skip-backward-symbolic", _("Anterior"), "flat", "expanded-skip-control"
    )
    previous.connect("clicked", lambda *_: window._play_previous())
    window.expanded_play_button = _control(
        "media-playback-pause-symbolic",
        _("Pausar ou continuar"),
        "circular",
        "expanded-play-control",
    )
    window.expanded_play_button.connect("clicked", lambda *_: window._toggle_player())
    next_button = _control(
        "media-skip-forward-symbolic", _("Próxima"), "flat", "expanded-skip-control"
    )
    next_button.connect("clicked", lambda *_: window._play_next())
    repeat = _control(
        "media-playlist-repeat-symbolic", _("Repetir"), "flat", "expanded-secondary-control"
    )
    repeat.connect("clicked", lambda button: window._toggle_repeat(button))
    window.repeat_buttons.append(repeat)
    for control in (shuffle, previous, window.expanded_play_button, next_button, repeat):
        controls.append(
            control,
            fill=control is window.expanded_play_button,
            narrow=control in (shuffle, repeat),
        )
    return controls


def _lyrics_page(window) -> Gtk.Widget:
    scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
    scroll.set_kinetic_scrolling(True)
    window.expanded_lyrics_scroll = scroll
    window.expanded_lyrics_container = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        hexpand=True,
        vexpand=True,
    )
    window.expanded_lyrics_container.add_css_class("expanded-tab-page")
    scroll.set_child(window.expanded_lyrics_container)
    window._set_expanded_lyrics_message(
        "audio-input-microphone-symbolic",
        _("Letras"),
        _("Comece a reproduzir uma música para ver a letra."),
    )
    return scroll
