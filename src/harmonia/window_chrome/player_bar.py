"""The player bar at the bottom of the window."""

from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk

from ..i18n import _
from ..ui import CreditsLabel, icon_button, set_icon_selected, style_icon_button


def build_player_bar(window) -> None:
    window.player_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
    window.player_bar.add_css_class("player-bar")
    window.player_bar.set_size_request(-1, 72)
    window.player_bar.set_vexpand(False)
    window.player_bar.set_valign(Gtk.Align.END)
    window.player_bar.set_visible(True)
    window.player_bar.append(_track_section(window))
    window.player_bar.append(_transport_section(window))
    window.player_bar.append(_secondary_section(window))
    window.footer_item_controls = [
        window.footer_like_button,
        window.lyrics_button,
        window.queue_button,
        window.footer_close_button,
        *window.footer_transport_controls,
    ]
    window.root.append(window.player_bar)
    compact_footer = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 920px"))
    compact_footer.add_setter(window.footer_secondary, "visible", False)
    window.add_breakpoint(compact_footer)
    window._set_footer_item_state(False)


def footer_cover_hover(window, hovered: bool) -> None:
    """Dim the footer artwork under an expand hint, while a track is loaded."""
    if getattr(window, "current_item", None) is None:
        hovered = False
    window.now_cover.set_opacity(0.52 if hovered else 1.0)
    window.cover_expand_hint.set_opacity(1.0 if hovered else 0.0)


def _track_section(window) -> Gtk.Widget:
    """The current track: artwork that opens the expanded player, title, like."""
    track = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, hexpand=True)
    track.add_css_class("player-track")
    track.set_vexpand(False)
    track.set_valign(Gtk.Align.CENTER)
    track.append(_cover_button(window))

    copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
    copy.set_cursor_from_name("pointer")
    copy.set_tooltip_text(_("Abrir player expandido"))
    copy_click = Gtk.GestureClick(button=1)
    copy_click.connect("released", lambda *_: window._show_expanded_player())
    copy.add_controller(copy_click)
    window.footer_track_copy = copy
    window.now_title = Gtk.Label(xalign=0, ellipsize=3, max_width_chars=28)
    window.now_title.add_css_class("card-title")
    window.now_subtitle = CreditsLabel(
        window.navigate_credit, xalign=0, ellipsize=3, max_width_chars=28
    )
    window.now_subtitle.add_css_class("card-subtitle")
    copy.append(window.now_title)
    copy.append(window.now_subtitle)
    track.append(copy)

    window.footer_like_button = icon_button("non-starred-symbolic", _("Curtir"))
    window.footer_like_button.connect("clicked", lambda *_: window._toggle_current_song_like())
    window.like_buttons.append(window.footer_like_button)
    track.append(window.footer_like_button)
    return track


def _cover_button(window) -> Gtk.Button:
    cover_button = Gtk.Button(tooltip_text=_("Expandir player"))
    cover_button.add_css_class("flat")
    cover_button.add_css_class("player-cover-button")
    cover_button.set_size_request(56, 56)
    cover_button.set_hexpand(False)
    cover_button.set_halign(Gtk.Align.START)
    cover_button.set_valign(Gtk.Align.CENTER)
    cover_button.set_vexpand(False)
    cover_button.set_overflow(Gtk.Overflow.HIDDEN)
    cover_button.connect("clicked", lambda *_: window._show_expanded_player())
    window.footer_cover_button = cover_button
    cover_frame = Gtk.AspectFrame(ratio=1.0, obey_child=False)
    cover_frame.set_size_request(56, 56)
    cover_frame.set_hexpand(False)
    cover_frame.set_vexpand(False)
    cover_frame.set_halign(Gtk.Align.CENTER)
    cover_frame.set_valign(Gtk.Align.CENTER)
    cover_frame.set_overflow(Gtk.Overflow.HIDDEN)
    cover_frame.add_css_class("player-cover")
    cover_overlay = Gtk.Overlay(hexpand=True, vexpand=True)
    window.now_cover_placeholder = Gtk.Image.new_from_icon_name("audio-x-generic-symbolic")
    window.now_cover_placeholder.set_pixel_size(24)
    window.now_cover_placeholder.add_css_class("player-cover-placeholder")
    cover_overlay.set_child(window.now_cover_placeholder)
    window.now_cover = Gtk.Picture(content_fit=Gtk.ContentFit.COVER)
    window.now_cover.set_can_shrink(True)
    window.now_cover.set_halign(Gtk.Align.FILL)
    window.now_cover.set_valign(Gtk.Align.FILL)
    window.now_cover.set_hexpand(True)
    window.now_cover.set_vexpand(True)
    cover_overlay.add_overlay(window.now_cover)
    window.cover_expand_hint = Gtk.Box(halign=Gtk.Align.FILL, valign=Gtk.Align.FILL)
    window.cover_expand_hint.add_css_class("player-cover-expand")
    expand_icon = Gtk.Image.new_from_icon_name("view-fullscreen-symbolic")
    expand_icon.set_pixel_size(22)
    expand_icon.set_hexpand(True)
    expand_icon.set_vexpand(True)
    expand_icon.set_halign(Gtk.Align.CENTER)
    expand_icon.set_valign(Gtk.Align.CENTER)
    window.cover_expand_hint.append(expand_icon)
    window.cover_expand_hint.set_opacity(0)
    window.cover_expand_hint.set_can_target(False)
    cover_overlay.add_overlay(window.cover_expand_hint)
    cover_frame.set_child(cover_overlay)
    cover_button.set_child(cover_frame)
    hover = Gtk.EventControllerMotion()
    hover.connect("enter", lambda *_: footer_cover_hover(window, True))
    hover.connect("leave", lambda *_: footer_cover_hover(window, False))
    cover_button.add_controller(hover)
    return cover_button


