"""Clickable track rows of the home shelves and the album and playlist pages."""

from __future__ import annotations

from dataclasses import replace

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from .i18n import _  # noqa: E402
from .models import LibraryItem  # noqa: E402
from .ui import CreditsLabel, set_css_class, style_icon_button, track_byline  # noqa: E402

TRACK_COVER_SIZE = 40


class TrackRow:
    """A track row that plays or pauses on click, shows hover and can be liked.

    Subclasses build ``widget`` and implement ``update``, which the window
    calls whenever the current track or the playback state changes.
    """

    def __init__(
        self,
        window,
        widget: Gtk.Widget,
        track: LibraryItem,
        source: list[LibraryItem],
        options: Gtk.MenuButton,
    ) -> None:
        self.window = window
        self.widget = widget
        self.track = track
        self.source = source
        self.options = options
        self.liked = any(song.id == track.id for song in window.sections.get("songs", []))
        self.hovered = False

    def _connect(self) -> None:
        self.options.connect("notify::active", lambda *_: self.update())
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: self.set_hovered(True))
        motion.connect("leave", lambda *_: self.set_hovered(False))
        self.widget.add_controller(motion)

    def set_hovered(self, hovered: bool) -> None:
        self.hovered = hovered
        self.update()

    def activate(self) -> None:
        self.window.play_or_toggle(self.track, self.source)

    def toggle_like(self) -> None:
        self.liked = not self.liked
        self.update()
        self.window._toggle_song(self.track, self.liked)

    def playback(self) -> tuple[bool, bool]:
        """(this is the current track, and it is playing)."""
        active = self.window.is_current_track(self.track)
        return active, active and self.window._playback_is_playing()

    def update(self) -> None:
        raise NotImplementedError


def _title_line(track: LibraryItem, title: Gtk.Label) -> Gtk.Widget:
    """The title, followed by the explicit-content badge when the track has it."""
    if not track.explicit:
        return title
    line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    line.append(title)
    badge = Gtk.Label(label="E", valign=Gtk.Align.CENTER, tooltip_text=_("Conteúdo explícito"))
    badge.add_css_class("explicit-badge")
    line.append(badge)
    return line


def _options_button(css_class: str) -> tuple[Gtk.MenuButton, Gtk.Popover]:
    options = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text=_("Opções da faixa"))
    style_icon_button(options, "sm")
    options.add_css_class(css_class)
    popover = Gtk.Popover(has_arrow=False)
    popover.add_css_class("item-menu")
    options.set_popover(popover)
    return options, popover


class HomeSongRow(TrackRow):
    """A song of a home shelf: artwork with a play hint, title, credits, star, menu."""

    def __init__(self, window, track: LibraryItem, source: list[LibraryItem]) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=11)
        row.add_css_class("home-song-row")
        row.add_css_class("media-row")
        row.set_size_request(-1, 64)
        row.set_vexpand(False)
        row.set_cursor_from_name("pointer")
        row.append(self._cover(window, track))

        copy = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True, valign=Gtk.Align.CENTER
        )
        self.title = Gtk.Label(label=track.title, xalign=0, ellipsize=3)
        self.title.add_css_class("home-song-title")
        subtitle = CreditsLabel(window.navigate_credit, xalign=0, ellipsize=3)
        subtitle.show_item(track, track.subtitle or "YouTube Music")
        subtitle.add_css_class("home-song-subtitle")
        copy.append(_title_line(track, self.title))
        copy.append(subtitle)
        row.append(copy)

        self.liked_icon = Gtk.Image.new_from_icon_name("starred-symbolic")
        self.liked_icon.add_css_class("home-song-liked")
        row.append(self.liked_icon)

        options, popover = _options_button("home-song-options")
        row.append(options)
        super().__init__(window, row, track, source, options)
        self.liked_icon.set_opacity(1.0 if self.liked else 0.0)

        popover.connect(
            "show",
            lambda *_: popover.set_child(
                window.item_menu(
                    track,
                    popover,
                    liked=self.liked,
                    on_like=lambda: self._like_from_menu(popover),
                )
            ),
        )
        self._connect()
        click = Gtk.GestureClick(button=1)
        click.connect("released", lambda *_: self.activate())
        row.add_controller(click)
        self.update()

    def _cover(self, window, track: LibraryItem) -> Gtk.Widget:
        cover = Gtk.AspectFrame(ratio=1.0, obey_child=False)
        cover.set_size_request(48, 48)
        cover.set_halign(Gtk.Align.START)
        cover.set_valign(Gtk.Align.CENTER)
        # The artwork overlay expands; without this the cover inherits that and
        # takes a share of the row's spare width that differs per title, so the
        # titles of consecutive rows started at different x positions.
        cover.set_hexpand(False)
        cover.set_overflow(Gtk.Overflow.HIDDEN)
        cover.add_css_class("home-song-cover")
        artwork = Gtk.Overlay(hexpand=True, vexpand=True)
        placeholder = Gtk.Image.new_from_icon_name("audio-x-generic-symbolic")
        placeholder.set_pixel_size(20)
        placeholder.add_css_class("cover-placeholder")
        artwork.set_child(placeholder)
        if track.thumbnail:
            picture = Gtk.Picture(
                content_fit=Gtk.ContentFit.COVER,
                can_shrink=True,
                hexpand=True,
                vexpand=True,
            )
            window._load_artwork(track.thumbnail, picture, size=128)
            artwork.add_overlay(picture)
        self.play_hint = Gtk.Box(halign=Gtk.Align.FILL, valign=Gtk.Align.FILL)
        self.play_hint.add_css_class("home-song-play-hint")
        self.play_hint.set_opacity(0)
        self.play_hint.set_can_target(False)
        self.play_icon = Gtk.Image.new_from_icon_name("media-playback-start-symbolic")
        self.play_icon.set_pixel_size(22)
        self.play_icon.set_hexpand(True)
        self.play_icon.set_vexpand(True)
        self.play_icon.set_halign(Gtk.Align.CENTER)
        self.play_icon.set_valign(Gtk.Align.CENTER)
        self.play_hint.append(self.play_icon)
        artwork.add_overlay(self.play_hint)
        cover.set_child(artwork)
        return cover

    def _like_from_menu(self, popover: Gtk.Popover) -> None:
        popover.popdown()
        self.toggle_like()

    def update(self) -> None:
        active, playing = self.playback()
        set_css_class(self.widget, "home-song-current", active)
        set_css_class(self.title, "current-track", active)
        self.play_icon.set_from_icon_name(
            "media-playback-pause-symbolic" if playing else "media-playback-start-symbolic"
        )
        self.play_hint.set_opacity(1.0 if self.hovered or active else 0.0)
        self.liked_icon.set_opacity(1.0 if self.liked else 0.0)
        show_options = self.hovered or self.options.get_active()
        self.options.set_opacity(1.0 if show_options else 0.0)
        self.options.set_can_target(show_options)