def _transport_section(window) -> Gtk.Widget:
    """Shuffle, previous, play, next, repeat, autoplay, and the timeline."""
    center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
    center.add_css_class("player-center")
    center.set_vexpand(False)
    center.set_valign(Gtk.Align.CENTER)
    controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, halign=Gtk.Align.CENTER)
    shuffle = icon_button("media-playlist-shuffle-symbolic", _("Ordem aleatória"))
    shuffle.connect("clicked", lambda button: window._toggle_shuffle(button))
    window.shuffle_buttons.append(shuffle)
    previous = icon_button("media-skip-backward-symbolic", _("Anterior"))
    previous.connect("clicked", lambda *_: window._play_previous())
    window.play_button = icon_button("media-playback-pause-symbolic", _("Pausar ou continuar"))
    window.play_button.add_css_class("app-media-play")
    window.play_button.connect("clicked", lambda *_: window._toggle_player())
    next_button = icon_button("media-skip-forward-symbolic", _("Próxima"))
    next_button.connect("clicked", lambda *_: window._play_next())
    repeat = icon_button("media-playlist-repeat-symbolic", _("Repetir"))
    repeat.connect("clicked", lambda button: window._toggle_repeat(button))
    window.repeat_buttons.append(repeat)
    window.autoplay_button = icon_button(
        "media-playlist-consecutive-symbolic", _("Reprodução automática ativada")
    )
    set_icon_selected(window.autoplay_button, True)
    window.autoplay_button.connect("clicked", lambda button: window._toggle_autoplay(button))
    window.footer_transport_controls = [
        shuffle,
        previous,
        window.play_button,
        next_button,
        repeat,
        window.autoplay_button,
    ]
    for control in window.footer_transport_controls:
        controls.append(control)
    center.append(controls)

    timeline = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    window.elapsed_label = Gtk.Label(label=_("0:00"), width_chars=5)
    window.elapsed_label.add_css_class("time-label")
    timeline.append(window.elapsed_label)
    window.progress = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 0.1)
    window.progress.add_css_class("player-scale")
    window.progress.set_draw_value(False)
    window.progress.set_hexpand(True)
    window.progress.set_sensitive(False)
    window.progress.connect("change-value", window._seek_requested)
    timeline.append(window.progress)
    window.duration_label = Gtk.Label(label=_("0:00"), width_chars=5)
    window.duration_label.add_css_class("time-label")
    timeline.append(window.duration_label)
    center.append(timeline)
    return center


def _secondary_section(window) -> Gtk.Widget:
    """Lyrics and queue popovers, volume and stop."""
    secondary = Gtk.Box(
        orientation=Gtk.Orientation.HORIZONTAL, spacing=8, hexpand=True, halign=Gtk.Align.END
    )
    secondary.add_css_class("player-secondary")
    secondary.set_vexpand(False)
    secondary.set_valign(Gtk.Align.CENTER)
    window.lyrics_button = Gtk.MenuButton(
        icon_name="audio-input-microphone-symbolic", tooltip_text=_("Letras")
    )
    style_icon_button(window.lyrics_button, "sm")
    window.lyrics_popover = Gtk.Popover(autohide=True)
    window.lyrics_button.set_popover(window.lyrics_popover)
    window.lyrics_button.connect("notify::active", window._lyrics_toggled)
    window._set_lyrics_message(
        "audio-input-microphone-symbolic",
        _("Letras"),
        _("Comece a reproduzir uma música para ver a letra."),
    )
    secondary.append(window.lyrics_button)
    window.queue_button = Gtk.MenuButton(
        icon_name="view-list-symbolic", tooltip_text=_("Fila de reprodução")
    )
    style_icon_button(window.queue_button, "sm")
    window.queue_popover = Gtk.Popover()
    window.queue_button.set_popover(window.queue_popover)
    secondary.append(window.queue_button)
    secondary.append(Gtk.Image.new_from_icon_name("audio-volume-high-symbolic"))
    volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
    volume.add_css_class("player-scale")
    volume.set_size_request(100, -1)
    volume.set_draw_value(False)
    volume.set_value(80)
    volume.connect(
        "value-changed", lambda slider: setattr(window.player, "volume", slider.get_value() / 100)
    )
    secondary.append(volume)
    window.footer_close_button = icon_button("window-close-symbolic", _("Parar"))
    window.footer_close_button.connect("clicked", lambda *_: window._stop_player())
    secondary.append(window.footer_close_button)
    window.footer_secondary = secondary
    return secondary