class DetailTrackRow(TrackRow):
    """A track of an album or playlist page: number or play button, cover, credits,
    star, duration and menu."""

    def __init__(
        self,
        window,
        collection: LibraryItem,
        source: list[LibraryItem],
        track: LibraryItem,
        index: int,
    ) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add_css_class("detail-track-row")
        row.add_css_class("media-row")
        row.add_css_class("media-row-detailed")
        row.set_cursor_from_name("pointer")
        row.append(self._leading(track, index))

        artwork = track if track.thumbnail else replace(track, thumbnail=collection.thumbnail)
        cover = window._square_cover(artwork, size=TRACK_COVER_SIZE, fixed=True)
        cover.add_css_class("detail-track-cover")
        cover.set_valign(Gtk.Align.CENTER)
        row.append(cover)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        self.title = Gtk.Label(label=track.title, xalign=0, ellipsize=3)
        self.title.add_css_class("detail-track-title")
        text.append(_title_line(track, self.title))
        byline = track_byline(track)
        if byline:
            subtitle = CreditsLabel(window.navigate_credit, xalign=0, ellipsize=3)
            subtitle.show_item(track, byline)
            subtitle.add_css_class("detail-track-subtitle")
            text.append(subtitle)
        row.append(text)

        self.like = Gtk.Button()
        style_icon_button(self.like, "sm")
        self.like.add_css_class("detail-track-action")
        row.append(self.like)

        self.duration = Gtk.Label(label=window._duration_text(track), width_chars=6, xalign=1)
        self.duration.add_css_class("detail-track-duration")
        row.append(self.duration)

        options, popover = _options_button("detail-track-action")
        # Built when opened, so the offline state is always current.
        options.set_create_popup_func(
            lambda _button: popover.set_child(window._track_menu(collection, track, popover))
        )
        row.append(options)
        super().__init__(window, row, track, source, options)
        self.like.set_tooltip_text(
            _("Remover das músicas curtidas") if self.liked else _("Curtir música")
        )

        self.play.connect("clicked", lambda *_: self.activate())
        self.like.connect("clicked", lambda *_: self.toggle_like())
        self._connect()
        secondary = Gtk.GestureClick(button=3)
        secondary.connect("pressed", lambda *_: options.popup())
        row.add_controller(secondary)
        click = Gtk.GestureClick(button=1)
        click.connect("released", lambda *_: self.activate())
        row.add_controller(click)
        self.update()

    def _leading(self, track: LibraryItem, index: int) -> Gtk.Stack:
        """The track number, the playing icon or, on hover, a play button."""
        self.leading = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.leading.set_size_request(36, 36)
        number = Gtk.Label(label=str(index), width_chars=3, xalign=1)
        number.add_css_class("detail-track-number")
        self.leading.add_named(number, "number")
        active_icon = Gtk.Image.new_from_icon_name("audio-volume-high-symbolic")
        active_icon.add_css_class("detail-track-accent")
        self.leading.add_named(active_icon, "active")
        self.play = Gtk.Button(
            icon_name="media-playback-start-symbolic",
            tooltip_text=_("Reproduzir {title}").format(title=track.title),
        )
        style_icon_button(self.play, "sm")
        self.play.add_css_class("detail-track-play")
        self.leading.add_named(self.play, "play")
        return self.leading

    def update(self) -> None:
        active, playing = self.playback()
        set_css_class(self.widget, "detail-track-current", active)
        set_css_class(self.title, "detail-track-accent", active)
        set_css_class(self.duration, "detail-track-accent", active)
        self.leading.set_visible_child_name(
            "play" if self.hovered else ("active" if active else "number")
        )
        self.play.set_icon_name(
            "media-playback-pause-symbolic" if playing else "media-playback-start-symbolic"
        )
        self.like.set_icon_name("starred-symbolic" if self.liked else "non-starred-symbolic")
        set_css_class(self.like, "detail-track-accent", self.liked)
        show_like = self.hovered or self.liked
        emphasized = self.hovered or self.options.get_active()
        self.like.set_opacity(1.0 if show_like else 0.0)
        self.like.set_can_target(show_like)
        # Always reachable so the menu is discoverable without hovering.
        self.options.set_opacity(1.0 if emphasized else 0.55)
