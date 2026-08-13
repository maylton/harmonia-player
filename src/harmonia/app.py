from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .downloads import DownloadManager
from .i18n import _, ngettext
from .lyrics import GoogleTranslationClient, LyricsResolver
from .models import (
    ArtistPage,
    ArtistSection,
    DownloadRecord,
    ExploreData,
    ExploreDestination,
    HistoryEntry,
    LibraryItem,
    LocalPlaylist,
    LyricLine,
    LyricsDocument,
    PlaybackState,
    SearchGroup,
    SearchResults,
)
from .mpris import MprisService
from .player import NativePlayer
from .preferences import Preferences
from .services import YouTubeMusicService
from .storage import Storage
from .ui import (
    action_button,
    icon_button,
    media_play_button,
    menu_action_button,
    page_header,
    page_shell,
    section_link,
    set_action_role,
    set_icon_selected,
    set_menu_action_content,
    style_action,
    style_icon_button,
)

LOGGER = logging.getLogger(__name__)
APP_ID = "io.github.harmonia.Harmonia"

LABELS = {
    "playlists": _("Playlists"),
    "songs": _("Músicas"),
    "albums": _("Álbuns"),
    "artists": _("Artistas"),
}
ICONS = {
    "playlists": "view-list-symbolic",
    "songs": "audio-x-generic-symbolic",
    "albums": "media-optical-symbolic",
    "artists": "avatar-default-symbolic",
}
EXPLORE_ICON = "find-location-symbolic"
LIKED_ICON = "starred-symbolic"


class HarmoniaWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(
            application=app, title=_("Harmonia"), default_width=1080, default_height=760
        )
        self.storage = Storage()
        self.preferences = Preferences.load(self.storage)
        self.youtube = YouTubeMusicService(self.storage)
        self.lyrics_resolver = LyricsResolver(self.youtube.lyrics)
        self.translation_client = GoogleTranslationClient()
        self.lyrics_provider = self.storage.get_setting("lyrics_provider", "auto")
        if self.lyrics_provider not in {"auto", "lrclib", "youtube"}:
            self.lyrics_provider = "auto"
        try:
            self.lyrics_offset_ms = int(self.storage.get_setting("lyrics_offset_ms", "0"))
        except ValueError:
            self.lyrics_offset_ms = 0
        self.current_lyrics_document: LyricsDocument | None = None
        self._lyrics_item_id: str | None = None
        self._lyric_views: list[dict] = []
        self._active_lyric_index = -1
        self.downloads = DownloadManager(
            self.storage,
            self.youtube,
            lambda record: GLib.idle_add(self._download_updated, record),
        )
        self.sections = self.storage.load_library()
        self.home_sections = self.storage.load_home()
        self.explore_data = self.storage.load_explore()
        self.main_view = "home"
        self.queue: list[LibraryItem] = []
        self.related_items: list[LibraryItem] = []
        self.queue_index = -1
        self.current_duration_ms = 0
        self._updating_progress = False
        self.shuffle_enabled = False
        self.repeat_enabled = False
        self.autoplay_enabled = True
        self._autoplay_loading = False
        self._autoplay_request = 0
        self._waiting_for_autoplay = False
        self._last_queue_save = 0.0
        self._restored_position_ms = 0
        self._history_recorded_request = -1
        self._history_entries: list[HistoryEntry] = []
        self._history_tracking_request = -1
        self._account_avatar_request = 0
        self._artwork_requests: dict[int, str] = {}
        self._icon_sources: dict[Gtk.Image, str] = {}
        self._icon_update_guard = False
        icon_settings = Gtk.Settings.get_for_display(Gdk.Display.get_default())
        self._system_icon_theme_name = (
            icon_settings.get_property("gtk-icon-theme-name") if icon_settings else "Adwaita"
        )
        self._sleep_timer_source = 0
        self._sleep_timer_deadline = 0.0
        self._artist_current_item: LibraryItem | None = None
        self.library_filter = "albums"
        self.library_origin = "youtube"
        self.library_sort = "recent"
        self._stream_ready = False
        self._stream_recovery_attempts = 0
        self._play_request = 0
        self._lyrics_request = 0
        self._search_request = 0
        self._suggestion_request = 0
        self._suggestion_timeout = 0
        self.search_results: SearchResults | None = None
        self.detail_track_rows: list[dict] = []
        self.home_song_rows: list[dict] = []
        self.shuffle_buttons: list[Gtk.Button] = []
        self.repeat_buttons: list[Gtk.Button] = []
        self.like_buttons: list[Gtk.Button] = []
        self.current_liked = False
        self.set_size_request(720, 520)
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)
        self.app_overlay = Gtk.Overlay()
        self.toast_overlay.set_child(self.app_overlay)
        self.ambient_background = Gtk.Picture(
            content_fit=Gtk.ContentFit.COVER,
            can_shrink=True,
            hexpand=True,
            vexpand=True,
        )
        self.ambient_background.add_css_class("ambient-background")
        self.ambient_background.set_opacity(0)
        self.app_overlay.set_child(self.ambient_background)
        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.root.add_css_class("app-root")
        self.app_overlay.add_overlay(self.root)
        self.app_overlay.set_measure_overlay(self.root, True)
        self._build_header()
        self._load_account_avatar(
            self.storage.get_setting("account_avatar_url", "") if self.storage.load_cookie() else ""
        )
        self.main_shell = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.main_shell.set_vexpand(True)
        self._build_sidebar()
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        self.stack.connect(
            "notify::visible-child",
            lambda *_: GLib.idle_add(self._refresh_custom_icons),
        )
        self.main_shell.append(self.stack)
        self.root.append(self.main_shell)
        compact = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 800px"))
        compact.add_setter(self.sidebar, "visible", False)
        compact.add_setter(self.sidebar_separator, "visible", False)
        compact.add_setter(self.compact_menu, "visible", True)
        self.add_breakpoint(compact)
        self.player = NativePlayer(self._player_state, self._player_error, self._play_next)
        self._apply_audio_preferences()
        self.mpris = MprisService(
            app,
            self.player,
            {
                "next": self._play_next,
                "previous": self._play_previous,
                "toggle": self._toggle_player,
                "pause": self._pause,
                "play": self._resume,
                "repeat": self._set_repeat,
                "shuffle": self._set_shuffle,
                "stop": self._stop_player,
            },
            {
                "repeat": lambda: self.repeat_enabled,
                "shuffle": lambda: self.shuffle_enabled,
            },
        )
        self._build_player_bar()
        compact_player = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 900px"))
        compact_player.add_setter(self.sidebar, "visible", False)
        compact_player.add_setter(self.sidebar_separator, "visible", False)
        compact_player.add_setter(self.compact_menu, "visible", True)
        compact_player.add_setter(self.footer_secondary, "visible", False)
        compact_player.add_setter(self.player_bar, "spacing", 8)
        self.add_breakpoint(compact_player)
        self._build_expanded_player()
        self._apply_appearance_preferences()
        GLib.timeout_add(500, self._update_progress)
        self._render()
        self._restore_playback_state()
        if self.storage.load_cookie():
            self._refresh_account_avatar()
            GLib.idle_add(self._initial_sync)
            threading.Thread(
                target=self._validate_download_account, daemon=True, name="download-account"
            ).start()
            self.downloads.resume_pending()
            GLib.timeout_add_seconds(24 * 60 * 60, self._periodic_download_validation)

    def _build_header(self) -> None:
        self.header = Adw.HeaderBar()
        self.search_entry = Gtk.SearchEntry(
            placeholder_text=_("Pesquisar músicas, álbuns, artistas…")
        )
        self.search_entry.set_size_request(380, -1)
        self.search_entry.connect("activate", lambda *_: self.search(self.search_entry.get_text()))
        self.search_entry.connect("search-changed", self._search_text_changed)
        self.search_suggestions = Gtk.Popover(autohide=True, has_arrow=False)
        self.search_suggestions.set_parent(self.search_entry)
        self.search_suggestions.add_css_class("search-suggestions")
        self.header.set_title_widget(self.search_entry)
        self.back = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text=_("Voltar"))
        style_icon_button(self.back, "md")
        self.back.connect("clicked", lambda *_: self._go_back())
        self.back.set_visible(False)
        self.header.pack_start(self.back)
        self.compact_menu = Gtk.MenuButton(
            icon_name="open-menu-symbolic", tooltip_text=_("Navegação")
        )
        style_icon_button(self.compact_menu, "md")
        self.compact_menu.set_visible(False)
        menu = Gtk.Popover()
        menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        menu_box.add_css_class("compact-menu")
        for label, icon, callback in (
            (_("Início"), "go-home-symbolic", self.show_home),
            (_("Explorar"), EXPLORE_ICON, self.show_explore),
            (_("Biblioteca"), "folder-music-symbolic", self.show_library),
            (_("Músicas curtidas"), LIKED_ICON, lambda: self.show_category("songs")),
            (_("Playlists"), "view-list-symbolic", lambda: self.show_category("playlists")),
            (_("Artistas"), "avatar-default-symbolic", lambda: self.show_category("artists")),
            (_("Histórico"), "document-open-recent-symbolic", self.show_history),
            (_("Downloads"), "folder-download-symbolic", self.show_downloads),
            (_("Preferências"), "preferences-system-symbolic", self.show_settings),
        ):
            button = menu_action_button(label, icon)
            button.connect("clicked", lambda _button, action=callback: (menu.popdown(), action()))
            menu_box.append(button)
        menu.set_child(menu_box)
        self.compact_menu.set_popover(menu)
        self.header.pack_start(self.compact_menu)
        refresh = Gtk.Button(
            icon_name="view-refresh-symbolic", tooltip_text=_("Sincronizar biblioteca")
        )
        style_icon_button(refresh, "md")
        refresh.connect("clicked", lambda *_: (self.sync(), self.sync_home(), self.sync_explore()))
        self.header.pack_start(refresh)
        account = Gtk.Button(tooltip_text=_("Conta"))
        style_icon_button(account, "md")
        set_icon_selected(account, True)
        account.add_css_class("account-avatar-button")
        account.set_overflow(Gtk.Overflow.HIDDEN)
        avatar_stack = Gtk.Overlay()
        avatar_stack.set_size_request(30, 30)
        avatar_stack.set_overflow(Gtk.Overflow.HIDDEN)
        avatar_stack.add_css_class("account-avatar-frame")
        self.account_avatar_fallback = Gtk.Image.new_from_icon_name("avatar-default-symbolic")
        self.account_avatar_fallback.set_pixel_size(18)
        avatar_stack.set_child(self.account_avatar_fallback)
        self.account_avatar_picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER)
        self.account_avatar_picture.set_can_shrink(True)
        self.account_avatar_picture.set_hexpand(True)
        self.account_avatar_picture.set_vexpand(True)
        self.account_avatar_picture.set_opacity(0)
        self.account_avatar_picture.add_css_class("account-avatar-picture")
        avatar_stack.add_overlay(self.account_avatar_picture)
        account.set_child(avatar_stack)
        self.account_button = account
        account.connect("clicked", lambda *_: self.login_dialog())
        self.header.pack_end(account)
        self.root.append(self.header)

    def _show_account_avatar_file(self, path: Path, request_id: int) -> bool:
        if request_id != self._account_avatar_request or not path.exists():
            return GLib.SOURCE_REMOVE
        self.account_avatar_picture.set_filename(str(path))
        self.account_avatar_picture.set_opacity(1)
        self.account_avatar_fallback.set_opacity(0)
        return GLib.SOURCE_REMOVE

    def _load_account_avatar(self, url: str) -> None:
        self._account_avatar_request += 1
        request_id = self._account_avatar_request
        if not url:
            self.account_avatar_picture.set_opacity(0)
            self.account_avatar_picture.set_filename(None)
            self.account_avatar_fallback.set_opacity(1)
            self.account_button.set_tooltip_text(_("Conta"))
            return
        target = self.storage.artwork_path(url)
        if target.exists():
            self._show_account_avatar_file(target, request_id)
            return

        def worker() -> None:
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(request, timeout=15) as response:
                    data = response.read(2 * 1024 * 1024)
                target.write_bytes(data)
                GLib.idle_add(self._show_account_avatar_file, target, request_id)
            except Exception:
                LOGGER.debug("Não foi possível baixar o avatar da conta", exc_info=True)

        threading.Thread(target=worker, daemon=True, name="account-avatar-image").start()

    def _refresh_account_avatar(self) -> None:
        if not self.storage.load_cookie():
            self._clear_account_avatar()
            return

        def worker() -> None:
            try:
                profile = self.youtube.account_profile()
                GLib.idle_add(self._account_profile_loaded, profile)
            except Exception:
                LOGGER.debug(
                    "Não foi possível atualizar o perfil; mantendo o avatar em cache",
                    exc_info=True,
                )

        threading.Thread(target=worker, daemon=True, name="account-profile").start()

    def _account_profile_loaded(self, profile) -> bool:
        avatar = profile.thumbnail or ""
        self.storage.set_setting("account_avatar_url", avatar)
        self.account_button.set_tooltip_text(_("Conta — {name}").format(name=profile.name))
        self._load_account_avatar(avatar)
        return GLib.SOURCE_REMOVE

    def _clear_account_avatar(self) -> None:
        self.storage.set_setting("account_avatar_url", "")
        self._load_account_avatar("")

    def _build_sidebar(self) -> None:
        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.sidebar.add_css_class("sidebar")
        self.sidebar.set_size_request(230, -1)
        self.sidebar.set_hexpand(False)
        self.sidebar.set_halign(Gtk.Align.START)
        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        brand.add_css_class("sidebar-brand")
        logo = Gtk.Image.new_from_icon_name("audio-headphones-symbolic")
        logo.set_pixel_size(24)
        brand.append(logo)
        name = Gtk.Label(label=_("Harmonia"), xalign=0)
        name.add_css_class("sidebar-brand-title")
        brand.append(name)
        self.sidebar.append(brand)
        self.nav_buttons: dict[str, Gtk.Button] = {}
        self.sidebar.append(
            self._sidebar_button("home", _("Início"), "go-home-symbolic", self.show_home)
        )
        self.sidebar.append(
            self._sidebar_button("explore", _("Explorar"), EXPLORE_ICON, self.show_explore)
        )
        self.sidebar.append(
            self._sidebar_button(
                "library", _("Biblioteca"), "folder-music-symbolic", self.show_library
            )
        )
        heading = Gtk.Label(label=_("SUAS MÚSICAS"), xalign=0)
        heading.add_css_class("sidebar-heading")
        self.sidebar.append(heading)
        self.sidebar.append(
            self._sidebar_button(
                "songs", _("Músicas curtidas"), LIKED_ICON, lambda: self.show_category("songs")
            )
        )
        self.sidebar.append(
            self._sidebar_button(
                "playlists",
                _("Playlists"),
                "view-list-symbolic",
                lambda: self.show_category("playlists"),
            )
        )
        self.sidebar.append(
            self._sidebar_button(
                "artists",
                _("Artistas"),
                "avatar-default-symbolic",
                lambda: self.show_category("artists"),
            )
        )
        self.sidebar.append(
            self._sidebar_button(
                "history", _("Histórico"), "document-open-recent-symbolic", self.show_history
            )
        )
        self.sidebar.append(
            self._sidebar_button(
                "downloads", _("Downloads"), "folder-download-symbolic", self.show_downloads
            )
        )
        self.sidebar.append(
            self._sidebar_button(
                "settings", _("Preferências"), "preferences-system-symbolic", self.show_settings
            )
        )
        spacer = Gtk.Box(vexpand=True)
        self.sidebar.append(spacer)
        create = Gtk.Button(label=_("Nova playlist"), icon_name="list-add-symbolic")
        create.add_css_class("sidebar-create")
        create.connect("clicked", lambda *_: self.create_playlist_dialog())
        self.sidebar.append(create)
        self.main_shell.append(self.sidebar)
        self.sidebar_separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        self.sidebar_separator.set_hexpand(False)
        self.main_shell.append(self.sidebar_separator)

    def _sidebar_button(self, key: str, label: str, icon: str, callback) -> Gtk.Button:
        button = Gtk.Button()
        button.add_css_class("sidebar-item")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.append(Gtk.Image.new_from_icon_name(icon))
        text = Gtk.Label(label=label, xalign=0, hexpand=True)
        row.append(text)
        button.set_child(row)
        button.connect("clicked", lambda *_: callback())
        self.nav_buttons[key] = button
        return button

    def _set_active_nav(self, key: str) -> None:
        for name, button in self.nav_buttons.items():
            if name == key:
                button.add_css_class("sidebar-active")
            else:
                button.remove_css_class("sidebar-active")

    def _build_player_bar(self) -> None:
        self.player_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        self.player_bar.add_css_class("player-bar")
        self.player_bar.set_size_request(-1, 72)
        self.player_bar.set_vexpand(False)
        self.player_bar.set_valign(Gtk.Align.END)
        self.player_bar.set_visible(True)
        track = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, hexpand=True)
        track.add_css_class("player-track")
        track.set_vexpand(False)
        track.set_valign(Gtk.Align.CENTER)
        cover_button = Gtk.Button(tooltip_text=_("Expandir player"))
        cover_button.add_css_class("flat")
        cover_button.add_css_class("player-cover-button")
        cover_button.set_size_request(56, 56)
        cover_button.set_hexpand(False)
        cover_button.set_halign(Gtk.Align.START)
        cover_button.set_valign(Gtk.Align.CENTER)
        cover_button.set_vexpand(False)
        cover_button.set_overflow(Gtk.Overflow.HIDDEN)
        cover_button.connect("clicked", lambda *_: self._show_expanded_player())
        self.footer_cover_button = cover_button
        cover_frame = Gtk.AspectFrame(ratio=1.0, obey_child=False)
        cover_frame.set_size_request(56, 56)
        cover_frame.set_hexpand(False)
        cover_frame.set_vexpand(False)
        cover_frame.set_halign(Gtk.Align.CENTER)
        cover_frame.set_valign(Gtk.Align.CENTER)
        cover_frame.set_overflow(Gtk.Overflow.HIDDEN)
        cover_frame.add_css_class("player-cover")
        cover_overlay = Gtk.Overlay(hexpand=True, vexpand=True)
        self.now_cover_placeholder = Gtk.Image.new_from_icon_name("audio-x-generic-symbolic")
        self.now_cover_placeholder.set_pixel_size(24)
        self.now_cover_placeholder.add_css_class("player-cover-placeholder")
        cover_overlay.set_child(self.now_cover_placeholder)
        self.now_cover = Gtk.Picture(content_fit=Gtk.ContentFit.COVER)
        self.now_cover.set_can_shrink(True)
        self.now_cover.set_halign(Gtk.Align.FILL)
        self.now_cover.set_valign(Gtk.Align.FILL)
        self.now_cover.set_hexpand(True)
        self.now_cover.set_vexpand(True)
        cover_overlay.add_overlay(self.now_cover)
        self.cover_expand_hint = Gtk.Box(halign=Gtk.Align.FILL, valign=Gtk.Align.FILL)
        self.cover_expand_hint.add_css_class("player-cover-expand")
        expand_icon = Gtk.Image.new_from_icon_name("view-fullscreen-symbolic")
        expand_icon.set_pixel_size(22)
        expand_icon.set_hexpand(True)
        expand_icon.set_vexpand(True)
        expand_icon.set_halign(Gtk.Align.CENTER)
        expand_icon.set_valign(Gtk.Align.CENTER)
        self.cover_expand_hint.append(expand_icon)
        self.cover_expand_hint.set_opacity(0)
        self.cover_expand_hint.set_can_target(False)
        cover_overlay.add_overlay(self.cover_expand_hint)
        cover_frame.set_child(cover_overlay)
        cover_button.set_child(cover_frame)
        hover = Gtk.EventControllerMotion()
        hover.connect("enter", lambda *_: self._footer_cover_hover(True))
        hover.connect("leave", lambda *_: self._footer_cover_hover(False))
        cover_button.add_controller(hover)
        track.append(cover_button)
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        copy.set_cursor_from_name("pointer")
        copy.set_tooltip_text(_("Abrir player expandido"))
        copy_click = Gtk.GestureClick(button=1)
        copy_click.connect("released", lambda *_: self._show_expanded_player())
        copy.add_controller(copy_click)
        self.footer_track_copy = copy
        self.now_title = Gtk.Label(xalign=0, ellipsize=3, max_width_chars=28)
        self.now_title.add_css_class("card-title")
        self.now_subtitle = Gtk.Label(xalign=0, ellipsize=3, max_width_chars=28)
        self.now_subtitle.add_css_class("card-subtitle")
        copy.append(self.now_title)
        copy.append(self.now_subtitle)
        track.append(copy)
        self.footer_like_button = Gtk.Button(
            icon_name="non-starred-symbolic", tooltip_text=_("Curtir")
        )
        style_icon_button(self.footer_like_button, "sm")
        self.footer_like_button.set_valign(Gtk.Align.CENTER)
        self.footer_like_button.connect("clicked", lambda *_: self._toggle_current_song_like())
        self.like_buttons.append(self.footer_like_button)
        track.append(self.footer_like_button)
        self.player_bar.append(track)

        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        center.add_css_class("player-center")
        center.set_vexpand(False)
        center.set_valign(Gtk.Align.CENTER)
        controls = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=10, halign=Gtk.Align.CENTER
        )
        shuffle = Gtk.Button(
            icon_name="media-playlist-shuffle-symbolic", tooltip_text=_("Ordem aleatória")
        )
        style_icon_button(shuffle, "sm")
        shuffle.connect("clicked", lambda button: self._toggle_shuffle(button))
        self.shuffle_buttons.append(shuffle)
        controls.append(shuffle)
        previous = Gtk.Button(icon_name="media-skip-backward-symbolic", tooltip_text=_("Anterior"))
        style_icon_button(previous, "sm")
        previous.connect("clicked", lambda *_: self._play_previous())
        controls.append(previous)
        self.play_button = Gtk.Button(
            icon_name="media-playback-pause-symbolic", tooltip_text=_("Pausar ou continuar")
        )
        style_icon_button(self.play_button, "sm")
        self.play_button.add_css_class("app-media-play")
        self.play_button.connect("clicked", lambda *_: self._toggle_player())
        controls.append(self.play_button)
        next_button = Gtk.Button(icon_name="media-skip-forward-symbolic", tooltip_text=_("Próxima"))
        style_icon_button(next_button, "sm")
        next_button.connect("clicked", lambda *_: self._play_next())
        controls.append(next_button)
        repeat = Gtk.Button(icon_name="media-playlist-repeat-symbolic", tooltip_text=_("Repetir"))
        style_icon_button(repeat, "sm")
        repeat.connect("clicked", lambda button: self._toggle_repeat(button))
        self.repeat_buttons.append(repeat)
        controls.append(repeat)
        self.autoplay_button = Gtk.Button(
            icon_name="media-playlist-consecutive-symbolic",
            tooltip_text=_("Reprodução automática ativada"),
        )
        style_icon_button(self.autoplay_button, "sm")
        set_icon_selected(self.autoplay_button, True)
        self.autoplay_button.connect("clicked", lambda button: self._toggle_autoplay(button))
        controls.append(self.autoplay_button)
        self.footer_transport_controls = [
            shuffle,
            previous,
            self.play_button,
            next_button,
            repeat,
            self.autoplay_button,
        ]
        center.append(controls)
        timeline = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.elapsed_label = Gtk.Label(label=_("0:00"), width_chars=5)
        self.elapsed_label.add_css_class("time-label")
        timeline.append(self.elapsed_label)
        self.progress = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 0.1)
        self.progress.set_draw_value(False)
        self.progress.set_hexpand(True)
        self.progress.set_sensitive(False)
        self.progress.connect("change-value", self._seek_requested)
        timeline.append(self.progress)
        self.duration_label = Gtk.Label(label=_("0:00"), width_chars=5)
        self.duration_label.add_css_class("time-label")
        timeline.append(self.duration_label)
        center.append(timeline)
        self.player_bar.append(center)

        secondary = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8, hexpand=True, halign=Gtk.Align.END
        )
        secondary.add_css_class("player-secondary")
        secondary.set_vexpand(False)
        secondary.set_valign(Gtk.Align.CENTER)
        self.lyrics_button = Gtk.MenuButton(
            icon_name="audio-input-microphone-symbolic", tooltip_text=_("Letras")
        )
        style_icon_button(self.lyrics_button, "sm")
        self.lyrics_popover = Gtk.Popover(autohide=True)
        self.lyrics_button.set_popover(self.lyrics_popover)
        self.lyrics_button.connect("notify::active", self._lyrics_toggled)
        self._set_lyrics_message(
            "audio-input-microphone-symbolic",
            _("Letras"),
            _("Comece a reproduzir uma música para ver a letra."),
        )
        secondary.append(self.lyrics_button)
        self.queue_button = Gtk.MenuButton(
            icon_name="view-list-symbolic", tooltip_text=_("Fila de reprodução")
        )
        style_icon_button(self.queue_button, "sm")
        self.queue_popover = Gtk.Popover()
        self.queue_button.set_popover(self.queue_popover)
        secondary.append(self.queue_button)
        secondary.append(Gtk.Image.new_from_icon_name("audio-volume-high-symbolic"))
        volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        volume.set_size_request(100, -1)
        volume.set_draw_value(False)
        volume.set_value(80)
        volume.connect(
            "value-changed", lambda slider: setattr(self.player, "volume", slider.get_value() / 100)
        )
        secondary.append(volume)
        close = Gtk.Button(icon_name="window-close-symbolic", tooltip_text=_("Parar"))
        style_icon_button(close, "sm")
        close.connect("clicked", lambda *_: self._stop_player())
        secondary.append(close)
        self.footer_secondary = secondary
        self.footer_item_controls = [
            self.footer_like_button,
            self.lyrics_button,
            self.queue_button,
            close,
            *self.footer_transport_controls,
        ]
        self.player_bar.append(secondary)
        self.root.append(self.player_bar)
        compact_footer = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 920px"))
        compact_footer.add_setter(self.footer_secondary, "visible", False)
        self.add_breakpoint(compact_footer)
        self._set_footer_item_state(False)

    def _build_expanded_player(self) -> None:
        self.expanded_revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.FADE_SLIDE_UP,
            transition_duration=500,
            hexpand=True,
            vexpand=True,
            halign=Gtk.Align.FILL,
            valign=Gtk.Align.FILL,
        )
        self.expanded_revealer.set_can_target(False)
        self.expanded_revealer.connect(
            "notify::child-revealed",
            lambda revealer, _pspec: revealer.set_can_target(revealer.get_child_revealed()),
        )

        surface = Gtk.Overlay(hexpand=True, vexpand=True)
        surface.add_css_class("expanded-player")
        background = Gtk.Box(hexpand=True, vexpand=True)
        surface.set_child(background)
        self.expanded_backdrop_base = Gtk.Picture(
            content_fit=Gtk.ContentFit.COVER,
            can_shrink=True,
            hexpand=True,
            vexpand=True,
            halign=Gtk.Align.FILL,
            valign=Gtk.Align.FILL,
        )
        # A very faint base prevents transparent-looking blur edges without
        # making the original artwork composition readable in the backdrop.
        self.expanded_backdrop_base.set_opacity(0.05)
        self.expanded_backdrop_base.set_can_target(False)
        self.expanded_backdrop_base.add_css_class("expanded-backdrop-base")
        surface.add_overlay(self.expanded_backdrop_base)
        self.expanded_backdrop = Gtk.Picture(
            content_fit=Gtk.ContentFit.COVER,
            can_shrink=True,
            hexpand=True,
            vexpand=True,
            halign=Gtk.Align.FILL,
            valign=Gtk.Align.FILL,
        )
        self.expanded_backdrop.set_opacity(0.68)
        self.expanded_backdrop.set_can_target(False)
        self.expanded_backdrop.add_css_class("expanded-backdrop")
        surface.add_overlay(self.expanded_backdrop)
        shade = Gtk.Box(hexpand=True, vexpand=True)
        shade.set_can_target(False)
        shade.add_css_class("expanded-backdrop-shade")
        surface.add_overlay(shade)

        shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        shell.add_css_class("expanded-shell")
        top = Gtk.CenterBox()
        top.add_css_class("expanded-header")
        self.expanded_close_button = Gtk.Button(
            icon_name="go-down-symbolic",
            tooltip_text=_("Recolher player (Esc)"),
            halign=Gtk.Align.START,
        )
        style_icon_button(self.expanded_close_button, "md")
        self.expanded_close_button.connect("clicked", lambda *_: self._hide_expanded_player())
        top.set_start_widget(self.expanded_close_button)

        self.expanded_stack = Adw.ViewStack()
        self.expanded_stack.set_enable_transitions(True)
        self.expanded_stack.set_transition_duration(250)
        self.expanded_stack.set_vexpand(True)
        switcher = Adw.ViewSwitcher(stack=self.expanded_stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        switcher.add_css_class("expanded-switcher")
        top.set_center_widget(switcher)
        top.set_end_widget(Gtk.Box(width_request=40))
        shell.append(top)

        music_page = self._expanded_music_page()
        lyrics_page = self._expanded_lyrics_page()
        related_page = self._expanded_related_page()
        music_stack_page = self.expanded_stack.add_titled(music_page, "music", _("Música"))
        music_stack_page.set_icon_name("audio-headphones-symbolic")
        lyrics_stack_page = self.expanded_stack.add_titled(lyrics_page, "lyrics", _("Letras"))
        lyrics_stack_page.set_icon_name("audio-input-microphone-symbolic")
        related_stack_page = self.expanded_stack.add_titled(
            related_page, "related", _("Relacionadas")
        )
        related_stack_page.set_icon_name("media-playlist-consecutive-symbolic")
        self.expanded_stack.connect("notify::visible-child-name", self._expanded_page_changed)
        shell.append(self.expanded_stack)
        surface.add_overlay(shell)
        self.expanded_revealer.set_child(surface)
        self.app_overlay.add_overlay(self.expanded_revealer)
        self.app_overlay.set_measure_overlay(self.expanded_revealer, False)

        key = Gtk.EventControllerKey()
        key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key.connect("key-pressed", self._expanded_key_pressed)
        self.add_controller(key)

    def _expanded_music_page(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        wrap = Adw.WrapBox(
            orientation=Gtk.Orientation.HORIZONTAL,
            child_spacing=76,
            line_spacing=40,
            natural_line_length=900,
            wrap_policy=Adw.WrapPolicy.NATURAL,
            align=0.5,
            valign=Gtk.Align.CENTER,
            hexpand=True,
            vexpand=True,
        )
        wrap.add_css_class("expanded-music-content")
        wrap.set_child_spacing_unit(Adw.LengthUnit.PX)
        wrap.set_line_spacing_unit(Adw.LengthUnit.PX)
        wrap.set_natural_line_length_unit(Adw.LengthUnit.PX)

        cover = Gtk.AspectFrame(ratio=1.0, obey_child=False)
        cover.set_size_request(384, 384)
        cover.set_halign(Gtk.Align.CENTER)
        cover.set_valign(Gtk.Align.CENTER)
        cover.set_overflow(Gtk.Overflow.HIDDEN)
        cover.add_css_class("expanded-cover")
        cover_overlay = Gtk.Overlay(hexpand=True, vexpand=True)
        placeholder = Gtk.Image.new_from_icon_name("audio-x-generic-symbolic")
        placeholder.set_pixel_size(104)
        placeholder.add_css_class("expanded-cover-placeholder")
        cover_overlay.set_child(placeholder)
        self.expanded_cover = Gtk.Picture(
            content_fit=Gtk.ContentFit.COVER,
            can_shrink=True,
            hexpand=True,
            vexpand=True,
        )
        cover_overlay.add_overlay(self.expanded_cover)
        cover.set_child(cover_overlay)
        wrap.append(cover)

        info = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=22,
            valign=Gtk.Align.CENTER,
        )
        info.set_size_request(420, -1)
        info.add_css_class("expanded-info")
        heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        self.expanded_title = Gtk.Label(xalign=0, wrap=True)
        self.expanded_title.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
        self.expanded_title.add_css_class("expanded-title")
        self.expanded_subtitle = Gtk.Label(xalign=0, ellipsize=3)
        self.expanded_subtitle.add_css_class("expanded-subtitle")
        title_box.append(self.expanded_title)
        title_box.append(self.expanded_subtitle)
        heading.append(title_box)
        self.expanded_like_button = Gtk.Button(
            icon_name="non-starred-symbolic",
            tooltip_text=_("Curtir música"),
            valign=Gtk.Align.END,
        )
        style_icon_button(self.expanded_like_button, "md")
        self.expanded_like_button.add_css_class("expanded-like")
        self.expanded_like_button.connect("clicked", lambda *_: self._toggle_current_song_like())
        self.like_buttons.append(self.expanded_like_button)
        heading.append(self.expanded_like_button)
        info.append(heading)

        timeline = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.expanded_elapsed_label = Gtk.Label(label=_("0:00"), width_chars=5, xalign=1)
        self.expanded_elapsed_label.add_css_class("expanded-time")
        timeline.append(self.expanded_elapsed_label)
        self.expanded_progress = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 0.1)
        self.expanded_progress.set_draw_value(False)
        self.expanded_progress.set_hexpand(True)
        self.expanded_progress.set_sensitive(False)
        self.expanded_progress.connect("change-value", self._seek_requested)
        timeline.append(self.expanded_progress)
        self.expanded_duration_label = Gtk.Label(label=_("0:00"), width_chars=5, xalign=0)
        self.expanded_duration_label.add_css_class("expanded-time")
        timeline.append(self.expanded_duration_label)
        info.append(timeline)

        controls = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=21, halign=Gtk.Align.CENTER
        )
        shuffle = Gtk.Button(
            icon_name="media-playlist-shuffle-symbolic", tooltip_text=_("Ordem aleatória")
        )
        shuffle.add_css_class("flat")
        shuffle.add_css_class("expanded-secondary-control")
        shuffle.connect("clicked", lambda button: self._toggle_shuffle(button))
        self.shuffle_buttons.append(shuffle)
        controls.append(shuffle)
        previous = Gtk.Button(icon_name="media-skip-backward-symbolic", tooltip_text=_("Anterior"))
        previous.add_css_class("flat")
        previous.add_css_class("expanded-skip-control")
        previous.connect("clicked", lambda *_: self._play_previous())
        controls.append(previous)
        self.expanded_play_button = Gtk.Button(
            icon_name="media-playback-pause-symbolic",
            tooltip_text=_("Pausar ou continuar"),
        )
        self.expanded_play_button.add_css_class("circular")
        self.expanded_play_button.add_css_class("expanded-play-control")
        self.expanded_play_button.connect("clicked", lambda *_: self._toggle_player())
        controls.append(self.expanded_play_button)
        next_button = Gtk.Button(icon_name="media-skip-forward-symbolic", tooltip_text=_("Próxima"))
        next_button.add_css_class("flat")
        next_button.add_css_class("expanded-skip-control")
        next_button.connect("clicked", lambda *_: self._play_next())
        controls.append(next_button)
        repeat = Gtk.Button(icon_name="media-playlist-repeat-symbolic", tooltip_text=_("Repetir"))
        repeat.add_css_class("flat")
        repeat.add_css_class("expanded-secondary-control")
        repeat.connect("clicked", lambda button: self._toggle_repeat(button))
        self.repeat_buttons.append(repeat)
        controls.append(repeat)
        info.append(controls)
        wrap.append(info)
        scroll.set_child(wrap)
        return scroll

    def _expanded_lyrics_page(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_kinetic_scrolling(True)
        self.expanded_lyrics_scroll = scroll
        self.expanded_lyrics_container = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            hexpand=True,
            vexpand=True,
        )
        self.expanded_lyrics_container.add_css_class("expanded-tab-page")
        scroll.set_child(self.expanded_lyrics_container)
        self._set_expanded_lyrics_message(
            "audio-input-microphone-symbolic",
            _("Letras"),
            _("Comece a reproduzir uma música para ver a letra."),
        )
        return scroll

    def _expanded_related_page(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.expanded_related_container = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=14,
        )
        self.expanded_related_container.add_css_class("expanded-tab-page")
        scroll.set_child(self.expanded_related_container)
        self._render_expanded_related()
        return scroll

    def _footer_cover_hover(self, hovered: bool) -> None:
        if getattr(self, "current_item", None) is None:
            hovered = False
        self.now_cover.set_opacity(0.52 if hovered else 1.0)
        self.cover_expand_hint.set_opacity(1.0 if hovered else 0.0)

    def _set_footer_item_state(self, has_item: bool) -> None:
        """Switch the persistent footer between its empty and playable states."""
        self.footer_cover_button.set_sensitive(has_item)
        self.footer_track_copy.set_sensitive(has_item)
        for control in self.footer_item_controls:
            control.set_sensitive(has_item)
        if has_item:
            self.player_bar.remove_css_class("player-bar-empty")
            return
        self.player_bar.add_css_class("player-bar-empty")
        self.now_title.set_label(_("Nenhuma música reproduzindo"))
        self.now_subtitle.set_label(_("Escolha uma faixa para começar"))
        self.now_cover.set_paintable(None)
        self.ambient_background.set_paintable(None)
        self.now_cover.set_opacity(1.0)
        self.cover_expand_hint.set_opacity(0.0)
        self.play_button.set_icon_name("media-playback-start-symbolic")
        self.elapsed_label.set_label(_("0:00"))
        self.duration_label.set_label(_("0:00"))
        self.progress.set_value(0)
        self.progress.set_sensitive(False)

    def _show_expanded_player(self) -> None:
        if getattr(self, "current_item", None) is None:
            return
        self._refresh_expanded_player()
        self.expanded_stack.set_visible_child_name("music")
        self.player_bar.set_visible(False)
        self.expanded_revealer.set_reveal_child(True)
        self.expanded_revealer.set_can_target(True)
        GLib.idle_add(self.expanded_close_button.grab_focus)

    def _hide_expanded_player(self) -> None:
        self.expanded_revealer.set_reveal_child(False)
        self.player_bar.set_visible(True)

    def _expanded_key_pressed(self, _controller, keyval, _keycode, _state) -> bool:
        if keyval == Gdk.KEY_Escape and self.expanded_revealer.get_reveal_child():
            self._hide_expanded_player()
            return True
        return False

    def _expanded_page_changed(self, stack: Adw.ViewStack, _pspec) -> None:
        page = stack.get_visible_child_name()
        if page == "lyrics":
            self._load_current_lyrics()
        elif page == "related":
            self._render_expanded_related()

    def _refresh_expanded_player(self) -> None:
        item = getattr(self, "current_item", None)
        if item is None:
            return
        self.expanded_title.set_label(item.title)
        subtitle = re.sub(r"\s*[·•]\s*(?:(?:\d+):)?\d{1,2}:\d{2}\s*$", "", item.subtitle or "")
        self.expanded_subtitle.set_label(subtitle or "YouTube Music")
        if item.thumbnail:
            self.expanded_cover.set_paintable(None)
            self.expanded_backdrop_base.set_paintable(None)
            self.expanded_backdrop.set_paintable(None)
            # Reuse an already-cached thumbnail immediately, then replace it
            # with the dedicated high-resolution variant when available.
            self._load_artwork(item.thumbnail, self.expanded_cover)
            self._load_artwork(item.thumbnail, self.expanded_cover, size=1024)
            self._load_artwork(item.thumbnail, self.expanded_backdrop_base, size=1280)
            self._load_artwork(item.thumbnail, self.expanded_backdrop, size=1280)
            self._load_artwork(item.thumbnail, self.ambient_background, size=1280)
        else:
            self.expanded_cover.set_paintable(None)
            self.expanded_backdrop_base.set_paintable(None)
            self.expanded_backdrop.set_paintable(None)
            self.ambient_background.set_paintable(None)
        self._refresh_current_like_from_library()
        self._render_expanded_related()

    def _set_expanded_lyrics_message(self, icon: str, title: str, description: str) -> None:
        if not hasattr(self, "expanded_lyrics_container"):
            return
        while child := self.expanded_lyrics_container.get_first_child():
            self.expanded_lyrics_container.remove(child)
        status = Adw.StatusPage(icon_name=icon, title=title, description=description)
        status.set_vexpand(True)
        self.expanded_lyrics_container.append(status)

    def _render_expanded_lyrics(self, item: LibraryItem, document: LyricsDocument) -> None:
        while child := self.expanded_lyrics_container.get_first_child():
            self.expanded_lyrics_container.remove(child)
        clamp = Adw.Clamp(maximum_size=760, tightening_threshold=620)
        box = self._lyrics_surface(item, document, expanded=True)
        if self._lyric_views and self._lyric_views[-1]["expanded"]:
            self._lyric_views[-1]["scroll"] = self.expanded_lyrics_scroll
        clamp.set_child(box)
        self.expanded_lyrics_container.append(clamp)

    def _render_expanded_related(self) -> None:
        if not hasattr(self, "expanded_related_container"):
            return
        while child := self.expanded_related_container.get_first_child():
            self.expanded_related_container.remove(child)
        clamp = Adw.Clamp(maximum_size=760, tightening_threshold=620)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        heading = Gtk.Label(label=_("Fila"), xalign=0)
        heading.add_css_class("expanded-related-title")
        box.append(heading)
        if not self.queue:
            box.append(
                Adw.StatusPage(
                    icon_name="media-playlist-consecutive-symbolic",
                    title=_("Nada na fila"),
                    description=_("Escolha uma música para ver as próximas faixas."),
                )
            )
        else:
            listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            listing.add_css_class("boxed-list")
            for position, item in enumerate(self.queue):
                row = Adw.ActionRow()
                row.add_css_class("media-row")
                row.set_use_markup(False)
                row.set_title(item.title)
                row.set_subtitle(item.subtitle)
                row.set_activatable(True)
                if position == self.queue_index:
                    row.add_prefix(Gtk.Image.new_from_icon_name("audio-volume-high-symbolic"))
                    row.add_css_class("current-track")
                row.connect(
                    "activated",
                    lambda _row, selected=position: self._select_expanded_queue_item(selected),
                )
                listing.append(row)
            box.append(listing)
            related_heading = Gtk.Label(label=_("Relacionadas"), xalign=0)
            related_heading.add_css_class("expanded-related-title")
            box.append(related_heading)
            if self.related_items:
                related = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
                related.add_css_class("boxed-list")
                for item in self.related_items:
                    row = Adw.ActionRow()
                    row.set_use_markup(False)
                    row.set_title(item.title)
                    row.set_subtitle(item.subtitle)
                    add = Gtk.Button(
                        icon_name="list-add-symbolic", tooltip_text=_("Adicionar ao fim")
                    )
                    add.add_css_class("flat")
                    add.connect(
                        "clicked",
                        lambda *_args, selected=item: GLib.idle_add(
                            self._promote_related, selected, False
                        ),
                    )
                    row.add_suffix(add)
                    related.append(row)
                box.append(related)
        clamp.set_child(box)
        self.expanded_related_container.append(clamp)

    def _select_expanded_queue_item(self, position: int) -> None:
        self.queue_index = position
        self._render_queue()
        self.play_item(self.queue[position])

    def show_library(self) -> None:
        self.main_view = "library"
        self.back.set_visible(False)
        self._render()
        self.stack.set_visible_child_name("library")
        self._set_active_nav("library")

    def _go_back(self) -> None:
        if self.main_view == "home":
            self.show_home()
        elif self.main_view.startswith("explore"):
            self.show_explore()
        elif self.main_view == "history":
            self.show_home()
        elif self.main_view == "downloads":
            self.show_library()
        elif self.main_view == "settings":
            self.show_home()
        elif self.main_view == "artist-section" and self._artist_current_item:
            self._open_artist(self._artist_current_item)
        else:
            self.show_library()

    def show_home(self) -> None:
        self.main_view = "home"
        self.back.set_visible(False)
        self._render_home()
        self.stack.set_visible_child_name("home")
        self._set_active_nav("home")

    def show_history(self) -> None:
        self.main_view = "history"
        self.back.set_visible(False)
        self._set_active_nav("history")
        self._history_entries = self.storage.load_history()
        self._render_history(self._history_entries, loading=True)

        def worker() -> None:
            try:
                remote = self.youtube.history() if self.storage.load_cookie() else []
                GLib.idle_add(self._history_loaded, remote, None)
            except Exception as exc:
                GLib.idle_add(self._history_loaded, [], str(exc))

        threading.Thread(target=worker, daemon=True, name="account-history").start()

    def _validate_download_account(self) -> None:
        try:
            self.downloads.validate_account()
        except Exception:
            LOGGER.debug("Não foi possível validar a conta dos downloads", exc_info=True)

    def _periodic_download_validation(self) -> bool:
        if self.storage.load_cookie():
            threading.Thread(
                target=self._validate_download_account,
                daemon=True,
                name="download-account-periodic",
            ).start()
        return GLib.SOURCE_CONTINUE

    @staticmethod
    def _format_bytes(value: int) -> str:
        size = float(max(0, value))
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.1f} {unit}"
            size /= 1024
        return "0 B"

    def show_downloads(self) -> None:
        self.main_view = "downloads"
        self.back.set_visible(False)
        self._set_active_nav("downloads")
        self._render_downloads()

    def _apply_audio_preferences(self) -> None:
        if not hasattr(self, "player"):
            return
        self.player.apply_audio_settings(
            normalization=self.preferences.normalization,
            equalizer=self.preferences.equalizer,
            speed=self.preferences.speed,
            pitch=self.preferences.pitch,
            skip_silence=self.preferences.skip_silence,
        )

    def _preference_changed(self, name: str, value, *, audio: bool = False) -> None:
        setattr(self.preferences, name, value)
        self.preferences.save(self.storage)
        if audio:
            self._apply_audio_preferences()

    def _apply_appearance_preferences(self) -> None:
        blurred = self.preferences.background_blur
        if blurred:
            self.root.add_css_class("appearance-blur")
        else:
            self.root.remove_css_class("appearance-blur")
        self.ambient_background.set_opacity(0.30 if blurred else 0)

        self.root.remove_css_class("icons-material")
        if self.preferences.icon_style != "gtk":
            self.root.add_css_class(f"icons-{self.preferences.icon_style}")
        display = Gdk.Display.get_default()
        if display:
            theme = Gtk.IconTheme.get_for_display(display)
            icons_path = str(Path(__file__).with_name("icons"))
            if icons_path not in theme.get_search_path():
                theme.add_search_path(icons_path)
            settings = Gtk.Settings.get_for_display(display)
            if settings:
                selected = {
                    "material": "HarmoniaMaterial",
                }.get(self.preferences.icon_style, self._system_icon_theme_name)
                settings.set_property("gtk-icon-theme-name", selected)
        self._refresh_custom_icons()

    def _icon_name_changed(self, image: Gtk.Image, _pspec) -> None:
        if self._icon_update_guard:
            return
        name = image.get_icon_name()
        if name:
            self._icon_sources[image] = name
            GLib.idle_add(self._apply_custom_icon, image)

    def _apply_custom_icon(self, image: Gtk.Image) -> bool:
        name = image.get_icon_name()
        if name:
            self._icon_sources[image] = name
        base_name = self._icon_sources.get(image)
        if not base_name:
            return GLib.SOURCE_REMOVE
        self._icon_update_guard = True
        try:
            # Keep the semantic icon name on GtkImage. The process-wide icon
            # theme resolves the selected pack and GTK can then recolor every
            # symbolic icon from the widget's current foreground/accent color.
            image.set_from_icon_name(base_name)
        finally:
            self._icon_update_guard = False
        return GLib.SOURCE_REMOVE

    def _refresh_custom_icons(self) -> bool:
        pending = [self.root]
        while pending:
            widget = pending.pop()
            if isinstance(widget, Gtk.Image):
                if widget not in self._icon_sources:
                    widget.connect("notify::icon-name", self._icon_name_changed)
                self._apply_custom_icon(widget)
            child = widget.get_first_child()
            while child:
                pending.append(child)
                child = child.get_next_sibling()
        return GLib.SOURCE_REMOVE

    def _appearance_changed(self, name: str, value) -> None:
        self._preference_changed(name, value)
        self._apply_appearance_preferences()

    def _cache_size(self) -> int:
        return sum(
            path.stat().st_size for path in self.storage.artwork_dir.iterdir() if path.is_file()
        )

    def _clear_artwork_cache(self, row: Adw.ActionRow) -> None:
        removed = self.storage.clear_cache()
        row.set_subtitle(_("0 B armazenados"))
        self.toast_overlay.add_toast(
            Adw.Toast(
                title=_("Cache limpo · {size} removidos").format(size=self._format_bytes(removed))
            )
        )

    def _set_sleep_timer(self, minutes: int) -> None:
        if self._sleep_timer_source:
            GLib.source_remove(self._sleep_timer_source)
            self._sleep_timer_source = 0
        self._sleep_timer_deadline = 0.0
        if minutes:
            self._sleep_timer_deadline = time.time() + minutes * 60
            self._sleep_timer_source = GLib.timeout_add_seconds(
                minutes * 60, self._sleep_timer_elapsed
            )
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=ngettext(
                        "Temporizador definido para {count} minuto",
                        "Temporizador definido para {count} minutos",
                        minutes,
                    ).format(count=minutes)
                )
            )

    def _sleep_timer_elapsed(self) -> bool:
        self._sleep_timer_source = 0
        self._sleep_timer_deadline = 0.0
        self._pause()
        self.toast_overlay.add_toast(Adw.Toast(title=_("Reprodução pausada pelo temporizador")))
        return GLib.SOURCE_REMOVE

    def _validate_settings_account(self, row: Adw.ActionRow) -> None:
        row.set_subtitle(_("Validando sessão…"))

        def worker() -> None:
            try:
                valid = self.youtube.validate_account()
                error = None
            except Exception as exc:
                valid, error = False, str(exc)
            GLib.idle_add(self._account_validation_done, row, valid, error)

        threading.Thread(target=worker, daemon=True, name="settings-account-validation").start()

    def _account_validation_done(self, row: Adw.ActionRow, valid: bool, error: str | None) -> bool:
        row.set_subtitle(_("Conectada e válida") if valid else _("Sessão inválida ou expirada"))
        self.toast_overlay.add_toast(
            Adw.Toast(
                title=_("Conta validada")
                if valid
                else _("Não foi possível validar a conta{detail}").format(
                    detail=f": {error}" if error else ""
                ),
                timeout=5,
            )
        )
        return GLib.SOURCE_REMOVE

    def _disconnect_from_settings(self) -> None:
        self.youtube.disconnect()
        self._clear_account_avatar()
        self.toast_overlay.add_toast(Adw.Toast(title=_("Conta desconectada")))
        self.show_settings()

    def show_settings(self) -> None:
        self.main_view = "settings"
        self.back.set_visible(False)
        self._set_active_nav("settings")
        old = self.stack.get_child_by_name("settings")
        if old:
            self.stack.remove(old)

        page = Adw.PreferencesPage(title=_("Preferências"))
        page.add_css_class("app-preferences")

        account_group = Adw.PreferencesGroup(
            title=_("Conta"),
            description=_("Sessão protegida pelo chaveiro Secret Service do sistema."),
        )
        account = Adw.ActionRow(
            title=_("YouTube Music"),
            subtitle=_("Conectada") if self.storage.load_cookie() else _("Não conectada"),
        )
        account.add_prefix(Gtk.Image.new_from_icon_name("avatar-default-symbolic"))
        if self.storage.load_cookie():
            validate = Gtk.Button(label=_("Validar"), valign=Gtk.Align.CENTER)
            validate.add_css_class("pill")
            validate.connect("clicked", lambda *_: self._validate_settings_account(account))
            account.add_suffix(validate)
            disconnect = Gtk.Button(
                icon_name="system-log-out-symbolic",
                tooltip_text=_("Desconectar"),
                valign=Gtk.Align.CENTER,
            )
            style_icon_button(disconnect, "sm")
            disconnect.add_css_class("destructive-action")
            disconnect.connect("clicked", lambda *_: self._disconnect_from_settings())
            account.add_suffix(disconnect)
        else:
            connect = Gtk.Button(label=_("Conectar"), valign=Gtk.Align.CENTER)
            connect.add_css_class("pill")
            connect.add_css_class("suggested-action")
            connect.connect("clicked", lambda *_: self.login_dialog())
            account.add_suffix(connect)
        account_group.add(account)
        page.add(account_group)

        streaming = Adw.PreferencesGroup(
            title=_("Streaming"),
            description=_("Estas opções são aplicadas à próxima requisição ao YouTube Music."),
        )

        def combo(
            title: str, values: list[tuple[str, str]], current: str, callback
        ) -> Adw.ComboRow:
            row = Adw.ComboRow(
                title=title, model=Gtk.StringList.new([label for label, _ in values])
            )
            keys = [key for _, key in values]
            row.set_selected(keys.index(current) if current in keys else 0)
            row.connect(
                "notify::selected", lambda widget, _pspec: callback(keys[widget.get_selected()])
            )
            return row

        appearance = Adw.PreferencesGroup(
            title=_("Aparência"),
            description=_("Personalize o ambiente visual sem alterar o conteúdo."),
        )
        blur = Adw.SwitchRow(
            title=_("Fundo ambiente desfocado"),
            subtitle=_("Usa as cores da capa atual atrás da interface"),
        )
        blur.set_active(self.preferences.background_blur)
        blur.connect(
            "notify::active",
            lambda row, _pspec: self._appearance_changed("background_blur", row.get_active()),
        )
        appearance.add(blur)
        appearance.add(
            combo(
                _("Estilo dos ícones"),
                [
                    (_("GTK — padrão do sistema"), "gtk"),
                    (_("Material Expressive"), "material"),
                ],
                self.preferences.icon_style,
                lambda value: self._appearance_changed("icon_style", value),
            )
        )
        page.add(appearance)

        streaming.add(
            combo(
                _("Qualidade do áudio"),
                [(_("Alta"), "high"), (_("Média"), "medium"), (_("Econômica"), "low")],
                self.preferences.quality,
                lambda value: self._preference_changed("quality", value),
            )
        )
        streaming.add(
            combo(
                _("Idioma"),
                [
                    (_("Português (Brasil)"), "pt-BR"),
                    (_("English"), "en-US"),
                    (_("Español"), "es-ES"),
                    ("日本語", "ja-JP"),
                ],
                self.preferences.language,
                lambda value: self._preference_changed("language", value),
            )
        )
        streaming.add(
            combo(
                _("Região"),
                [
                    (_("Brasil"), "BR"),
                    (_("Estados Unidos"), "US"),
                    (_("Portugal"), "PT"),
                    (_("Japão"), "JP"),
                ],
                self.preferences.region,
                lambda value: self._preference_changed("region", value),
            )
        )
        proxy = Adw.ActionRow(
            title=_("Proxy HTTP(S)"), subtitle=_("Opcional · exemplo: http://127.0.0.1:8080")
        )
        proxy_entry = Gtk.Entry(
            text=self.preferences.proxy, placeholder_text=_("Sem proxy"), valign=Gtk.Align.CENTER
        )
        proxy_entry.set_size_request(260, -1)
        proxy_entry.connect(
            "changed", lambda entry: self._preference_changed("proxy", entry.get_text().strip())
        )
        proxy.add_suffix(proxy_entry)
        streaming.add(proxy)
        cache = Adw.ActionRow(
            title=_("Cache de capas"),
            subtitle=_("{size} armazenados").format(size=self._format_bytes(self._cache_size())),
        )
        clear_cache = Gtk.Button(label=_("Limpar"), valign=Gtk.Align.CENTER)
        clear_cache.add_css_class("pill")
        clear_cache.connect("clicked", lambda *_: self._clear_artwork_cache(cache))
        cache.add_suffix(clear_cache)
        streaming.add(cache)
        page.add(streaming)

        audio = Adw.PreferencesGroup(
            title=_("Áudio"),
            description=_("Processamento nativo em tempo real pelo GStreamer."),
        )
        audio.add(
            combo(
                "Equalizador",
                [("Plano", "flat"), ("Graves", "bass"), ("Voz", "vocal"), ("Agudos", "treble")],
                self.preferences.equalizer,
                lambda value: self._preference_changed("equalizer", value, audio=True),
            )
        )
        normalization = Adw.SwitchRow(
            title=_("Normalização de volume"), subtitle=_("Reduz variações de volume entre faixas")
        )
        normalization.set_active(self.preferences.normalization)
        normalization.connect(
            "notify::active",
            lambda row, _pspec: self._preference_changed(
                "normalization", row.get_active(), audio=True
            ),
        )
        audio.add(normalization)
        silence = Adw.SwitchRow(
            title=_("Pular silêncio"), subtitle=_("Remove trechos silenciosos longos")
        )
        silence.set_active(self.preferences.skip_silence)
        silence.connect(
            "notify::active",
            lambda row, _pspec: self._preference_changed(
                "skip_silence", row.get_active(), audio=True
            ),
        )
        audio.add(silence)

        def scale_row(
            title: str,
            lower: float,
            upper: float,
            step: float,
            value: float,
            callback,
            digits: int = 1,
        ) -> Adw.ActionRow:
            row = Adw.ActionRow(title=title)
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lower, upper, step)
            scale.set_draw_value(True)
            scale.set_digits(digits)
            scale.set_value(value)
            scale.set_size_request(260, -1)
            scale.set_valign(Gtk.Align.CENTER)
            scale.connect("value-changed", lambda widget: callback(widget.get_value()))
            row.add_suffix(scale)
            return row

        audio.add(
            scale_row(
                "Velocidade",
                0.5,
                2.0,
                0.05,
                self.preferences.speed,
                lambda value: self._preference_changed("speed", value, audio=True),
                2,
            )
        )
        audio.add(
            scale_row(
                "Tom (semitons)",
                -12,
                12,
                1,
                self.preferences.pitch,
                lambda value: self._preference_changed("pitch", value, audio=True),
                0,
            )
        )
        timer_values = [
            ("Desligado", 0),
            ("15 minutos", 15),
            ("30 minutos", 30),
            ("1 hora", 60),
            ("1 hora e 30", 90),
        ]
        timer = Adw.ComboRow(
            title=_("Temporizador"), model=Gtk.StringList.new([label for label, _ in timer_values])
        )
        timer.connect(
            "notify::selected",
            lambda row, _pspec: self._set_sleep_timer(timer_values[row.get_selected()][1]),
        )
        audio.add(timer)
        page.add(audio)

        self.stack.add_named(page, "settings")
        self.stack.set_visible_child_name("settings")

    def _render_downloads(self) -> None:
        old = self.stack.get_child_by_name("downloads")
        if old:
            self.stack.remove(old)
        records = self.storage.load_downloads()
        shell = page_shell("reading", spacing=20)
        scroll, content = shell.scroll, shell.content
        validate = action_button(_("Validar conta"), "emblem-ok-symbolic", role="secondary")
        validate.connect(
            "clicked",
            lambda *_: threading.Thread(
                target=self._validate_download_account, daemon=True
            ).start(),
        )
        content.append(
            page_header(
                _("Downloads"),
                ngettext(
                    "{count} item · {size} utilizado",
                    "{count} itens · {size} utilizados",
                    len(records),
                ).format(
                    count=len(records),
                    size=self._format_bytes(self.storage.download_storage_bytes()),
                ),
                actions=(validate,),
            )
        )
        if not records:
            content.append(
                Adw.StatusPage(
                    icon_name="folder-download-symbolic",
                    title=_("Nenhum download"),
                    description=_(
                        "Use o botão de download em um álbum ou playlist para ouvir offline."
                    ),
                )
            )
        else:
            group = Adw.PreferencesGroup()
            status_labels = {
                "queued": _("Na fila"),
                "downloading": _("Baixando"),
                "paused": _("Pausado"),
                "completed": _("Disponível offline"),
                "failed": _("Falha"),
            }
            for record in records:
                subtitle = status_labels.get(record.status, record.status)
                if record.total_bytes:
                    subtitle += f" · {self._format_bytes(record.downloaded_bytes)} de {self._format_bytes(record.total_bytes)}"
                if record.error:
                    subtitle += f" · {record.error}"
                row = Adw.ActionRow()
                row.add_css_class("media-row")
                row.set_use_markup(False)
                row.set_title(record.item.title)
                row.set_subtitle(subtitle)
                row.add_prefix(self._square_cover(record.item, size=48, fixed=True))
                controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
                if record.status == "downloading":
                    pause = icon_button("media-playback-pause-symbolic", _("Pausar"), size="sm")
                    pause.connect(
                        "clicked",
                        lambda *_args, item_id=record.item.id: self.downloads.pause(item_id),
                    )
                    controls.append(pause)
                elif record.status in ("paused", "failed", "queued"):
                    resume = icon_button("media-playback-start-symbolic", _("Retomar"), size="sm")
                    resume.connect(
                        "clicked", lambda *_args, item=record.item: self.downloads.start(item)
                    )
                    controls.append(resume)
                elif record.status == "completed":
                    play = icon_button(
                        "media-playback-start-symbolic", _("Reproduzir offline"), size="sm"
                    )
                    play.connect(
                        "clicked", lambda *_args, item=record.item: self.set_queue([item], 0)
                    )
                    controls.append(play)
                remove = icon_button(
                    "user-trash-symbolic", _("Excluir download"), size="sm", destructive=True
                )
                remove.connect(
                    "clicked", lambda *_args, item_id=record.item.id: self.downloads.remove(item_id)
                )
                controls.append(remove)
                row.add_suffix(controls)
                group.add(row)
            content.append(group)
        self.stack.add_named(scroll, "downloads")
        self.stack.set_visible_child_name("downloads")

    def _download_updated(self, _record: DownloadRecord | None) -> bool:
        if self.main_view == "downloads":
            self._render_downloads()
        if self.main_view == "library" and self.library_origin == "downloads":
            self._render()
        return False

    def _history_loaded(self, remote: list[HistoryEntry], error: str | None) -> bool:
        if self.main_view != "history":
            return False
        local = self.storage.load_history()
        self._history_entries = [*remote, *local]
        self._render_history(self._history_entries, loading=False)
        if error:
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=_("O histórico local foi preservado; o remoto falhou: {error}").format(
                        error=error
                    ),
                    timeout=5,
                )
            )
        return False

    def _render_history(self, entries: list[HistoryEntry], loading: bool = False) -> None:
        old = self.stack.get_child_by_name("history")
        if old:
            self.stack.remove(old)
        shell = page_shell("reading", spacing=20)
        scroll, content = shell.scroll, shell.content
        clear = action_button(_("Limpar local"), "user-trash-symbolic", role="secondary")
        clear.set_sensitive(any(entry.source == "local" for entry in entries))
        clear.connect("clicked", lambda *_: self._clear_local_history())
        content.append(
            page_header(
                _("Histórico"),
                _("Reproduções da conta e deste dispositivo"),
                actions=(clear,),
            )
        )

        privacy = Adw.ActionRow()
        privacy.set_use_markup(False)
        privacy.set_title(_("Registrar neste dispositivo"))
        privacy.set_subtitle(
            _("Quando desativado, o Harmonia não grava novas reproduções localmente.")
        )
        toggle = Gtk.Switch(active=self.storage.history_enabled(), valign=Gtk.Align.CENTER)
        toggle.connect("notify::active", self._history_privacy_changed)
        privacy.add_suffix(toggle)
        privacy.set_activatable_widget(toggle)
        privacy.add_css_class("boxed-list")
        content.append(privacy)
        if loading:
            spinner = Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER)
            content.append(spinner)

        grouped: dict[str, list[HistoryEntry]] = {}
        for entry in entries:
            group = entry.group
            if entry.source == "local" and entry.played_at:
                group = datetime.fromtimestamp(entry.played_at).strftime("%d/%m/%Y")
            grouped.setdefault(group, []).append(entry)
        if not grouped and not loading:
            empty = Adw.StatusPage(
                icon_name="document-open-recent-symbolic",
                title=_("Nenhuma reprodução"),
                description=_("As músicas tocadas aparecerão aqui."),
            )
            content.append(empty)
        for group_name, group_entries in grouped.items():
            group = Adw.PreferencesGroup(title=group_name)
            for entry in group_entries:
                row = Adw.ActionRow()
                row.add_css_class("media-row")
                row.set_use_markup(False)
                row.set_title(entry.item.title)
                row.set_subtitle(
                    entry.item.subtitle
                    or (_("YouTube Music") if entry.source == "remote" else _("Neste dispositivo"))
                )
                row.set_activatable(True)
                row.add_prefix(self._square_cover(entry.item, size=48, fixed=True))
                remove = icon_button(
                    "user-trash-symbolic", _("Remover do histórico"), size="sm", destructive=True
                )
                remove.set_sensitive(entry.source == "local" or bool(entry.feedback_token))
                remove.connect(
                    "clicked",
                    lambda *_args, selected=entry: GLib.idle_add(
                        self._remove_history_entry, selected
                    ),
                )
                row.add_suffix(remove)
                row.connect(
                    "activated", lambda _row, selected=entry.item: self.set_queue([selected], 0)
                )
                group.add(row)
            content.append(group)
        self.stack.add_named(scroll, "history")
        self.stack.set_visible_child_name("history")

    def _history_privacy_changed(self, switch: Gtk.Switch, _pspec) -> None:
        self.storage.set_history_enabled(switch.get_active())
        self.toast_overlay.add_toast(
            Adw.Toast(
                title=_("Histórico local ativado")
                if switch.get_active()
                else _("Histórico local pausado")
            )
        )

    def _clear_local_history(self) -> None:
        self.storage.clear_history()
        self._history_entries = [
            entry for entry in self._history_entries if entry.source != "local"
        ]
        self._render_history(self._history_entries)

    def _remove_history_entry(self, entry: HistoryEntry) -> None:
        if entry.source == "local" and entry.id is not None:
            self.storage.remove_history(entry.id)
            self._history_entries = [
                candidate for candidate in self._history_entries if candidate is not entry
            ]
            self._render_history(self._history_entries)
            return

        def worker() -> None:
            try:
                self.youtube.remove_history_item(entry.feedback_token or "")
                GLib.idle_add(done, None)
            except Exception as exc:
                GLib.idle_add(done, str(exc))

        def done(error: str | None) -> bool:
            if error:
                self.toast_overlay.add_toast(
                    Adw.Toast(
                        title=_("Não foi possível remover: {error}").format(error=error),
                        timeout=5,
                    )
                )
            else:
                self._history_entries = [
                    candidate for candidate in self._history_entries if candidate is not entry
                ]
                self._render_history(self._history_entries)
            return False

        threading.Thread(target=worker, daemon=True, name="remove-history").start()

    def show_explore(self) -> None:
        self.main_view = "explore"
        self.back.set_visible(False)
        page = self._explore_page(
            _("Explorar"),
            _("Lançamentos, paradas e sons para cada momento."),
            self.explore_data,
        )
        old = self.stack.get_child_by_name("explore")
        if old:
            self.stack.remove(old)
        self.stack.add_named(page, "explore")
        self.stack.set_visible_child_name("explore")
        self._set_active_nav("explore")

    def _explore_page(
        self, title: str, description: str, data: ExploreData, full_sections: bool = False
    ) -> Gtk.Widget:
        shell = page_shell("content", spacing=24)
        content = shell.content
        content.append(page_header(title, description))
        if data.shortcuts:
            content.append(self._destination_section(_("Descubra"), data.shortcuts, prominent=True))
        for section in data.sections:
            limit = len(section.items) if full_sections else 12
            content.append(self._home_section(section.title, section.items, limit=limit))
        if data.genres:
            content.append(self._destination_section(_("Momentos e gêneros"), data.genres))
        if not data.sections and not data.shortcuts and not data.genres:
            content.append(
                Adw.StatusPage(
                    icon_name="view-refresh-symbolic",
                    title=_("Preparando o Explorar…"),
                    description=_("Buscando novidades no YouTube Music"),
                )
            )
        return shell.scroll

    def _destination_section(
        self, title: str, destinations: list[ExploreDestination], prominent: bool = False
    ) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.append(self._section_header(title))
        flow = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            column_spacing=12,
            row_spacing=10,
            min_children_per_line=2,
            max_children_per_line=4,
            homogeneous=True,
        )
        icons = {
            "FEmusic_new_releases": "media-optical-symbolic",
            "FEmusic_charts": "view-list-symbolic",
            "FEmusic_moods_and_genres": "applications-multimedia-symbolic",
            "FEmusic_non_music_audio": "audio-headphones-symbolic",
        }
        for destination in destinations:
            button = Gtk.Button()
            button.add_css_class("explore-shortcut" if prominent else "genre-chip")
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            if prominent:
                icon = Gtk.Image.new_from_icon_name(icons.get(destination.browse_id, EXPLORE_ICON))
                icon.set_pixel_size(22)
                row.append(icon)
            row.append(Gtk.Label(label=destination.title, xalign=0, hexpand=True, ellipsize=3))
            row.append(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            button.set_child(row)
            button.connect(
                "clicked", lambda _button, selected=destination: self.open_destination(selected)
            )
            flow.append(button)
        box.append(flow)
        return box

    def open_destination(self, destination: ExploreDestination) -> None:
        self.main_view = "explore-detail"
        self.back.set_visible(True)
        self._set_active_nav("explore")
        status = Adw.StatusPage(
            icon_name="view-refresh-symbolic",
            title=_("Carregando {title}…").format(title=destination.title),
            description=_("Consultando o YouTube Music"),
        )
        old = self.stack.get_child_by_name("discovery")
        if old:
            self.stack.remove(old)
        self.stack.add_named(status, "discovery")
        self.stack.set_visible_child_name("discovery")

        def worker():
            try:
                data = self.youtube.discovery(destination)
                GLib.idle_add(self._destination_loaded, destination, data, None)
            except Exception as exc:
                GLib.idle_add(self._destination_loaded, destination, None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _destination_loaded(
        self, destination: ExploreDestination, data: ExploreData | None, error: str | None
    ):
        old = self.stack.get_child_by_name("discovery")
        if old:
            self.stack.remove(old)
        if error:
            page = Adw.StatusPage(
                icon_name="dialog-error-symbolic",
                title=_("Não foi possível abrir"),
                description=error,
            )
        else:
            page = self._explore_page(
                destination.title,
                _("Seleção atualizada pelo YouTube Music."),
                data or ExploreData([], [], []),
                full_sections=True,
            )
        self.stack.add_named(page, "discovery")
        self.stack.set_visible_child_name("discovery")
        return False

    def _render_home(self) -> None:
        self.home_song_rows = []
        shell = page_shell("content", spacing=30, css_classes=("home-content",))
        page, content = shell.scroll, shell.content
        content.append(page_header(_("Início"), _("Escolhas feitas para você pelo YouTube Music")))
        if not self.home_sections:
            content.append(
                Adw.StatusPage(
                    icon_name="view-refresh-symbolic",
                    title=_("Preparando sua música…"),
                    description=_("Carregando recomendações personalizadas"),
                )
            )
        for section in self.home_sections:
            if section.items:
                content.append(self._home_section(section.title, section.items))
        old = self.stack.get_child_by_name("home")
        if old:
            self.stack.remove(old)
        self.stack.add_named(page, "home")

    def _home_section(self, title: str, items: list[LibraryItem], limit: int = 12) -> Gtk.Widget:
        unique_items = list({item.id: item for item in items}.values())
        if unique_items and all(item.kind == "songs" for item in unique_items):
            return self._home_song_section(title, unique_items[: max(limit, 24)])
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.add_css_class("home-shelf")
        box.set_vexpand(False)
        box.set_valign(Gtk.Align.START)
        scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.EXTERNAL,
            vscrollbar_policy=Gtk.PolicyType.NEVER,
            min_content_width=1,
            min_content_height=218,
            propagate_natural_width=False,
        )
        scroll.set_kinetic_scrolling(True)
        scroll.set_vexpand(False)
        scroll.set_valign(Gtk.Align.START)
        shelf = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        shelf.add_css_class("home-shelf-row")
        shelf.set_vexpand(False)
        shelf.set_valign(Gtk.Align.START)
        for item in items[:limit]:
            button = self._media_card_button(
                item,
                168,
                lambda selected=item, source=items: self._open_home_item(selected, source),
            )
            button.add_css_class("home-media-card-button")
            shelf.append(button)
        scroll.set_child(shelf)
        box.append(self._home_shelf_header(title, scroll))
        box.append(scroll)
        return box

    def _home_song_section(self, title: str, items: list[LibraryItem]) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.add_css_class("home-shelf")
        box.add_css_class("home-song-shelf")
        box.set_vexpand(False)
        box.set_valign(Gtk.Align.START)
        scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.EXTERNAL,
            vscrollbar_policy=Gtk.PolicyType.NEVER,
            min_content_width=1,
            min_content_height=256,
            propagate_natural_width=False,
        )
        scroll.set_kinetic_scrolling(True)
        scroll.set_vexpand(False)
        scroll.set_valign(Gtk.Align.START)
        grid = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        grid.add_css_class("home-song-grid")
        grid.set_vexpand(False)
        grid.set_valign(Gtk.Align.START)
        columns: list[Gtk.Box] = []
        for start in range(0, len(items), 4):
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            column.add_css_class("home-song-column")
            column.set_vexpand(False)
            column.set_size_request(420, -1)
            columns.append(column)
            for track in items[start : start + 4]:
                column.append(self._home_song_row(track, items))
            grid.append(column)
        scroll.set_child(grid)
        box.append(self._home_shelf_header(title, scroll, lambda: self.set_queue(items, 0)))
        box.append(scroll)

        last_width = {"value": 0}

        def resize_columns(widget: Gtk.Widget):
            viewport = widget.get_width()
            if viewport <= 1 or viewport == last_width["value"]:
                return
            last_width["value"] = viewport
            width = self._home_song_column_width(viewport)
            for column in columns:
                column.set_size_request(width, -1)

        def follow_allocation(widget: Gtk.Widget, _clock) -> bool:
            resize_columns(widget)
            return GLib.SOURCE_CONTINUE

        scroll.add_tick_callback(follow_allocation)
        return box

    @staticmethod
    def _home_song_column_width(viewport: int, gap: int = 14) -> int:
        if (viewport - gap * 2) / 3 >= 320:
            visible_columns = 3
        elif (viewport - gap) / 2 >= 320:
            visible_columns = 2
        else:
            visible_columns = 1
        if visible_columns == 1:
            return max(280, int(viewport * 0.9))
        return int((viewport - gap * (visible_columns - 1)) / visible_columns)

    def _home_song_row(self, track: LibraryItem, source: list[LibraryItem]) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=11)
        row.add_css_class("home-song-row")
        row.add_css_class("media-row")
        row.set_size_request(-1, 64)
        row.set_vexpand(False)
        row.set_cursor_from_name("pointer")

        cover = Gtk.AspectFrame(ratio=1.0, obey_child=False)
        cover.set_size_request(48, 48)
        cover.set_halign(Gtk.Align.START)
        cover.set_valign(Gtk.Align.CENTER)
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
            self._load_artwork(track.thumbnail, picture, size=128)
            artwork.add_overlay(picture)
        play_hint = Gtk.Box(halign=Gtk.Align.FILL, valign=Gtk.Align.FILL)
        play_hint.add_css_class("home-song-play-hint")
        play_hint.set_opacity(0)
        play_hint.set_can_target(False)
        play_icon = Gtk.Image.new_from_icon_name("media-playback-start-symbolic")
        play_icon.set_pixel_size(22)
        play_icon.set_hexpand(True)
        play_icon.set_vexpand(True)
        play_icon.set_halign(Gtk.Align.CENTER)
        play_icon.set_valign(Gtk.Align.CENTER)
        play_hint.append(play_icon)
        artwork.add_overlay(play_hint)
        cover.set_child(artwork)
        row.append(cover)

        copy = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True, valign=Gtk.Align.CENTER
        )
        name = Gtk.Label(label=track.title, xalign=0, ellipsize=3)
        name.add_css_class("home-song-title")
        subtitle = Gtk.Label(label=track.subtitle or "YouTube Music", xalign=0, ellipsize=3)
        subtitle.add_css_class("home-song-subtitle")
        copy.append(name)
        copy.append(subtitle)
        row.append(copy)

        liked = any(song.id == track.id for song in self.sections.get("songs", []))
        liked_icon = Gtk.Image.new_from_icon_name("starred-symbolic")
        liked_icon.add_css_class("home-song-liked")
        liked_icon.set_opacity(1.0 if liked else 0.0)
        row.append(liked_icon)

        options = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text=_("Opções da faixa"))
        style_icon_button(options, "sm")
        options.add_css_class("home-song-options")
        popover = Gtk.Popover()
        menu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        menu.add_css_class("detail-menu")
        like = menu_action_button(
            _("Remover das curtidas") if liked else _("Curtir música"),
            "starred-symbolic" if liked else "non-starred-symbolic",
        )
        add = menu_action_button(_("Adicionar à playlist"), "list-add-symbolic")
        add.connect("clicked", lambda *_: (popover.popdown(), self.add_to_playlist_dialog(track)))
        menu.append(like)
        menu.append(add)
        download = menu_action_button(_("Baixar"), "folder-download-symbolic")
        download.connect("clicked", lambda *_: (popover.popdown(), self._download_items([track])))
        menu.append(download)
        popover.set_child(menu)
        options.set_popover(popover)
        row.append(options)

        state = {
            "row": row,
            "track": track,
            "source": source,
            "play_hint": play_hint,
            "play_icon": play_icon,
            "title": name,
            "liked": liked,
            "liked_icon": liked_icon,
            "like_button": like,
            "options": options,
            "hovered": False,
        }
        self.home_song_rows.append(state)
        like.connect("clicked", lambda *_: self._toggle_home_song_like(state, popover))
        options.connect("notify::active", lambda *_: self._update_home_song_row(state))
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: self._set_home_song_hover(state, True))
        motion.connect("leave", lambda *_: self._set_home_song_hover(state, False))
        row.add_controller(motion)
        click = Gtk.GestureClick(button=1)
        click.connect("released", lambda *_: self._activate_home_song(state))
        row.add_controller(click)
        self._update_home_song_row(state)
        return row

    def _set_home_song_hover(self, state: dict, hovered: bool) -> None:
        state["hovered"] = hovered
        self._update_home_song_row(state)

    def _activate_home_song(self, state: dict) -> None:
        track = state["track"]
        active = (
            getattr(self, "current_item", None) is not None and self.current_item.id == track.id
        )
        if active and self._stream_ready:
            self._toggle_player()
            return
        source = state["source"]
        self.set_queue(source, source.index(track))

    def _toggle_home_song_like(self, state: dict, popover: Gtk.Popover) -> None:
        popover.popdown()
        state["liked"] = not state["liked"]
        self._update_home_song_row(state)
        self._toggle_song(state["track"], state["liked"])

    def _update_home_song_row(self, state: dict) -> None:
        track = state["track"]
        active = (
            getattr(self, "current_item", None) is not None and self.current_item.id == track.id
        )
        playing = active and self.player.playing
        hovered = state["hovered"]
        if active:
            state["row"].add_css_class("home-song-current")
            state["title"].add_css_class("current-track")
        else:
            state["row"].remove_css_class("home-song-current")
            state["title"].remove_css_class("current-track")
        state["play_icon"].set_from_icon_name(
            "media-playback-pause-symbolic" if playing else "media-playback-start-symbolic"
        )
        state["play_hint"].set_opacity(1.0 if hovered or active else 0.0)
        state["liked_icon"].set_opacity(1.0 if state["liked"] else 0.0)
        set_menu_action_content(
            state["like_button"],
            _("Remover das curtidas") if state["liked"] else _("Curtir música"),
            "starred-symbolic" if state["liked"] else "non-starred-symbolic",
        )
        show_options = hovered or state["options"].get_active()
        state["options"].set_opacity(1.0 if show_options else 0.0)
        state["options"].set_can_target(show_options)

    def _refresh_home_song_rows(self) -> None:
        for state in self.home_song_rows:
            self._update_home_song_row(state)

    @staticmethod
    def _home_card_hover(cover: Gtk.Widget, hint: Gtk.Widget, hovered: bool) -> None:
        cover.set_opacity(0.68 if hovered else 1.0)
        hint.set_opacity(1.0 if hovered else 0.0)

    def _home_shelf_header(
        self,
        title: str,
        scroll: Gtk.ScrolledWindow,
        on_play_all=None,
    ) -> Gtk.Widget:
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("home-shelf-header")
        heading = Gtk.Label(label=title, xalign=0, hexpand=True)
        heading.add_css_class("section-title")
        if on_play_all:
            header.add_css_class("home-song-shelf-header")
            heading.add_css_class("home-song-section-title")
        header.append(heading)
        if on_play_all:
            play_all = Gtk.Button(
                label=_("Tocar tudo"),
                tooltip_text=_("Reproduzir tudo em {title}").format(title=title),
            )
            play_all.add_css_class("pill")
            play_all.add_css_class("home-play-all")
            play_all.set_valign(Gtk.Align.CENTER)
            play_all.connect("clicked", lambda *_: on_play_all())
            header.append(play_all)
        previous = Gtk.Button(
            icon_name="go-previous-symbolic",
            tooltip_text=_("Voltar em {title}").format(title=title),
        )
        next_button = Gtk.Button(
            icon_name="go-next-symbolic",
            tooltip_text=_("Avançar em {title}").format(title=title),
        )
        for button in (previous, next_button):
            button.set_valign(Gtk.Align.CENTER)
            button.add_css_class("flat")
            button.add_css_class("circular")
            button.add_css_class("home-shelf-control")
            button.add_css_class("home-shelf-nav")
            header.append(button)
        previous.connect("clicked", lambda *_: self._scroll_home_shelf(scroll, -1))
        next_button.connect("clicked", lambda *_: self._scroll_home_shelf(scroll, 1))

        adjustment = scroll.get_hadjustment()

        def update_actions(*_args):
            value = adjustment.get_value()
            upper = adjustment.get_upper()
            page_size = adjustment.get_page_size()
            previous.set_sensitive(value > adjustment.get_lower() + 1)
            next_button.set_sensitive(value + page_size < upper - 1)

        adjustment.connect("changed", update_actions)
        adjustment.connect("value-changed", update_actions)
        GLib.idle_add(update_actions)
        return header

    @staticmethod
    def _scroll_home_shelf(scroll: Gtk.ScrolledWindow, direction: int) -> None:
        adjustment = scroll.get_hadjustment()
        step = max(360.0, adjustment.get_page_size() * 0.82)
        target = adjustment.get_value() + direction * step
        maximum = max(adjustment.get_lower(), adjustment.get_upper() - adjustment.get_page_size())
        adjustment.set_value(max(adjustment.get_lower(), min(target, maximum)))

    def _initial_sync(self):
        self.show_home()
        self.sync()
        self.sync_home()
        self.sync_explore()
        return False

    def _render(self) -> None:
        has_local_content = bool(
            self.storage.load_local_media()
            or self.storage.load_downloads()
            or self.storage.load_local_playlists()
        )
        if not self.storage.load_cookie() and not has_local_content:
            self.stack.add_named(self._welcome(), "welcome")
            self.stack.set_visible_child_name("welcome")
            return
        shell = page_shell("content", spacing=22)
        page, content = shell.scroll, shell.content
        hero = Adw.WrapBox(
            orientation=Gtk.Orientation.HORIZONTAL,
            child_spacing=18,
            line_spacing=12,
            natural_line_length=900,
            wrap_policy=Adw.WrapPolicy.NATURAL,
        )
        hero.add_css_class("hero")
        hero.add_css_class("app-page-header")
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        title = Gtk.Label(label=_("Biblioteca"), xalign=0)
        title.add_css_class("hero-title")
        copy.append(title)
        subtitle = Gtk.Label(label=self._library_description(), xalign=0)
        subtitle.add_css_class("hero-subtitle")
        copy.append(subtitle)
        hero.append(copy)
        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, valign=Gtk.Align.END)
        source_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.END
        )
        origin_keys = ["youtube", "uploads", "downloads", "local", "podcasts"]
        origin = Gtk.DropDown.new_from_strings(
            [
                _("YouTube Music"),
                _("Uploads"),
                _("Downloads"),
                _("Arquivos locais"),
                _("Podcasts"),
            ]
        )
        origin.set_selected(origin_keys.index(self.library_origin))
        origin.connect(
            "notify::selected",
            lambda dropdown, _pspec: self._set_library_origin(origin_keys[dropdown.get_selected()]),
        )
        source_row.append(origin)
        sorting = Gtk.DropDown.new_from_strings([_("Mais recentes"), _("A-Z")])
        sorting.set_selected(0 if self.library_sort == "recent" else 1)
        sorting.connect(
            "notify::selected",
            lambda dropdown, _pspec: self._set_library_sort(
                "recent" if dropdown.get_selected() == 0 else "title"
            ),
        )
        source_row.append(sorting)
        controls.append(source_row)
        filters = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2, valign=Gtk.Align.END)
        filters.add_css_class("segmented-control")
        group = None
        for key in ("albums", "artists", "songs", "playlists"):
            button = Gtk.ToggleButton(label=LABELS[key])
            if group is None:
                group = button
            else:
                button.set_group(group)
            button.set_active(key == self.library_filter)
            button.connect(
                "toggled",
                lambda selected, category=key: (
                    selected.get_active() and self._set_library_filter(category)
                ),
            )
            filters.append(button)
        controls.append(filters)
        hero.append(controls)
        content.append(hero)
        if self.library_origin == "local":
            actions = Adw.WrapBox(
                orientation=Gtk.Orientation.HORIZONTAL,
                child_spacing=8,
                line_spacing=8,
                natural_line_length=620,
                wrap_policy=Adw.WrapPolicy.NATURAL,
            )
            add_files = action_button(
                _("Adicionar arquivos"), "document-open-symbolic", role="secondary"
            )
            add_files.connect("clicked", lambda *_: self._add_local_files_dialog())
            actions.append(add_files)
            import_playlist = action_button(
                _("Importar playlist"), "document-open-symbolic", role="secondary"
            )
            import_playlist.connect("clicked", lambda *_: self._import_local_playlist_dialog())
            actions.append(import_playlist)
            create_playlist = action_button(
                _("Nova playlist local"), "list-add-symbolic", role="primary"
            )
            create_playlist.connect("clicked", lambda *_: self._create_local_playlist_dialog())
            actions.append(create_playlist)
            content.append(actions)
        items = self._library_items_for_view()
        if not self.sections and self.library_origin in ("youtube", "uploads", "podcasts"):
            status = Adw.StatusPage(
                icon_name="view-refresh-symbolic",
                title=_("Sincronizando…"),
                description=_("Buscando sua biblioteca no YouTube Music"),
            )
            content.append(status)
        elif not items:
            content.append(
                Adw.StatusPage(
                    icon_name="folder-music-symbolic",
                    title=_("Nada nesta visualização"),
                    description=_("Altere a origem ou adicione conteúdo à biblioteca."),
                )
            )
        else:
            if self.library_filter == "songs":
                content.append(self._song_section(self._library_description(), items, items))
            else:
                section_kind = (
                    "playlists" if self.library_filter == "playlists" else self.library_filter
                )
                content.append(self._section(section_kind, items, limit=len(items)))
        old = self.stack.get_child_by_name("library")
        if old:
            self.stack.remove(old)
        self.stack.add_named(page, "library")
        self.stack.set_visible_child_name("library")

    def _library_description(self) -> str:
        if self.library_origin != "youtube":
            return {
                "uploads": _("Músicas enviadas à sua conta do YouTube Music."),
                "downloads": _("Conteúdo disponível para reprodução offline."),
                "local": _("Arquivos e playlists armazenados neste computador."),
                "podcasts": _("Programas e episódios salvos na sua conta."),
            }[self.library_origin]
        return {
            "albums": _("Álbuns e EPs salvos na sua coleção."),
            "artists": _("Artistas que você acompanha."),
            "songs": _("Todas as músicas marcadas como favoritas."),
            "playlists": _("Playlists salvas na sua conta."),
        }[self.library_filter]

    def _library_items_for_view(self) -> list[LibraryItem]:
        if self.library_origin == "youtube":
            items = list(self.sections.get(self.library_filter, []))
        elif self.library_origin == "uploads":
            key = "uploaded-albums" if self.library_filter == "albums" else "uploads"
            items = (
                list(self.sections.get(key, []))
                if self.library_filter in ("albums", "songs")
                else []
            )
        elif self.library_origin == "downloads":
            items = (
                [
                    record.item
                    for record in self.storage.load_downloads()
                    if record.status == "completed"
                ]
                if self.library_filter == "songs"
                else []
            )
        elif self.library_origin == "local":
            if self.library_filter == "songs":
                items = self.storage.load_local_media()
            elif self.library_filter == "playlists":
                items = [
                    LibraryItem(
                        f"local-playlist:{playlist.id}",
                        playlist.title,
                        f"{len(playlist.items)} faixas",
                        kind="local-playlists",
                    )
                    for playlist in self.storage.load_local_playlists()
                ]
            else:
                items = []
        else:
            if self.library_filter == "songs":
                items = [
                    item
                    for item in self.sections.get("podcast-episodes", [])
                    if item.kind == "songs"
                ]
            elif self.library_filter == "playlists":
                items = list(self.sections.get("podcasts", []))
            else:
                items = []
        if self.library_sort == "title":
            items.sort(key=lambda item: item.title.casefold())
        return items

    def _set_library_filter(self, key: str) -> None:
        if key != self.library_filter:
            self.library_filter = key
            self._render()
            self.stack.set_visible_child_name("library")

    def _set_library_origin(self, key: str) -> None:
        if key != self.library_origin:
            self.library_origin = key
            if key in ("downloads", "local") and self.library_filter not in ("songs", "playlists"):
                self.library_filter = "songs"
            self._render()
            self.stack.set_visible_child_name("library")

    def _set_library_sort(self, key: str) -> None:
        if key != self.library_sort:
            self.library_sort = key
            self._render()
            self.stack.set_visible_child_name("library")

    def _welcome(self) -> Gtk.Widget:
        page = Adw.StatusPage(
            icon_name="audio-headphones-symbolic",
            title=_("Sua música, no seu desktop"),
            description=_(
                "Conecte sua sessão do YouTube Music para sincronizar playlists, músicas, álbuns e artistas."
            ),
        )
        page.add_css_class("welcome")
        button = action_button(_("Conectar ao YouTube Music"), role="accent")
        button.set_halign(Gtk.Align.CENTER)
        button.connect("clicked", lambda *_: self.login_dialog())
        page.set_child(button)
        return page

    def _section_header(self, title: str, on_all=None) -> Gtk.Widget:
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        heading = Gtk.Label(label=title, xalign=0, hexpand=True)
        heading.add_css_class("section-title")
        header.append(heading)
        if on_all:
            header.append(section_link(_("Mostrar tudo"), on_all))
        return header

    def _section(self, key: str, items: list[LibraryItem], limit: int = 8) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.append(self._section_header(LABELS[key], lambda: self.show_category(key)))
        flow = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            column_spacing=16,
            row_spacing=18,
            min_children_per_line=2,
            max_children_per_line=5,
            homogeneous=False,
        )
        for item in items[:limit]:
            flow.append(
                self._media_card_button(item, 140, lambda selected=item: self.open_item(selected))
            )
        box.append(flow)
        return box

    def _media_card_button(
        self,
        item: LibraryItem,
        size: int,
        activate,
    ) -> Gtk.Button:
        """One card interaction shared by Home, Library and artist shelves."""
        button = Gtk.Button()
        button.add_css_class("media-card-button")
        button.set_halign(Gtk.Align.START)
        button.set_valign(Gtk.Align.START)
        button.set_hexpand(False)
        button.set_size_request(size, -1)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        card.add_css_class("media-card")
        card.set_size_request(size, -1)

        cover = self._square_cover(item, size=size)
        cover.add_css_class("media-card-cover")
        # The labels below can be wider than the artwork.  Keep the overlay on
        # the artwork's exact allocation; otherwise GtkBox stretches it to the
        # card width and a mathematically centred action appears shifted right.
        cover_overlay = Gtk.Overlay(
            halign=Gtk.Align.START,
            valign=Gtk.Align.START,
            hexpand=False,
            vexpand=False,
        )
        cover_overlay.set_size_request(size, size)
        cover_overlay.set_hexpand_set(True)
        cover_overlay.set_vexpand_set(True)
        cover_overlay.set_child(cover)
        hint = Gtk.CenterBox(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        hint.set_size_request(48, 48)
        hint.set_hexpand(False)
        hint.set_vexpand(False)
        hint.add_css_class("home-cover-action")
        hint.add_css_class("media-card-action")
        hint.set_opacity(0)
        hint.set_can_target(False)
        icon_name = (
            "media-playback-start-symbolic"
            if item.kind in ("songs", "videos")
            else "go-next-symbolic"
        )
        action_icon = Gtk.Image.new_from_icon_name(icon_name)
        action_icon.set_pixel_size(26)
        hint.set_center_widget(action_icon)
        cover_overlay.add_overlay(hint)
        card.append(cover_overlay)

        width_chars = 20 if size >= 160 else 17
        title = Gtk.Label(
            label=item.title,
            xalign=0,
            ellipsize=3,
            width_chars=width_chars,
            max_width_chars=width_chars,
        )
        title.add_css_class("card-title")
        card.append(title)
        if item.subtitle:
            subtitle = Gtk.Label(
                label=item.subtitle,
                xalign=0,
                ellipsize=3,
                width_chars=width_chars,
                max_width_chars=width_chars,
            )
            subtitle.add_css_class("card-subtitle")
            card.append(subtitle)
        button.set_child(card)
        hover = Gtk.EventControllerMotion()
        hover.connect("enter", lambda *_args: self._home_card_hover(cover, hint, True))
        hover.connect("leave", lambda *_args: self._home_card_hover(cover, hint, False))
        button.add_controller(hover)
        button.connect("clicked", lambda *_: activate())
        return button

    def _square_cover(self, item: LibraryItem, size: int = 140, fixed: bool = False) -> Gtk.Widget:
        """Create conventional 1:1 music artwork, circular only for artists."""
        # Detail artwork has an exact desktop size.  A plain overlay keeps it
        # from reserving the hero's full cross-axis size, while cards continue
        # to use AspectFrame so their 1:1 ratio survives responsive layouts.
        frame = Gtk.Overlay() if fixed else Gtk.AspectFrame(ratio=1.0, obey_child=False)
        frame.set_size_request(size, size)
        frame.set_halign(Gtk.Align.START)
        frame.set_valign(Gtk.Align.START)
        if fixed:
            frame.set_hexpand(False)
            frame.set_hexpand_set(True)
            frame.set_vexpand(False)
            frame.set_vexpand_set(True)
        frame.set_overflow(Gtk.Overflow.HIDDEN)
        frame.add_css_class("artist-cover" if item.kind == "artists" else "square-cover")
        overlay = Gtk.Overlay(hexpand=True, vexpand=True)
        placeholder = Gtk.Image.new_from_icon_name(ICONS.get(item.kind, "audio-x-generic-symbolic"))
        placeholder.set_pixel_size(42)
        placeholder.add_css_class("cover-placeholder")
        overlay.set_child(placeholder)
        if item.thumbnail:
            picture = Gtk.Picture(
                content_fit=Gtk.ContentFit.COVER, can_shrink=True, hexpand=True, vexpand=True
            )
            picture.add_css_class("cover-art")
            overlay.add_overlay(picture)
            self._load_artwork(item.thumbnail, picture, size=max(256, size * 2))
        frame.set_child(overlay)
        return frame

    def _song_section(
        self, title: str, items: list[LibraryItem], source: list[LibraryItem]
    ) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.append(self._section_header(title, lambda: self.show_category("songs")))
        listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        listing.add_css_class("boxed-list")
        for item in items:
            row = Adw.ActionRow()
            row.add_css_class("media-row")
            row.set_use_markup(False)
            row.set_title(item.title)
            row.set_subtitle(item.subtitle)
            row.add_css_class("song-row")
            row.set_activatable(True)
            thumb = Gtk.Picture(content_fit=Gtk.ContentFit.COVER)
            thumb.set_size_request(52, 52)
            thumb.set_can_shrink(True)
            thumb.set_overflow(Gtk.Overflow.HIDDEN)
            thumb.add_css_class("row-cover")
            if item.thumbnail:
                self._load_artwork(item.thumbnail, thumb, size=128)
            row.add_prefix(thumb)
            if self.library_origin == "local":
                remove = icon_button(
                    "user-trash-symbolic",
                    _("Remover da biblioteca local"),
                    size="sm",
                    destructive=True,
                )
                remove.connect(
                    "clicked",
                    lambda _button, selected=item: GLib.idle_add(
                        self._remove_local_library_item, selected
                    ),
                )
                row.add_suffix(remove)
            elif self.library_origin == "downloads":
                remove = icon_button(
                    "user-trash-symbolic", _("Excluir download"), size="sm", destructive=True
                )
                remove.connect(
                    "clicked", lambda _button, selected=item: self.downloads.remove(selected.id)
                )
                row.add_suffix(remove)
            elif self.library_origin == "youtube":
                remove = icon_button(LIKED_ICON, _("Remover das músicas marcadas"), size="sm")
                remove.connect(
                    "clicked", lambda _button, selected=item: self._toggle_song(selected, False)
                )
                row.add_suffix(remove)
            row.add_suffix(Gtk.Image.new_from_icon_name("media-playback-start-symbolic"))
            row.connect(
                "activated",
                lambda _row, selected=item, queue=source: self.set_queue(
                    queue, queue.index(selected)
                ),
            )
            listing.append(row)
        box.append(listing)
        return box

    def _remove_local_library_item(self, item: LibraryItem) -> None:
        self.storage.remove_local_media(item.id)
        self._render()

    def show_category(self, key: str) -> None:
        """Select a YouTube library category without leaving the library shell.

        Older builds created a separate ``category`` stack page here.  Besides
        duplicating the grid, that page dropped the origin, sorting and category
        controls, leaving no way to move from Artists to Albums without using
        the sidebar.  A category is presentation state of the library, not a
        navigation destination of its own.
        """
        if key not in LABELS:
            return
        self.library_origin = "youtube"
        self.library_filter = key
        self.show_library()
        self._set_active_nav(key if key in self.nav_buttons else "library")

    @staticmethod
    def _sized_artwork_url(url: str, size: int | None = None) -> str:
        """Request a sharper Google/YouTube thumbnail without changing its asset."""
        if not size or not any(
            domain in url
            for domain in (
                "googleusercontent.com",
                "ggpht.com",
            )
        ):
            return url
        size = max(64, min(1280, int(size)))
        result = re.sub(r"([=-])w\d+(?=-|$)", rf"\1w{size}", url)
        result = re.sub(r"([=-])h\d+(?=-|$)", rf"\1h{size}", result)
        result = re.sub(r"=s\d+(?=-|$)", f"=s{size}", result)
        return result

    def _set_artwork_if_current(
        self,
        picture: Gtk.Picture,
        target: Path,
        request_key: str,
    ) -> bool:
        if self._artwork_requests.get(id(picture)) == request_key and target.exists():
            picture.set_filename(str(target))
        return GLib.SOURCE_REMOVE

    def _load_artwork(
        self,
        url: str,
        picture: Gtk.Picture,
        *,
        size: int | None = None,
    ) -> None:
        request_url = self._sized_artwork_url(url, size)
        target = self.storage.artwork_path(request_url)
        request_key = str(target)
        self._artwork_requests[id(picture)] = request_key
        if target.exists():
            picture.set_filename(str(target))
            return

        def worker():
            try:
                request = urllib.request.Request(request_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(request, timeout=15) as response:
                    data = response.read(12 * 1024 * 1024)
                target.write_bytes(data)
                GLib.idle_add(self._set_artwork_if_current, picture, target, request_key)
            except Exception:
                LOGGER.debug("Não foi possível carregar a arte de %s", request_url, exc_info=True)

        threading.Thread(target=worker, daemon=True).start()

    def open_item(self, item: LibraryItem) -> None:
        if item.kind in ("songs", "videos"):
            songs = self.sections.get("songs", [])
            if item in songs:
                self.set_queue(songs, songs.index(item))
            else:
                self.set_queue([item], 0)
            return
        if item.kind == "local-playlists":
            try:
                playlist_id = int(item.id.split(":", 1)[1])
            except (IndexError, ValueError):
                return
            playlist = self.storage.get_local_playlist(playlist_id)
            if playlist:
                self._show_local_playlist(playlist)
            return
        if item.kind == "artists":
            self._open_artist(item)
            return
        self.back.set_visible(True)
        self.detail_track_rows = []
        status = Adw.StatusPage(
            icon_name="view-refresh-symbolic",
            title=_("Carregando…"),
            description=_("Buscando {title}").format(title=item.title),
        )
        old = self.stack.get_child_by_name("detail")
        if old:
            self.stack.remove(old)
        self.stack.add_named(status, "detail")
        self.stack.set_visible_child_name("detail")

        def worker():
            try:
                tracks = self.youtube.browse(item)
                GLib.idle_add(self._show_detail, item, tracks, None)
            except Exception as exc:
                GLib.idle_add(self._show_detail, item, None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _show_local_playlist(self, playlist: LocalPlaylist) -> None:
        self.main_view = "local-playlist"
        self.back.set_visible(True)
        old = self.stack.get_child_by_name("local-playlist")
        if old:
            self.stack.remove(old)
        shell = page_shell("reading", spacing=22)
        scroll, content = shell.scroll, shell.content
        play = action_button(_("Reproduzir"), "media-playback-start-symbolic", role="primary")
        play.set_sensitive(bool(playlist.items))
        play.connect("clicked", lambda *_: playlist.items and self.set_queue(playlist.items, 0))
        add = action_button(_("Adicionar arquivos"), "list-add-symbolic", role="secondary")
        add.connect("clicked", lambda *_: self._add_local_files_dialog(playlist))
        export = action_button(_("Exportar"), "document-save-symbolic", role="secondary")
        export.connect("clicked", lambda *_: self._export_local_playlist_dialog(playlist))
        rename = icon_button("document-edit-symbolic", _("Renomear playlist"), size="md")
        rename.connect("clicked", lambda *_: self._rename_local_playlist_dialog(playlist))
        delete = icon_button(
            "user-trash-symbolic", _("Excluir playlist"), size="md", destructive=True
        )
        delete.connect("clicked", lambda *_: self._confirm_delete_local_playlist(playlist))
        track_count = ngettext("{count} faixa", "{count} faixas", len(playlist.items)).format(
            count=len(playlist.items)
        )
        content.append(
            page_header(
                playlist.title,
                _("Playlist local · {tracks}").format(tracks=track_count),
                actions=(play, add, export, rename, delete),
            )
        )
        group = Adw.PreferencesGroup(title=track_count)
        for position, item in enumerate(playlist.items):
            row = Adw.ActionRow()
            row.add_css_class("media-row")
            row.set_use_markup(False)
            row.set_title(item.title)
            row.set_subtitle(item.subtitle)
            row.set_activatable(True)
            row.connect(
                "activated",
                lambda _row, selected=position: self.set_queue(playlist.items, selected),
            )
            controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            up = icon_button("go-up-symbolic", _("Mover para cima"), size="sm")
            down = icon_button("go-down-symbolic", _("Mover para baixo"), size="sm")
            remove = icon_button("list-remove-symbolic", _("Remover"), size="sm")
            for button in (up, down, remove):
                controls.append(button)
            up.set_sensitive(position > 0)
            down.set_sensitive(position + 1 < len(playlist.items))
            up.connect(
                "clicked",
                lambda *_args, selected=position: GLib.idle_add(
                    self._move_local_playlist_item, playlist, selected, -1
                ),
            )
            down.connect(
                "clicked",
                lambda *_args, selected=position: GLib.idle_add(
                    self._move_local_playlist_item, playlist, selected, 1
                ),
            )
            remove.connect(
                "clicked",
                lambda *_args, selected=position: GLib.idle_add(
                    self._remove_local_playlist_item, playlist, selected
                ),
            )
            row.add_suffix(controls)
            group.add(row)
        content.append(group)
        self.stack.add_named(scroll, "local-playlist")
        self.stack.set_visible_child_name("local-playlist")

    def _move_local_playlist_item(
        self, playlist: LocalPlaylist, position: int, direction: int
    ) -> None:
        target = position + direction
        if target < 0 or target >= len(playlist.items):
            return
        playlist.items[position], playlist.items[target] = (
            playlist.items[target],
            playlist.items[position],
        )
        self.storage.save_local_playlist(playlist)
        self._show_local_playlist(playlist)

    def _remove_local_playlist_item(self, playlist: LocalPlaylist, position: int) -> None:
        if 0 <= position < len(playlist.items):
            playlist.items.pop(position)
            self.storage.save_local_playlist(playlist)
            self._show_local_playlist(playlist)

    def _delete_local_playlist(self, playlist: LocalPlaylist) -> None:
        if playlist.id is not None:
            self.storage.delete_local_playlist(playlist.id)
        self.library_origin = "local"
        self.library_filter = "playlists"
        self.show_library()

    def _confirm_delete_local_playlist(self, playlist: LocalPlaylist) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Excluir playlist local?"),
            body=_(
                "“{title}” será removida deste dispositivo. Os arquivos de áudio serão preservados."
            ).format(title=playlist.title),
        )
        dialog.add_response("cancel", _("Cancelar"))
        dialog.add_response("delete", _("Excluir"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect(
            "response",
            lambda _dialog, response: (
                response == "delete" and self._delete_local_playlist(playlist)
            ),
        )
        dialog.present(self)

    def _rename_local_playlist_dialog(self, playlist: LocalPlaylist) -> None:
        dialog = Adw.AlertDialog(heading=_("Renomear playlist local"))
        entry = Gtk.Entry(text=playlist.title)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", _("Cancelar"))
        dialog.add_response("rename", _("Renomear"))
        dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)

        def response(_dialog, name: str) -> None:
            title = entry.get_text().strip()
            if name == "rename" and title:
                playlist.title = title
                self.storage.save_local_playlist(playlist)
                self._show_local_playlist(playlist)

        dialog.connect("response", response)
        dialog.present(self)

    def _open_artist(self, item: LibraryItem) -> None:
        self.main_view = "artist"
        self._artist_current_item = item
        self.back.set_visible(True)
        self._set_active_nav("artists")
        status = Adw.StatusPage(
            icon_name="view-refresh-symbolic",
            title=_("Carregando {title}…").format(title=item.title),
            description=_("Buscando a página completa do artista"),
        )
        old = self.stack.get_child_by_name("artist")
        if old:
            self.stack.remove(old)
        self.stack.add_named(status, "artist")
        self.stack.set_visible_child_name("artist")

        def worker() -> None:
            try:
                page = self.youtube.artist(item.id)
                GLib.idle_add(self._show_artist, item, page, None)
            except Exception as exc:
                GLib.idle_add(self._show_artist, item, None, str(exc))

        threading.Thread(target=worker, daemon=True, name="artist-page").start()

    def _show_artist(
        self,
        item: LibraryItem,
        artist: ArtistPage | None,
        error: str | None,
    ) -> bool:
        old = self.stack.get_child_by_name("artist")
        if old:
            self.stack.remove(old)
        if error or artist is None:
            page: Gtk.Widget = Adw.StatusPage(
                icon_name="dialog-error-symbolic",
                title=_("Não foi possível abrir o artista"),
                description=error or "Resposta vazia do YouTube Music",
            )
        else:
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            surface = Gtk.Overlay()
            surface.add_css_class("artist-surface")
            base = Gtk.Box(vexpand=True)
            surface.set_child(base)
            if artist.thumbnail:
                backdrop = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
                backdrop.set_size_request(-1, 430)
                backdrop.set_valign(Gtk.Align.START)
                backdrop.set_opacity(0.18)
                backdrop.add_css_class("artist-backdrop")
                self._load_artwork(artist.thumbnail, backdrop, size=1280)
                surface.add_overlay(backdrop)
            shade = Gtk.Box(height_request=430, valign=Gtk.Align.START, hexpand=True)
            shade.add_css_class("artist-backdrop-shade")
            shade.set_can_target(False)
            surface.add_overlay(shade)

            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=30)
            content.add_css_class("artist-page")
            content.add_css_class("app-page")
            content.add_css_class("app-page-content")
            hero = Adw.WrapBox(
                orientation=Gtk.Orientation.HORIZONTAL,
                child_spacing=34,
                line_spacing=24,
                natural_line_length=940,
                wrap_policy=Adw.WrapPolicy.NATURAL,
                valign=Gtk.Align.END,
            )
            hero.add_css_class("app-page-header")
            portrait_item = LibraryItem(
                item.id, artist.title, thumbnail=artist.thumbnail, kind="artists"
            )
            portrait = self._square_cover(portrait_item, size=230, fixed=True)
            portrait.add_css_class("artist-portrait")
            hero.append(portrait)
            copy = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL, spacing=10, hexpand=True, valign=Gtk.Align.END
            )
            eyebrow = Gtk.Label(label=_("ARTISTA"), xalign=0)
            eyebrow.add_css_class("detail-eyebrow")
            copy.append(eyebrow)
            title = Gtk.Label(label=artist.title, xalign=0, wrap=True)
            title.add_css_class("artist-title")
            copy.append(title)
            if artist.subscribers:
                listeners = Gtk.Label(label=artist.subscribers, xalign=0)
                listeners.add_css_class("artist-listeners")
                copy.append(listeners)
            if artist.description:
                description = Gtk.Label(
                    label=artist.description, xalign=0, wrap=True, lines=3, ellipsize=3
                )
                description.add_css_class("artist-description")
                copy.append(description)
            actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            play = action_button(_("Reproduzir"), "media-playback-start-symbolic", role="primary")
            play.set_sensitive(bool(artist.songs))
            play.connect("clicked", lambda *_: artist.songs and self.set_queue(artist.songs, 0))
            actions.append(play)
            radio = action_button(
                _("Rádio"), "media-playlist-consecutive-symbolic", role="secondary"
            )
            radio.set_sensitive(bool(artist.songs))
            radio.connect("clicked", lambda *_: artist.songs and self.set_queue(artist.songs, 0))
            actions.append(radio)
            subscribed = {"value": artist.subscribed}
            subscribe = action_button(
                label=_("Inscrito") if artist.subscribed else "Inscrever-se",
                icon_name="object-select-symbolic" if artist.subscribed else "contact-new-symbolic",
                role="accent" if artist.subscribed else "secondary",
            )
            subscribe.connect(
                "clicked",
                lambda *_: self._toggle_artist_page_subscription(item, subscribe, subscribed),
            )
            actions.append(subscribe)
            copy.append(actions)
            hero.append(copy)
            content.append(hero)
            for section in artist.sections or []:
                content.append(self._artist_section_widget(section))
            clamp = Adw.Clamp(maximum_size=1280, tightening_threshold=1050)
            clamp.set_child(content)
            surface.add_overlay(clamp)
            surface.set_measure_overlay(clamp, True)
            scroll.set_child(surface)
            page = scroll
        self.stack.add_named(page, "artist")
        self.stack.set_visible_child_name("artist")
        return False

    def _toggle_artist_page_subscription(
        self, item: LibraryItem, button: Gtk.Button, state: dict
    ) -> None:
        subscribed = not state["value"]

        def completed(_result) -> None:
            state["value"] = subscribed
            button.set_label(_("Inscrito") if subscribed else _("Inscrever-se"))
            button.set_icon_name("object-select-symbolic" if subscribed else "contact-new-symbolic")
            set_action_role(button, "accent" if subscribed else "secondary")
            self.sync()

        self._mutate(
            "subscribe-artist" if subscribed else "unsubscribe-artist",
            item.id,
            lambda client: client.subscribe_artist(item.id, subscribed),
            _("Inscrição realizada") if subscribed else _("Inscrição cancelada"),
            completed,
        )

    def _artist_section_widget(self, section: ArtistSection) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        if section.browse_id:
            show_all = section_link(_("Mostrar tudo"), lambda: self._open_artist_section(section))
            show_all.set_halign(Gtk.Align.END)
            box.append(show_all)
        box.append(self._home_section(section.title, section.items, limit=12))
        return box

    def _open_artist_section(self, section: ArtistSection) -> None:
        self.main_view = "artist-section"
        status = Adw.StatusPage(
            icon_name="view-refresh-symbolic",
            title=_("Carregando {title}…").format(title=section.title),
        )
        old = self.stack.get_child_by_name("artist-section")
        if old:
            self.stack.remove(old)
        self.stack.add_named(status, "artist-section")
        self.stack.set_visible_child_name("artist-section")

        def worker() -> None:
            try:
                items = self.youtube.artist_section(section)
                GLib.idle_add(self._show_artist_section, section, items, None)
            except Exception as exc:
                GLib.idle_add(self._show_artist_section, section, None, str(exc))

        threading.Thread(target=worker, daemon=True, name="artist-section").start()

    def _show_artist_section(
        self, section: ArtistSection, items: list[LibraryItem] | None, error: str | None
    ) -> bool:
        old = self.stack.get_child_by_name("artist-section")
        if old:
            self.stack.remove(old)
        if error:
            page: Gtk.Widget = Adw.StatusPage(
                icon_name="dialog-error-symbolic",
                title=_("Não foi possível carregar"),
                description=error,
            )
        else:
            shell = page_shell("content", spacing=20)
            scroll, content = shell.scroll, shell.content
            content.append(page_header(section.title))
            content.append(
                self._home_section(section.title, items or [], limit=max(24, len(items or [])))
            )
            page = scroll
        self.stack.add_named(page, "artist-section")
        self.stack.set_visible_child_name("artist-section")
        return False

    def _open_home_item(self, item: LibraryItem, section_items: list[LibraryItem]) -> None:
        if item.kind != "songs":
            self.open_item(item)
            return
        playable = [candidate for candidate in section_items if candidate.kind == "songs"]
        self.set_queue(playable, playable.index(item) if item in playable else 0)

    def _show_detail(self, item: LibraryItem, tracks: list[LibraryItem] | None, error: str | None):
        old = self.stack.get_child_by_name("detail")
        if old:
            self.stack.remove(old)
        self.detail_track_rows = []
        if error:
            page = Adw.StatusPage(
                icon_name="dialog-error-symbolic",
                title=_("Não foi possível abrir"),
                description=error,
            )
        else:
            tracks = tracks or []
            for track in tracks:
                if not track.thumbnail and item.thumbnail:
                    track.thumbnail = item.thumbnail
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            surface = Gtk.Overlay(hexpand=True)
            surface.add_css_class("detail-surface")

            background = Gtk.Box(hexpand=True, vexpand=True)
            background.add_css_class("detail-background")
            surface.set_child(background)
            if item.thumbnail:
                backdrop = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
                backdrop.set_size_request(-1, 390)
                backdrop.set_valign(Gtk.Align.START)
                backdrop.set_opacity(0.13)
                backdrop.set_can_target(False)
                backdrop.add_css_class("detail-backdrop")
                self._load_artwork(item.thumbnail, backdrop, size=1280)
                surface.add_overlay(backdrop)
            shade = Gtk.Box(height_request=390, valign=Gtk.Align.START, hexpand=True)
            shade.set_can_target(False)
            shade.add_css_class("detail-backdrop-shade")
            surface.add_overlay(shade)

            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=28, hexpand=True)
            content.add_css_class("detail-page")
            content.add_css_class("app-page")
            content.add_css_class("app-page-content")
            content.set_valign(Gtk.Align.START)

            # Keep a stable editorial gutter instead of letting short titles
            # drift right according to their natural width.
            hero = Adw.WrapBox(
                orientation=Gtk.Orientation.HORIZONTAL,
                child_spacing=76,
                line_spacing=24,
                natural_line_length=920,
                wrap_policy=Adw.WrapPolicy.NATURAL,
            )
            hero.add_css_class("detail-hero")
            hero.add_css_class("app-page-header")
            art = self._square_cover(item, size=240, fixed=True)
            art.add_css_class("detail-hero-cover")
            hero.append(art)

            copy = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL,
                spacing=9,
                valign=Gtk.Align.END,
                hexpand=True,
            )
            copy.add_css_class("detail-hero-copy")
            kind_name = {
                "albums": _("ÁLBUM"),
                "playlists": _("PLAYLIST"),
                "artists": _("ARTISTA"),
            }.get(item.kind, _("COLEÇÃO"))
            eyebrow = Gtk.Label(label=kind_name, xalign=0)
            eyebrow.add_css_class("detail-eyebrow")
            copy.append(eyebrow)
            title = Gtk.Label(label=item.title, xalign=0, wrap=True)
            title.set_natural_wrap_mode(Gtk.NaturalWrapMode.WORD)
            title.add_css_class("detail-title")
            copy.append(title)
            copy.append(self._detail_metadata(item, tracks))
            copy.append(self._detail_actions(item, tracks))
            hero.append(copy)
            content.append(hero)

            tracklist = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
            tracklist.add_css_class("detail-tracklist")
            tracklist.append(self._detail_track_header())
            for index, track in enumerate(tracks, 1):
                tracklist.append(self._detail_track_row(item, tracks, track, index))
            if not tracks:
                empty = Adw.StatusPage(
                    icon_name="audio-x-generic-symbolic",
                    title=_("Nenhuma faixa"),
                    description=_("Esta coleção ainda não possui músicas disponíveis."),
                )
                empty.set_size_request(-1, 220)
                tracklist.append(empty)
            content.append(tracklist)

            clamp = Adw.Clamp(maximum_size=1120, tightening_threshold=900)
            clamp.set_hexpand(True)
            clamp.set_child(content)
            surface.add_overlay(clamp)
            surface.set_measure_overlay(clamp, True)
            scroll.set_child(surface)
            page = scroll
        self.stack.add_named(page, "detail")
        self.stack.set_visible_child_name("detail")
        self._refresh_detail_track_states()
        return False

    @staticmethod
    def _duration_text(item: LibraryItem) -> str:
        match = re.search(r"(?<!\d)(?:(?:\d+):)?[0-5]?\d:[0-5]\d(?!\d)", item.subtitle or "")
        return match.group(0) if match else "—"

    @classmethod
    def _duration_seconds(cls, item: LibraryItem) -> int:
        value = cls._duration_text(item)
        if value == "—":
            return 0
        parts = [int(part) for part in value.split(":")]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        return parts[0] * 60 + parts[1]

    @staticmethod
    def _duration_summary(seconds: int) -> str:
        if seconds <= 0:
            return ""
        hours, remainder = divmod(seconds, 3600)
        minutes = remainder // 60
        if hours:
            return f"{hours} {'hora' if hours == 1 else 'horas'} {minutes} min"
        return f"{minutes} min"

    def _detail_metadata(self, item: LibraryItem, tracks: list[LibraryItem]) -> Gtk.Widget:
        raw_parts = [
            part.strip()
            for part in re.split(r"\s*[\u2022·]\s*", item.subtitle or "")
            if part.strip()
        ]
        ignored = {"álbum", "album", "playlist", "playlist automática"}
        parts = [
            part
            for part in raw_parts
            if part.casefold() not in ignored
            and not re.search(r"\b(?:itens?|músicas?)\b", part, re.IGNORECASE)
        ]
        creator = parts[0] if parts else (item.subtitle or "YouTube Music")
        extras = parts[1:]
        initials = "".join(word[0] for word in creator.split()[:2] if word)[:2].upper() or "YT"

        meta = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        meta.add_css_class("detail-metadata")
        avatar = Gtk.Label(label=initials, width_chars=2)
        avatar.add_css_class("detail-avatar")
        meta.append(avatar)
        creator_label = Gtk.Label(label=creator, ellipsize=3)
        creator_label.add_css_class("detail-creator")
        meta.append(creator_label)

        count = len(tracks)
        summary = ngettext("{count} música", "{count} músicas", count).format(count=count)
        duration = self._duration_summary(sum(self._duration_seconds(track) for track in tracks))
        for value in [*extras, summary, duration]:
            if not value:
                continue
            dot = Gtk.Label(label=_("•"))
            dot.add_css_class("detail-meta-muted")
            meta.append(dot)
            label = Gtk.Label(label=value, ellipsize=3)
            label.add_css_class("detail-meta-muted")
            meta.append(label)
        return meta

    def _detail_actions(self, item: LibraryItem, tracks: list[LibraryItem]) -> Gtk.Widget:
        actions = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            column_spacing=10,
            row_spacing=8,
            min_children_per_line=1,
            max_children_per_line=5,
            homogeneous=False,
            halign=Gtk.Align.START,
        )
        actions.add_css_class("detail-actions")

        play = media_play_button(_("Reproduzir"), size="lg")
        play.set_sensitive(bool(tracks))
        play.connect("clicked", lambda *_: tracks and self.set_queue(tracks, 0))
        actions.append(play)

        shuffle = icon_button(
            "media-playlist-shuffle-symbolic", _("Reproduzir em ordem aleatória"), size="lg"
        )
        shuffle.set_sensitive(bool(tracks))
        shuffle.connect("clicked", lambda *_: self._play_shuffled(tracks))
        actions.append(shuffle)

        saved = any(saved_item.id == item.id for saved_item in self.sections.get(item.kind, []))
        save_state = {"saved": saved}
        save = icon_button(
            "object-select-symbolic" if saved else "bookmark-new-symbolic",
            _("Salvo na biblioteca") if saved else _("Salvar na biblioteca"),
            size="lg",
        )
        set_icon_selected(save, saved)
        save.connect(
            "clicked",
            lambda *_: self._toggle_detail_collection(item, tracks, save, save_state),
        )
        actions.append(save)

        download = icon_button("folder-download-symbolic", _("Fazer download"), size="lg")
        download.set_sensitive(bool(tracks))
        download.connect("clicked", lambda *_: self._download_items(tracks))
        actions.append(download)

        more = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text=_("Mais opções"))
        style_icon_button(more, "lg")
        menu = Gtk.Popover()
        menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        menu_box.add_css_class("detail-menu")
        if item.kind == "playlists":
            rename = menu_action_button(_("Renomear playlist"), "document-edit-symbolic")
            rename.connect(
                "clicked", lambda *_: (menu.popdown(), self.rename_playlist_dialog(item))
            )
            menu_box.append(rename)
            delete = menu_action_button(
                _("Excluir playlist"), "user-trash-symbolic", destructive=True
            )
            delete.connect(
                "clicked", lambda *_: (menu.popdown(), self.delete_playlist_dialog(item))
            )
            menu_box.append(delete)
        elif item.kind == "artists":
            unsubscribe = menu_action_button(_("Cancelar inscrição"), "contact-new-symbolic")
            unsubscribe.connect(
                "clicked", lambda *_: (menu.popdown(), self._toggle_artist(item, False))
            )
            menu_box.append(unsubscribe)
        else:
            info = Gtk.Label(label=_("Mais ações para álbuns em breve"), xalign=0)
            info.add_css_class("detail-menu-note")
            menu_box.append(info)
        menu.set_child(menu_box)
        more.set_popover(menu)
        actions.append(more)
        return actions

    def _toggle_detail_collection(
        self,
        item: LibraryItem,
        tracks: list[LibraryItem],
        button: Gtk.Button,
        state: dict,
    ) -> None:
        playlist_id = item.playlist_id or next(
            (track.playlist_id for track in tracks if track.playlist_id), None
        )
        if item.kind == "playlists":
            playlist_id = playlist_id or item.id
        if not playlist_id:
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=_("O YouTube Music não informou como salvar este item"),
                    timeout=4,
                )
            )
            return

        save = not state["saved"]
        message = _("Adicionado à biblioteca") if save else _("Removido da biblioteca")

        def completed(_result) -> None:
            state["saved"] = save
            button.set_icon_name("object-select-symbolic" if save else "bookmark-new-symbolic")
            button.set_tooltip_text(_("Salvo na biblioteca") if save else _("Salvar na biblioteca"))
            set_icon_selected(button, save)
            self.sync()

        self._mutate(
            "like-collection" if save else "unlike-collection",
            playlist_id,
            lambda client: client.like_playlist(playlist_id, save),
            message,
            completed,
        )

    def _play_shuffled(self, tracks: list[LibraryItem]) -> None:
        if not tracks:
            return
        shuffled = list(tracks)
        random.shuffle(shuffled)
        self.set_queue(shuffled, 0)

    def _download_items(self, tracks: list[LibraryItem]) -> None:
        playable = [
            track
            for track in tracks
            if track.kind in ("songs", "videos") and not track.id.startswith("local:")
        ]
        if not playable:
            self.toast_overlay.add_toast(
                Adw.Toast(title=_("Nenhuma faixa disponível para download"))
            )
            return
        for track in playable:
            self.downloads.start(track)
        self.toast_overlay.add_toast(
            Adw.Toast(
                title=ngettext(
                    "{count} download iniciado",
                    "{count} downloads adicionados à fila",
                    len(playable),
                ).format(count=len(playable))
            )
        )

    @staticmethod
    def _detail_track_header() -> Gtk.Widget:
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.add_css_class("detail-track-header")
        number = Gtk.Label(label=_("#"), width_chars=3, xalign=1)
        header.append(number)
        title = Gtk.Label(label=_("TÍTULO"), xalign=0, hexpand=True)
        header.append(title)
        heart_space = Gtk.Box(width_request=36)
        header.append(heart_space)
        clock = Gtk.Image.new_from_icon_name("preferences-system-time-symbolic")
        clock.set_size_request(52, -1)
        header.append(clock)
        menu_space = Gtk.Box(width_request=36)
        header.append(menu_space)
        return header

    def _detail_track_row(
        self,
        collection: LibraryItem,
        source: list[LibraryItem],
        track: LibraryItem,
        index: int,
    ) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add_css_class("detail-track-row")
        row.add_css_class("media-row")
        row.add_css_class("media-row-detailed")
        row.set_cursor_from_name("pointer")

        leading = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        leading.set_size_request(36, 36)
        number = Gtk.Label(label=str(index), width_chars=3, xalign=1)
        number.add_css_class("detail-track-number")
        leading.add_named(number, "number")
        active_icon = Gtk.Image.new_from_icon_name("audio-volume-high-symbolic")
        active_icon.add_css_class("detail-track-accent")
        leading.add_named(active_icon, "active")
        play = Gtk.Button(
            icon_name="media-playback-start-symbolic",
            tooltip_text=_("Reproduzir {title}").format(title=track.title),
        )
        style_icon_button(play, "sm")
        play.add_css_class("detail-track-play")
        leading.add_named(play, "play")
        row.append(leading)

        title = Gtk.Label(label=track.title, xalign=0, ellipsize=3, hexpand=True)
        title.add_css_class("detail-track-title")
        row.append(title)

        liked_ids = {song.id for song in self.sections.get("songs", [])}
        liked = track.id in liked_ids
        like = Gtk.Button(
            icon_name="starred-symbolic" if liked else "non-starred-symbolic",
            tooltip_text=_("Remover das músicas curtidas") if liked else _("Curtir música"),
        )
        style_icon_button(like, "sm")
        like.add_css_class("detail-track-action")
        if liked:
            like.add_css_class("detail-track-accent")
        row.append(like)

        duration = Gtk.Label(label=self._duration_text(track), width_chars=6, xalign=1)
        duration.add_css_class("detail-track-duration")
        row.append(duration)

        options = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text=_("Opções da faixa"))
        style_icon_button(options, "sm")
        options.add_css_class("detail-track-action")
        popover = Gtk.Popover()
        option_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        option_box.add_css_class("detail-menu")
        add = menu_action_button(_("Adicionar à playlist"), "list-add-symbolic")
        add.connect("clicked", lambda *_: (popover.popdown(), self.add_to_playlist_dialog(track)))
        option_box.append(add)
        download = menu_action_button(_("Baixar"), "folder-download-symbolic")
        download.connect("clicked", lambda *_: (popover.popdown(), self._download_items([track])))
        option_box.append(download)
        if collection.kind == "playlists" and track.set_video_id:
            remove = menu_action_button(_("Remover desta playlist"), "list-remove-symbolic")
            remove.connect(
                "clicked", lambda *_: (popover.popdown(), self._remove_track(collection, track))
            )
            option_box.append(remove)
        popover.set_child(option_box)
        options.set_popover(popover)
        row.append(options)

        state = {
            "row": row,
            "track": track,
            "source": source,
            "leading": leading,
            "play": play,
            "title": title,
            "like": like,
            "liked": liked,
            "duration": duration,
            "options": options,
            "hovered": False,
        }
        self.detail_track_rows.append(state)

        play.connect("clicked", lambda *_: self._activate_detail_track(state))
        like.connect("clicked", lambda *_: self._toggle_detail_track_like(state))
        options.connect("notify::active", lambda *_: self._update_detail_track_row(state))
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: self._set_detail_track_hover(state, True))
        motion.connect("leave", lambda *_: self._set_detail_track_hover(state, False))
        row.add_controller(motion)
        click = Gtk.GestureClick(button=1)
        click.connect(
            "released", lambda _gesture, _press, _x, _y: self._activate_detail_track(state)
        )
        row.add_controller(click)
        self._update_detail_track_row(state)
        return row

    def _set_detail_track_hover(self, state: dict, hovered: bool) -> None:
        state["hovered"] = hovered
        self._update_detail_track_row(state)

    def _activate_detail_track(self, state: dict) -> None:
        track = state["track"]
        active = (
            getattr(self, "current_item", None) is not None and self.current_item.id == track.id
        )
        if active and self._stream_ready:
            self._toggle_player()
            return
        source = state["source"]
        self.set_queue(source, source.index(track))

    def _toggle_detail_track_like(self, state: dict) -> None:
        state["liked"] = not state["liked"]
        self._update_detail_track_row(state)
        self._toggle_song(state["track"], state["liked"])

    def _update_detail_track_row(self, state: dict) -> None:
        track = state["track"]
        active = (
            getattr(self, "current_item", None) is not None and self.current_item.id == track.id
        )
        playing = active and self.player.playing
        hovered = state["hovered"]
        if active:
            state["row"].add_css_class("detail-track-current")
            state["title"].add_css_class("detail-track-accent")
            state["duration"].add_css_class("detail-track-accent")
        else:
            state["row"].remove_css_class("detail-track-current")
            state["title"].remove_css_class("detail-track-accent")
            state["duration"].remove_css_class("detail-track-accent")
        state["leading"].set_visible_child_name(
            "play" if hovered else ("active" if active else "number")
        )
        state["play"].set_icon_name(
            "media-playback-pause-symbolic" if playing else "media-playback-start-symbolic"
        )
        state["like"].set_icon_name(
            "starred-symbolic" if state["liked"] else "non-starred-symbolic"
        )
        if state["liked"]:
            state["like"].add_css_class("detail-track-accent")
        else:
            state["like"].remove_css_class("detail-track-accent")
        show_like = hovered or state["liked"]
        show_options = hovered or state["options"].get_active()
        state["like"].set_opacity(1.0 if show_like else 0.0)
        state["like"].set_can_target(show_like)
        state["options"].set_opacity(1.0 if show_options else 0.0)
        state["options"].set_can_target(show_options)

    def _refresh_detail_track_states(self) -> None:
        for state in self.detail_track_rows:
            self._update_detail_track_row(state)

    def _search_text_changed(self, entry: Gtk.SearchEntry) -> None:
        if self._suggestion_timeout:
            GLib.source_remove(self._suggestion_timeout)
            self._suggestion_timeout = 0
        query = entry.get_text().strip()
        self._suggestion_request += 1
        request_id = self._suggestion_request
        if len(query) < 2:
            self.search_suggestions.popdown()
            return

        def begin() -> bool:
            self._suggestion_timeout = 0

            def worker() -> None:
                try:
                    values = self.youtube.suggestions(query)
                    GLib.idle_add(self._show_search_suggestions, request_id, query, values)
                except Exception:
                    GLib.idle_add(self._show_search_suggestions, request_id, query, [])

            threading.Thread(target=worker, daemon=True, name="search-suggestions").start()
            return False

        self._suggestion_timeout = GLib.timeout_add(280, begin)

    def _show_search_suggestions(
        self,
        request_id: int,
        query: str,
        suggestions: list[str],
    ) -> bool:
        if request_id != self._suggestion_request or query != self.search_entry.get_text().strip():
            return False
        if not suggestions or not self.search_entry.has_focus():
            self.search_suggestions.popdown()
            return False
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.add_css_class("search-suggestion-list")
        for value in suggestions[:8]:
            button = Gtk.Button(label=value, icon_name="system-search-symbolic")
            button.add_css_class("flat")
            button.set_halign(Gtk.Align.FILL)
            button.connect(
                "clicked", lambda _button, selected=value: self._choose_search_suggestion(selected)
            )
            box.append(button)
        self.search_suggestions.set_child(box)
        self.search_suggestions.popup()
        return False

    def _choose_search_suggestion(self, value: str) -> None:
        self.search_entry.set_text(value)
        self.search_suggestions.popdown()
        self.search(value)

    def search(self, query: str) -> None:
        query = query.strip()
        if not query:
            return
        self.search_suggestions.popdown()
        self._search_request += 1
        request_id = self._search_request
        status = Adw.StatusPage(
            icon_name="system-search-symbolic", title=_("Buscando…"), description=query
        )
        old = self.stack.get_child_by_name("search")
        if old:
            self.stack.remove(old)
        self.stack.add_named(status, "search")
        self.stack.set_visible_child_name("search")
        self.back.set_visible(True)

        def worker():
            try:
                results = self.youtube.universal_search(query)
                GLib.idle_add(self._show_search, request_id, results, None)
            except Exception as exc:
                GLib.idle_add(self._show_search, request_id, None, str(exc))

        threading.Thread(target=worker, daemon=True, name="universal-search").start()

    def _show_search(
        self,
        request_id: int,
        results: SearchResults | None,
        error: str | None,
    ) -> bool:
        if request_id != self._search_request:
            return False
        old = self.stack.get_child_by_name("search")
        if old:
            self.stack.remove(old)
        query = results.query if results else self.search_entry.get_text().strip()
        if error:
            page = Adw.StatusPage(
                icon_name="dialog-error-symbolic", title=_("A busca falhou"), description=error
            )
        elif not results or not results.groups:
            detail = ""
            if results and results.errors:
                detail = _(" Algumas categorias não puderam ser consultadas.")
            page = Adw.StatusPage(
                icon_name="system-search-symbolic",
                title=_("Nenhum resultado"),
                description=_("Nada encontrado para “{query}”").format(query=query),
            )
            if detail:
                page.set_description(page.get_description() + detail)
        else:
            self.search_results = results
            shell = page_shell("reading", spacing=22)
            page, box = shell.scroll, shell.content
            box.append(page_header(_("Resultados para “{query}”").format(query=query)))
            if results.errors:
                warning = Gtk.Label(
                    label=_(
                        "Algumas categorias não puderam ser carregadas; os resultados disponíveis foram preservados."
                    ),
                    xalign=0,
                    wrap=True,
                )
                warning.add_css_class("search-partial-warning")
                box.append(warning)
            for search_group in results.groups:
                box.append(self._search_group_widget(results, search_group))
        self.stack.add_named(page, "search")
        self.stack.set_visible_child_name("search")
        return False

    def _search_group_widget(self, results: SearchResults, search_group: SearchGroup) -> Gtk.Widget:
        group = Adw.PreferencesGroup(title=search_group.title)
        playable = [item for item in search_group.items if item.kind in ("songs", "videos")]
        for item in search_group.items:
            row = Adw.ActionRow()
            row.add_css_class("media-row")
            row.set_use_markup(False)
            row.set_title(item.title)
            row.set_subtitle(item.subtitle)
            row.set_activatable(True)
            row.add_prefix(self._square_cover(item, size=48, fixed=True))
            icon = (
                "media-playback-start-symbolic"
                if item.kind in ("songs", "videos")
                else "go-next-symbolic"
            )
            row.add_suffix(Gtk.Image.new_from_icon_name(icon))
            if item.kind in ("songs", "videos"):
                row.connect(
                    "activated",
                    lambda _row, selected=item, source=playable: self.set_queue(
                        source, source.index(selected)
                    ),
                )
            else:
                row.connect("activated", lambda _row, selected=item: self.open_item(selected))
            group.add(row)
        if search_group.continuation:
            more = action_button(
                _("Carregar mais {category}").format(category=search_group.title.lower()),
                role="secondary",
            )
            more.set_halign(Gtk.Align.CENTER)
            more.connect(
                "clicked",
                lambda button, selected=search_group: self._load_more_search(
                    results, selected, button
                ),
            )
            group.add(more)
        return group

    def _load_more_search(
        self,
        results: SearchResults,
        group: SearchGroup,
        button: Gtk.Button,
    ) -> None:
        button.set_sensitive(False)
        request_id = self._search_request

        def worker() -> None:
            try:
                incoming = self.youtube.search_more(results.query, group)
                GLib.idle_add(
                    self._search_more_done, request_id, results, group.key, incoming, None
                )
            except Exception as exc:
                GLib.idle_add(
                    self._search_more_done, request_id, results, group.key, None, str(exc)
                )

        threading.Thread(target=worker, daemon=True, name="search-continuation").start()

    def _search_more_done(
        self,
        request_id: int,
        results: SearchResults,
        key: str,
        incoming: SearchGroup | None,
        error: str | None,
    ) -> bool:
        if request_id != self._search_request:
            return False
        group = results.group(key)
        if error or group is None or incoming is None:
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=_("Não foi possível carregar mais resultados: {error}").format(
                        error=error
                    )
                )
            )
            self._show_search(request_id, results, None)
            return False
        known = {item.id for item in group.items}
        group.items.extend(item for item in incoming.items if item.id not in known)
        group.continuation = incoming.continuation
        self._show_search(request_id, results, None)
        return False

    def _mutate(
        self, action: str, target: str | None, operation, success_message: str, on_success=None
    ) -> None:
        self.toast_overlay.add_toast(
            Adw.Toast(title=_("Enviando alteração ao YouTube Music…"), timeout=2)
        )

        def worker():
            try:
                result = self.youtube.mutate(operation)
                self.storage.log_action(action, target, "completed")
                GLib.idle_add(done, result, None)
            except Exception as exc:
                self.storage.log_action(action, target, "failed", str(exc))
                GLib.idle_add(done, None, str(exc))

        def done(result, error):
            if error:
                self.toast_overlay.add_toast(
                    Adw.Toast(
                        title=_("Alteração não aplicada: {error}").format(error=error),
                        timeout=6,
                    )
                )
            else:
                self.toast_overlay.add_toast(Adw.Toast(title=success_message))
                if on_success:
                    on_success(result)
            return False

        threading.Thread(target=worker, daemon=True).start()

    def _toggle_song(self, item: LibraryItem, liked: bool) -> None:
        verb = "like-song" if liked else "unlike-song"
        message = (
            _("Música adicionada à biblioteca") if liked else _("Música removida da biblioteca")
        )
        self._mutate(
            verb,
            item.id,
            lambda client: client.like_song(item.id, liked),
            message,
            lambda _r: self.sync(),
        )

    def _refresh_current_like_from_library(self) -> None:
        item = getattr(self, "current_item", None)
        self.current_liked = bool(
            item and any(song.id == item.id for song in self.sections.get("songs", []))
        )
        self._refresh_current_like_buttons()

    def _refresh_current_like_buttons(self) -> None:
        for button in self.like_buttons:
            button.set_icon_name(
                "starred-symbolic" if self.current_liked else "non-starred-symbolic"
            )
            button.set_tooltip_text(
                _("Remover das músicas curtidas") if self.current_liked else _("Curtir música")
            )
            if self.current_liked:
                set_icon_selected(button, True)
            else:
                set_icon_selected(button, False)

    def _toggle_current_song_like(self) -> None:
        item = getattr(self, "current_item", None)
        if item is None:
            return
        self.current_liked = not self.current_liked
        self._refresh_current_like_buttons()
        self._toggle_song(item, self.current_liked)

    def _toggle_artist(self, item: LibraryItem, subscribed: bool) -> None:
        message = _("Inscrição realizada") if subscribed else _("Inscrição cancelada")
        self._mutate(
            "subscribe-artist" if subscribed else "unsubscribe-artist",
            item.id,
            lambda client: client.subscribe_artist(item.id, subscribed),
            message,
            lambda _r: self.sync(),
        )

    def create_playlist_dialog(self) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Nova playlist"),
            body=_("Ela será criada como privada na sua conta do YouTube Music."),
        )
        entry = Gtk.Entry(placeholder_text=_("Nome da playlist"))
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", _("Cancelar"))
        dialog.add_response("create", _("Criar"))
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect(
            "response",
            lambda _d, response: (
                response == "create"
                and entry.get_text().strip()
                and self._mutate(
                    "create-playlist",
                    None,
                    lambda client: client.create_playlist(entry.get_text()),
                    _("Playlist criada"),
                    lambda _r: self.sync(),
                )
            ),
        )
        dialog.present(self)

    def _create_local_playlist_dialog(self) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Nova playlist local"),
            body=_("A playlist ficará somente neste computador."),
        )
        entry = Gtk.Entry(placeholder_text=_("Nome da playlist"))
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", _("Cancelar"))
        dialog.add_response("create", _("Criar"))
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)

        def response(_dialog, name: str) -> None:
            title = entry.get_text().strip()
            if name == "create" and title:
                playlist_id = self.storage.create_local_playlist(title)
                playlist = self.storage.get_local_playlist(playlist_id)
                if playlist:
                    self._show_local_playlist(playlist)

        dialog.connect("response", response)
        dialog.present(self)

    @staticmethod
    def _audio_file_filter() -> Gtk.FileFilter:
        file_filter = Gtk.FileFilter(name=_("Arquivos de áudio"))
        file_filter.add_mime_type("audio/*")
        for pattern in ("*.mp3", "*.m4a", "*.aac", "*.ogg", "*.opus", "*.flac", "*.wav", "*.wma"):
            file_filter.add_pattern(pattern)
        return file_filter

    def _add_local_files_dialog(self, playlist: LocalPlaylist | None = None) -> None:
        dialog = Gtk.FileDialog(title=_("Adicionar arquivos de áudio"))
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(self._audio_file_filter())
        dialog.set_filters(filters)

        def selected(file_dialog: Gtk.FileDialog, result) -> None:
            try:
                files = file_dialog.open_multiple_finish(result)
                paths = [files.get_item(index).get_path() for index in range(files.get_n_items())]
                items = self.storage.add_local_files([path for path in paths if path])
                if playlist is not None:
                    known = {item.id for item in playlist.items}
                    playlist.items.extend(item for item in items if item.id not in known)
                    self.storage.save_local_playlist(playlist)
                    self._show_local_playlist(playlist)
                else:
                    self.library_origin = "local"
                    self.library_filter = "songs"
                    self._render()
            except GLib.Error:
                return

        dialog.open_multiple(self, None, selected)

    def _import_local_playlist_dialog(self) -> None:
        dialog = Gtk.FileDialog(title=_("Importar playlist"))
        file_filter = Gtk.FileFilter(name=_("Playlists M3U ou JSON"))
        for pattern in ("*.m3u", "*.m3u8", "*.json"):
            file_filter.add_pattern(pattern)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(file_filter)
        dialog.set_filters(filters)

        def selected(file_dialog: Gtk.FileDialog, result) -> None:
            try:
                source = file_dialog.open_finish(result)
                path = Path(source.get_path())
                title = path.stem
                items: list[LibraryItem] = []
                if path.suffix.casefold() == ".json":
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    title = str(payload.get("title") or title)
                    for value in payload.get("items") or []:
                        local_path = value.get("path")
                        if local_path:
                            items.extend(self.storage.add_local_files([local_path]))
                        elif value.get("id"):
                            items.append(
                                LibraryItem(
                                    str(value["id"]),
                                    str(value.get("title") or value["id"]),
                                    str(value.get("subtitle") or ""),
                                    value.get("thumbnail"),
                                    str(value.get("kind") or "songs"),
                                    value.get("playlist_id"),
                                    value.get("set_video_id"),
                                )
                            )
                else:
                    paths = []
                    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        candidate = Path(line)
                        paths.append(
                            str(candidate if candidate.is_absolute() else path.parent / candidate)
                        )
                    items = self.storage.add_local_files(paths)
                playlist_id = self.storage.create_local_playlist(title, items)
                playlist = self.storage.get_local_playlist(playlist_id)
                if playlist:
                    self._show_local_playlist(playlist)
            except (GLib.Error, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                self.toast_overlay.add_toast(
                    Adw.Toast(
                        title=_("Não foi possível importar: {error}").format(error=exc),
                        timeout=5,
                    )
                )

        dialog.open(self, None, selected)

    def _export_local_playlist_dialog(self, playlist: LocalPlaylist) -> None:
        dialog = Gtk.FileDialog(title=_("Exportar playlist"), initial_name=f"{playlist.title}.m3u8")

        def selected(file_dialog: Gtk.FileDialog, result) -> None:
            try:
                target_file = file_dialog.save_finish(result)
                target = Path(target_file.get_path())
                if target.suffix.casefold() == ".json":
                    values = []
                    for item in playlist.items:
                        local_path = (
                            self.storage.local_media_path(item.id)
                            if item.id.startswith("local:")
                            else None
                        )
                        values.append(
                            {
                                "id": item.id,
                                "title": item.title,
                                "subtitle": item.subtitle,
                                "thumbnail": item.thumbnail,
                                "kind": item.kind,
                                "playlist_id": item.playlist_id,
                                "set_video_id": item.set_video_id,
                                "path": str(local_path) if local_path else None,
                            }
                        )
                    target.write_text(
                        json.dumps(
                            {"title": playlist.title, "items": values}, ensure_ascii=False, indent=2
                        ),
                        encoding="utf-8",
                    )
                else:
                    lines = ["#EXTM3U"]
                    for item in playlist.items:
                        local_path = (
                            self.storage.local_media_path(item.id)
                            if item.id.startswith("local:")
                            else None
                        )
                        if local_path:
                            lines.extend((f"#EXTINF:-1,{item.title}", str(local_path)))
                    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
                self.toast_overlay.add_toast(Adw.Toast(title=_("Playlist exportada")))
            except (GLib.Error, OSError) as exc:
                self.toast_overlay.add_toast(
                    Adw.Toast(
                        title=_("Não foi possível exportar: {error}").format(error=exc),
                        timeout=5,
                    )
                )

        dialog.save(self, None, selected)

    def rename_playlist_dialog(self, item: LibraryItem) -> None:
        dialog = Adw.AlertDialog(heading=_("Renomear playlist"))
        entry = Gtk.Entry(text=item.title)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", _("Cancelar"))
        dialog.add_response("rename", _("Renomear"))
        dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect(
            "response",
            lambda _d, response: (
                response == "rename"
                and entry.get_text().strip()
                and self._mutate(
                    "rename-playlist",
                    item.id,
                    lambda client: client.rename_playlist(item.id, entry.get_text()),
                    _("Playlist renomeada"),
                    lambda _r: self.sync(),
                )
            ),
        )
        dialog.present(self)

    def delete_playlist_dialog(self, item: LibraryItem) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Excluir playlist?"),
            body=_("“{title}” será removida permanentemente da sua conta.").format(
                title=item.title
            ),
        )
        dialog.add_response("cancel", _("Cancelar"))
        dialog.add_response("delete", _("Excluir"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect(
            "response",
            lambda _d, response: (
                response == "delete"
                and self._mutate(
                    "delete-playlist",
                    item.id,
                    lambda client: client.delete_playlist(item.id),
                    _("Playlist excluída"),
                    lambda _r: (self.show_library(), self.sync()),
                )
            ),
        )
        dialog.present(self)

    def add_to_playlist_dialog(self, song: LibraryItem) -> None:
        playlists = self.sections.get("playlists", [])
        local_playlists = self.storage.load_local_playlists()
        if not playlists and not local_playlists:
            self.toast_overlay.add_toast(Adw.Toast(title=_("Crie uma playlist primeiro")))
            return
        dialog = Adw.AlertDialog(heading=_("Adicionar à playlist"), body=song.title)
        choices = [("remote", item) for item in playlists] + [
            ("local", item) for item in local_playlists
        ]
        dropdown = Gtk.DropDown.new_from_strings(
            [
                item.title if source == "remote" else f"{item.title} · local"
                for source, item in choices
            ]
        )
        dialog.set_extra_child(dropdown)
        dialog.add_response("cancel", _("Cancelar"))
        dialog.add_response("add", _("Adicionar"))
        dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)

        def response(_dialog, name):
            if name == "add":
                source, playlist = choices[dropdown.get_selected()]
                if source == "local":
                    if all(item.id != song.id for item in playlist.items):
                        playlist.items.append(song)
                        self.storage.save_local_playlist(playlist)
                    self.toast_overlay.add_toast(
                        Adw.Toast(title=_("Adicionada a {title}").format(title=playlist.title))
                    )
                else:
                    self._mutate(
                        "add-to-playlist",
                        song.id,
                        lambda client: client.add_to_playlist(playlist.id, song.id),
                        _("Adicionada a {title}").format(title=playlist.title),
                    )

        dialog.connect("response", response)
        dialog.present(self)

    def _remove_track(self, playlist: LibraryItem, song: LibraryItem) -> None:
        self._mutate(
            "remove-from-playlist",
            song.id,
            lambda client: client.remove_from_playlist(
                playlist.id, song.id, song.set_video_id or ""
            ),
            _("Faixa removida da playlist"),
            lambda _r: self.open_item(playlist),
        )

    def _current_playback_state(self, position_ms: int | None = None) -> PlaybackState:
        if position_ms is None:
            position_ms = (
                self.player.position_us // 1000
                if self._stream_ready
                else self._restored_position_ms
            )
        return PlaybackState(
            list(self.queue),
            list(self.related_items),
            max(0, self.queue_index),
            max(0, position_ms),
            self.shuffle_enabled,
            self.repeat_enabled,
            self.autoplay_enabled,
        )

    def _save_playback_state(self, position_ms: int | None = None) -> None:
        if not self.queue:
            return
        self.storage.save_playback_state(self._current_playback_state(position_ms))
        self._last_queue_save = time.monotonic()

    def _restore_playback_state(self) -> None:
        state = self.storage.load_playback_state()
        if state is None or not state.queue:
            return
        self.queue = state.queue
        self.related_items = state.related
        self.queue_index = state.index
        self.shuffle_enabled = state.shuffle
        self.repeat_enabled = state.repeat
        self.autoplay_enabled = state.autoplay
        self._restored_position_ms = state.position_ms
        self.current_item = self.queue[self.queue_index]
        self.now_title.set_label(self.current_item.title)
        self.now_subtitle.set_label(self.current_item.subtitle or "YouTube Music")
        if self.current_item.thumbnail:
            self._load_artwork(self.current_item.thumbnail, self.now_cover, size=128)
        self.elapsed_label.set_label(self._format_time(state.position_ms))
        self._set_footer_item_state(True)
        for control in self.shuffle_buttons:
            set_icon_selected(control, state.shuffle)
        for control in self.repeat_buttons:
            set_icon_selected(control, state.repeat)
        set_icon_selected(self.autoplay_button, state.autoplay)
        self._render_queue()
        self._refresh_expanded_player()

    def set_queue(self, items: list[LibraryItem], index: int = 0) -> None:
        if not items:
            return
        self._autoplay_request += 1
        self._autoplay_loading = False
        self._waiting_for_autoplay = False
        self.related_items = []
        self.queue = list(items)
        self.queue_index = max(0, min(index, len(items) - 1))
        self._render_queue()
        self._save_playback_state()
        self.play_item(self.queue[self.queue_index])
        self._ensure_autoplay()

    def _play_next(self):
        if self.queue_index + 1 < len(self.queue):
            self.queue_index += 1
            self._render_queue()
            self.play_item(self.queue[self.queue_index])
            self._ensure_autoplay()
        elif self.repeat_enabled and self.queue:
            self.queue_index = 0
            self._render_queue()
            self.play_item(self.queue[0])
        elif self.autoplay_enabled and self.queue:
            if self.related_items:
                self._promote_related(self.related_items[0], play_next=False)
                self._play_next()
            else:
                self._waiting_for_autoplay = True
                self._ensure_autoplay(force=True)
        return False

    def _play_previous(self):
        if self.player.position_us > 3_000_000:
            self.play_item(self.queue[self.queue_index])
        elif self.queue_index > 0:
            self.queue_index -= 1
            self._render_queue()
            self.play_item(self.queue[self.queue_index])
        return False

    def _toggle_shuffle(self, button: Gtk.Button) -> None:
        self._set_shuffle(not self.shuffle_enabled)

    def _set_shuffle(self, enabled: bool) -> None:
        if enabled == self.shuffle_enabled:
            return
        self.shuffle_enabled = enabled
        if self.shuffle_enabled and self.queue:
            current = self.queue[self.queue_index]
            remainder = [item for i, item in enumerate(self.queue) if i != self.queue_index]
            random.shuffle(remainder)
            self.queue = [current, *remainder]
            self.queue_index = 0
            self._render_queue()
            self._save_playback_state()
        for control in self.shuffle_buttons:
            set_icon_selected(control, self.shuffle_enabled)
        self._save_playback_state()

    def _toggle_repeat(self, button: Gtk.Button) -> None:
        self._set_repeat(not self.repeat_enabled)

    def _set_repeat(self, enabled: bool) -> None:
        if enabled == self.repeat_enabled:
            return
        self.repeat_enabled = enabled
        for control in self.repeat_buttons:
            set_icon_selected(control, self.repeat_enabled)
        self._save_playback_state()

    def _toggle_autoplay(self, button: Gtk.Button) -> None:
        self.autoplay_enabled = not self.autoplay_enabled
        self._waiting_for_autoplay = False
        if self.autoplay_enabled:
            set_icon_selected(button, True)
            button.set_tooltip_text(_("Reprodução automática ativada"))
            self.toast_overlay.add_toast(Adw.Toast(title=_("Reprodução automática ativada")))
            self._ensure_autoplay()
        else:
            self._autoplay_request += 1
            self._autoplay_loading = False
            set_icon_selected(button, False)
            button.set_tooltip_text(_("Reprodução automática desativada"))
            self.toast_overlay.add_toast(Adw.Toast(title=_("Reprodução automática desativada")))
        self._save_playback_state()

    def _ensure_autoplay(self, force: bool = False) -> None:
        if not self.autoplay_enabled or not self.queue or self._autoplay_loading:
            return
        if self.related_items:
            if self._waiting_for_autoplay:
                self._waiting_for_autoplay = False
                self._promote_related(self.related_items[0], play_next=False)
                self._play_next()
            return
        remaining = len(self.queue) - self.queue_index - 1
        if not force and remaining > 5:
            return
        seed = self.queue[-1]
        self._autoplay_request += 1
        request_id = self._autoplay_request
        self._autoplay_loading = True

        def worker():
            try:
                recommendations = self.youtube.radio(seed.id)
                GLib.idle_add(self._autoplay_loaded, request_id, recommendations, None)
            except Exception as exc:
                GLib.idle_add(self._autoplay_loaded, request_id, None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _autoplay_loaded(
        self, request_id: int, recommendations: list[LibraryItem] | None, error: str | None
    ):
        if request_id != self._autoplay_request:
            return False
        self._autoplay_loading = False
        if error:
            if self._waiting_for_autoplay:
                self.toast_overlay.add_toast(
                    Adw.Toast(
                        title=_("Não foi possível continuar a rádio: {error}").format(error=error),
                        timeout=5,
                    )
                )
            self._waiting_for_autoplay = False
            return False
        existing = {item.id for item in self.queue}
        self.related_items = [item for item in recommendations or [] if item.id not in existing]
        self._render_queue()
        self._save_playback_state()
        if self._waiting_for_autoplay and self.related_items:
            self._waiting_for_autoplay = False
            self._promote_related(self.related_items[0], play_next=False)
            self._play_next()
        elif self._waiting_for_autoplay:
            self._waiting_for_autoplay = False
            self.toast_overlay.add_toast(
                Adw.Toast(title=_("A rádio não encontrou novas músicas"), timeout=4)
            )
        return False

    def _lyrics_toggled(self, button: Gtk.MenuButton, _pspec) -> None:
        if button.get_active():
            self._load_current_lyrics()

    def _set_lyrics_message(
        self, icon: str, title: str, description: str, retry: bool = False
    ) -> None:
        page = Adw.StatusPage(icon_name=icon, title=title, description=description)
        page.set_size_request(410, 430)
        if retry:
            button = action_button(_("Tentar novamente"), role="accent")
            button.set_halign(Gtk.Align.CENTER)
            button.connect("clicked", lambda *_: self._load_current_lyrics(force=True))
            page.set_child(button)
        self.lyrics_popover.set_child(page)
        self._set_expanded_lyrics_message(icon, title, description)

    def _load_current_lyrics(self, force: bool = False) -> None:
        item = getattr(self, "current_item", None)
        if item is None:
            self._set_lyrics_message(
                "audio-input-microphone-symbolic",
                _("Letras"),
                _("Comece a reproduzir uma música para ver a letra."),
            )
            return

        # Opening the footer popover again must not rebuild its scroller.  Apart
        # from wasting work, replacing the adjustment resets it to its lower
        # bound just before the active-line animation starts.
        if (
            not force
            and self.current_lyrics_document is not None
            and self._lyrics_item_id == item.id
            and self._lyric_views
        ):
            self._follow_visible_lyric_views()
            return

        self._lyrics_request += 1
        request_id = self._lyrics_request
        if not force:
            cached = self.storage.load_lyrics_document(item.id, self.lyrics_provider)
            if cached:
                self._render_lyrics(item, cached)
                return

        self._set_lyrics_message("view-refresh-symbolic", _("Carregando letra…"), item.title)

        def worker():
            try:
                document = self.lyrics_resolver.fetch(
                    item, self.current_duration_ms, self.lyrics_provider
                )
                if document:
                    self.storage.save_lyrics_document(item.id, document)
                GLib.idle_add(self._lyrics_loaded, request_id, item.id, document, None)
            except Exception as exc:
                GLib.idle_add(self._lyrics_loaded, request_id, item.id, None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _lyrics_loaded(
        self,
        request_id: int,
        video_id: str,
        document: LyricsDocument | None,
        error: str | None,
    ):
        item = getattr(self, "current_item", None)
        if request_id != self._lyrics_request or item is None or item.id != video_id:
            return False
        if error:
            self._set_lyrics_message(
                "dialog-error-symbolic", _("Não foi possível carregar"), error, retry=True
            )
        elif not document:
            self._set_lyrics_message(
                "audio-input-microphone-symbolic",
                _("Letra indisponível"),
                _("Nenhum dos provedores encontrou uma letra para esta faixa."),
                retry=True,
            )
        else:
            self._render_lyrics(item, document)
        return False

    def _render_lyrics(self, item: LibraryItem, document: LyricsDocument) -> None:
        self.current_lyrics_document = document
        self._lyrics_item_id = item.id
        for view in self._lyric_views:
            view["generation"] += 1
            view["follow_generation"] += 1
        self._lyric_views.clear()
        self._active_lyric_index = -1
        content = self._lyrics_surface(item, document, expanded=False)
        content.add_css_class("lyrics-popover")
        scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            min_content_width=410,
            min_content_height=380,
            max_content_height=520,
        )
        body = content.get_last_child()
        content.remove(body)
        scroll.set_child(body)
        if self._lyric_views and not self._lyric_views[0]["expanded"]:
            self._lyric_views[0]["scroll"] = scroll
        content.append(scroll)
        self.lyrics_popover.set_child(content)
        self._render_expanded_lyrics(item, document)
        self._update_synced_lyrics(self.player.position_us // 1000)

    def _lyrics_surface(
        self, item: LibraryItem, document: LyricsDocument, expanded: bool
    ) -> Gtk.Box:
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        header.add_css_class("lyrics-header")
        title = Gtk.Label(label=item.title, xalign=0, ellipsize=3, max_width_chars=48)
        title.add_css_class("expanded-lyrics-title" if expanded else "lyrics-title")
        header.append(title)
        mode = _("sincronizada") if document.is_synced else _("não sincronizada")
        subtitle = Gtk.Label(
            label=_("{provider} · Letra {mode}").format(provider=document.provider, mode=mode),
            xalign=0,
            ellipsize=3,
        )
        subtitle.add_css_class("expanded-lyrics-provider" if expanded else "lyrics-provider")
        header.append(subtitle)
        content.append(header)
        content.append(self._lyrics_actions(expanded))

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        body.add_css_class("synced-lyrics" if document.is_synced else "plain-lyrics")
        if document.is_synced:
            if expanded:
                lead = Gtk.Box(height_request=180)
                lead.add_css_class("lyrics-breathing-space")
                body.append(lead)
            rows: list[Gtk.Button] = []
            for line in document.synced:
                row = Gtk.Button()
                row.add_css_class("flat")
                row.add_css_class("lyrics-line")
                row.set_tooltip_text(
                    _("Ir para {time}").format(time=self._format_time(line.start_ms))
                )
                row.connect("clicked", lambda _button, value=line.start_ms: self._seek_lyric(value))
                labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                original = Gtk.Label(label=line.text, xalign=0, wrap=True)
                original.add_css_class("lyrics-line-text")
                labels.append(original)
                if line.translation:
                    translated = Gtk.Label(label=line.translation, xalign=0, wrap=True)
                    translated.add_css_class("lyrics-line-translation")
                    labels.append(translated)
                row.set_child(labels)
                body.append(row)
                rows.append(row)
            if expanded:
                tail = Gtk.Box(height_request=240)
                tail.add_css_class("lyrics-breathing-space")
                body.append(tail)
            self._lyric_views.append(
                {
                    "rows": rows,
                    "expanded": expanded,
                    "body": body,
                    "scroll": None,
                    "animation": 0,
                    "generation": 0,
                    "follow_generation": 0,
                }
            )
        else:
            original = Gtk.Label(
                label=document.display_text, xalign=0, yalign=0, wrap=True, selectable=True
            )
            original.set_max_width_chars(54)
            original.add_css_class("expanded-lyrics-text" if expanded else "lyrics-text")
            body.append(original)
            if document.translation:
                translated = Gtk.Label(
                    label=document.translation, xalign=0, yalign=0, wrap=True, selectable=True
                )
                translated.add_css_class("lyrics-plain-translation")
                body.append(translated)
        content.append(body)
        return content

    def _lyrics_actions(self, expanded: bool) -> Gtk.Widget:
        bar = Adw.WrapBox(
            orientation=Gtk.Orientation.HORIZONTAL,
            child_spacing=4,
            line_spacing=4,
            natural_line_length=620 if expanded else 400,
            wrap_policy=Adw.WrapPolicy.NATURAL,
        )
        bar.add_css_class("lyrics-actions")
        provider_names = {"auto": _("Automática"), "lrclib": "LRCLIB", "youtube": "YouTube"}
        provider = Gtk.Button(
            label=_("Fonte: {provider}").format(
                provider=provider_names.get(self.lyrics_provider, _("Automática"))
            ),
            tooltip_text=_("Alternar provedor de letras"),
        )
        style_action(provider, "secondary")
        provider.connect("clicked", lambda *_: self._cycle_lyrics_provider())
        bar.append(provider)
        translate = Gtk.Button(
            icon_name="accessories-dictionary-symbolic", tooltip_text=_("Traduzir para português")
        )
        style_icon_button(translate, "sm")
        translate.connect("clicked", lambda *_: self._translate_current_lyrics())
        bar.append(translate)
        copy = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text=_("Copiar letra"))
        style_icon_button(copy, "sm")
        copy.connect("clicked", lambda *_: self._copy_current_lyrics())
        bar.append(copy)
        earlier = Gtk.Button(
            icon_name="list-remove-symbolic", tooltip_text=_("Adiantar letra em 250 ms")
        )
        style_icon_button(earlier, "sm")
        earlier.connect("clicked", lambda *_: self._change_lyrics_offset(-250))
        bar.append(earlier)
        offset = Gtk.Button(label=self._offset_label(), tooltip_text=_("Zerar ajuste de tempo"))
        style_action(offset, "secondary")
        offset.add_css_class("lyrics-offset")
        offset.connect("clicked", lambda *_: self._set_lyrics_offset(0))
        bar.append(offset)
        later = Gtk.Button(icon_name="list-add-symbolic", tooltip_text=_("Atrasar letra em 250 ms"))
        style_icon_button(later, "sm")
        later.connect("clicked", lambda *_: self._change_lyrics_offset(250))
        bar.append(later)
        return bar

    def _cycle_lyrics_provider(self) -> None:
        providers = ("auto", "lrclib", "youtube")
        self.lyrics_provider = providers[
            (providers.index(self.lyrics_provider) + 1) % len(providers)
        ]
        self.storage.set_setting("lyrics_provider", self.lyrics_provider)
        self._load_current_lyrics(force=False)

    def _offset_label(self) -> str:
        return "Sincronia 0 ms" if not self.lyrics_offset_ms else f"{self.lyrics_offset_ms:+d} ms"

    def _change_lyrics_offset(self, delta: int) -> None:
        self._set_lyrics_offset(max(-5000, min(5000, self.lyrics_offset_ms + delta)))

    def _set_lyrics_offset(self, value: int) -> None:
        self.lyrics_offset_ms = value
        self.storage.set_setting("lyrics_offset_ms", str(value))
        item = getattr(self, "current_item", None)
        if item and self.current_lyrics_document:
            self._render_lyrics(item, self.current_lyrics_document)

    def _seek_lyric(self, start_ms: int) -> None:
        position_ms = max(0, start_ms - self.lyrics_offset_ms)
        if self.player.seek(position_ms * 1000):
            self._update_synced_lyrics(position_ms, allow_backward=True)

    def _copy_current_lyrics(self) -> None:
        document = self.current_lyrics_document
        display = Gdk.Display.get_default()
        if not document or not display:
            return
        value = document.display_text
        if document.translation:
            value += "\n\n" + document.translation
        if document.synced and any(line.translation for line in document.synced):
            value = "\n".join(
                f"{line.text}\n{line.translation}" if line.translation else line.text
                for line in document.synced
            )
        display.get_clipboard().set(value)
        self.toast_overlay.add_toast(Adw.Toast(title=_("Letra copiada"), timeout=2))

    def _translate_current_lyrics(self) -> None:
        item = getattr(self, "current_item", None)
        document = self.current_lyrics_document
        if not item or not document:
            return
        if document.translation_language == "pt" and (
            document.translation or any(line.translation for line in document.synced)
        ):
            document.translation = ""
            document.translation_language = ""
            document.synced = [LyricLine(line.start_ms, line.text) for line in document.synced]
            self.storage.save_lyrics_document(item.id, document)
            self._render_lyrics(item, document)
            return
        self.toast_overlay.add_toast(Adw.Toast(title=_("Traduzindo letra…"), timeout=2))
        request_id = self._lyrics_request
        lines = [line.text for line in document.synced] or document.display_text.splitlines()

        def worker():
            try:
                result = self.translation_client.translate(lines, "pt")
                GLib.idle_add(self._lyrics_translated, request_id, item.id, result, None)
            except Exception as exc:
                GLib.idle_add(self._lyrics_translated, request_id, item.id, None, str(exc))

        threading.Thread(target=worker, daemon=True, name="lyrics-translation").start()

    def _lyrics_translated(self, request_id, video_id, result, error):
        item = getattr(self, "current_item", None)
        document = self.current_lyrics_document
        if request_id != self._lyrics_request or not item or item.id != video_id or not document:
            return False
        if error or not result or not any(result):
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=_("Falha ao traduzir: {error}").format(
                        error=error or _("resposta vazia")
                    ),
                    timeout=5,
                )
            )
            return False
        if document.synced:
            document.synced = [
                LyricLine(line.start_ms, line.text, result[index] if index < len(result) else "")
                for index, line in enumerate(document.synced)
            ]
        else:
            document.translation = "\n".join(result)
        document.translation_language = "pt"
        self.storage.save_lyrics_document(item.id, document)
        self._render_lyrics(item, document)
        self.toast_overlay.add_toast(Adw.Toast(title=_("Letra traduzida"), timeout=2))
        return False

    def _update_synced_lyrics(self, position_ms: int, *, allow_backward: bool = False) -> None:
        document = self.current_lyrics_document
        if not document or not document.synced:
            return
        adjusted = position_ms + self.lyrics_offset_ms
        active = -1
        for index, line in enumerate(document.synced):
            if line.start_ms > adjusted:
                break
            active = index
        # GStreamer can briefly report an older/zero position while a network
        # stream is buffering. Lyrics naturally move forward during playback,
        # so accepting that transient value would animate the footer back to
        # the beginning. Real user seeks opt in to backwards movement.
        if (
            not allow_backward
            and self._active_lyric_index >= 0
            and active < self._active_lyric_index
        ):
            return
        if active == self._active_lyric_index:
            return
        self._active_lyric_index = active
        for view in self._lyric_views:
            for index, row in enumerate(view["rows"]):
                if index == active:
                    row.add_css_class("lyrics-line-active")
                else:
                    row.remove_css_class("lyrics-line-active")
            if active >= 0:
                should_follow = (
                    view["expanded"]
                    and self.expanded_revealer.get_reveal_child()
                    and self.expanded_stack.get_visible_child_name() == "lyrics"
                ) or (not view["expanded"] and self.lyrics_button.get_active())
                if should_follow:
                    self._queue_lyric_follow(view, active)

    def _follow_visible_lyric_views(self) -> None:
        """Resume following without replacing either lyrics scroller."""
        if self._active_lyric_index < 0:
            self._update_synced_lyrics(self.player.position_us // 1000)
            return
        for view in self._lyric_views:
            visible = (
                view["expanded"]
                and self.expanded_revealer.get_reveal_child()
                and self.expanded_stack.get_visible_child_name() == "lyrics"
            ) or (not view["expanded"] and self.lyrics_button.get_active())
            if visible:
                self._queue_lyric_follow(view, self._active_lyric_index)

    def _queue_lyric_follow(self, view: dict, index: int) -> None:
        """Keep only the newest allocation-time scroll request for a view."""
        view["follow_generation"] += 1
        generation = view["follow_generation"]
        GLib.idle_add(self._follow_lyric_line, view, index, generation)

    @staticmethod
    def _lyric_scroll_destination(
        row_top: float,
        row_height: float,
        viewport_height: float,
        lower: float,
        upper: float,
        *,
        expanded: bool,
    ) -> float:
        """Place expanded lyrics centrally and footer lyrics slightly above center."""
        anchor = 0.50 if expanded else 0.42
        target = row_top + row_height / 2 - viewport_height * anchor
        return max(lower, min(target, max(lower, upper - viewport_height)))

    def _follow_lyric_line(
        self, view: dict, index: int, follow_generation: int | None = None
    ) -> bool:
        if follow_generation is not None and follow_generation != view["follow_generation"]:
            return GLib.SOURCE_REMOVE
        scroll = view.get("scroll")
        if scroll is None or index >= len(view["rows"]):
            return GLib.SOURCE_REMOVE
        scroll_content = scroll.get_child()
        if scroll_content is None:
            return GLib.SOURCE_REMOVE
        ok, bounds = view["rows"][index].compute_bounds(scroll_content)
        adjustment = scroll.get_vadjustment()
        if not ok or adjustment.get_page_size() <= 1:
            return GLib.SOURCE_REMOVE
        # GTK reports bounds after the scrolled-window transform, therefore Y
        # is relative to the visible viewport once the adjustment is non-zero.
        # Convert it back to a stable content coordinate before calculating the
        # next destination; otherwise consecutive lines oscillate toward zero.
        row_top = bounds.get_y() + adjustment.get_value()
        destination = self._lyric_scroll_destination(
            row_top,
            bounds.get_height(),
            adjustment.get_page_size(),
            adjustment.get_lower(),
            adjustment.get_upper(),
            expanded=view["expanded"],
        )
        self._animate_lyric_scroll(view, adjustment, destination)
        return GLib.SOURCE_REMOVE

    def _animate_lyric_scroll(
        self,
        view: dict,
        adjustment: Gtk.Adjustment,
        destination: float,
        duration_ms: int = 420,
    ) -> None:
        """Animate the adjustment without stealing keyboard focus from the player."""
        view["generation"] += 1
        generation = view["generation"]
        start = adjustment.get_value()
        distance = destination - start
        if abs(distance) < 1:
            return
        started = time.monotonic()

        def tick() -> bool:
            if generation != view["generation"]:
                return GLib.SOURCE_REMOVE
            progress = min(1.0, (time.monotonic() - started) * 1000 / duration_ms)
            eased = 1 - (1 - progress) ** 3
            adjustment.set_value(start + distance * eased)
            return GLib.SOURCE_CONTINUE if progress < 1 else GLib.SOURCE_REMOVE

        view["animation"] = GLib.timeout_add(16, tick)

    def _render_queue(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.add_css_class("queue-popover")
        heading = Gtk.Label(label=_("Fila de reprodução"), xalign=0)
        heading.add_css_class("section-title")
        box.append(heading)
        scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            min_content_width=360,
            max_content_height=430,
            propagate_natural_height=True,
        )
        listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        listing.add_css_class("boxed-list")
        for position, item in enumerate(self.queue):
            row = Adw.ActionRow()
            row.set_use_markup(False)
            row.set_title(item.title)
            row.set_subtitle(item.subtitle)
            row.set_activatable(True)
            if position == self.queue_index:
                row.add_prefix(Gtk.Image.new_from_icon_name("audio-volume-high-symbolic"))
                row.add_css_class("current-track")
            controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            up = Gtk.Button(icon_name="go-up-symbolic", tooltip_text=_("Mover para cima"))
            down = Gtk.Button(icon_name="go-down-symbolic", tooltip_text=_("Mover para baixo"))
            remove = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text=_("Remover da fila"))
            for control in (up, down, remove):
                control.add_css_class("flat")
                controls.append(control)
            up.set_sensitive(position > 0)
            down.set_sensitive(position + 1 < len(self.queue))
            up.connect(
                "clicked",
                lambda *_args, selected=position: GLib.idle_add(
                    self._move_queue_item, selected, -1
                ),
            )
            down.connect(
                "clicked",
                lambda *_args, selected=position: GLib.idle_add(self._move_queue_item, selected, 1),
            )
            remove.connect(
                "clicked",
                lambda *_args, selected=position: GLib.idle_add(self._remove_queue_item, selected),
            )
            row.add_suffix(controls)
            row.connect(
                "activated", lambda _row, selected=position: self._select_queue_item(selected)
            )
            listing.append(row)
        scroll.set_child(listing)
        box.append(scroll)
        related_heading = Gtk.Label(label=_("Relacionadas"), xalign=0)
        related_heading.add_css_class("section-title")
        box.append(related_heading)
        if self.related_items:
            related = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            related.add_css_class("boxed-list")
            for item in self.related_items[:12]:
                row = Adw.ActionRow()
                row.set_use_markup(False)
                row.set_title(item.title)
                row.set_subtitle(item.subtitle)
                next_button = Gtk.Button(
                    icon_name="media-playlist-consecutive-symbolic",
                    tooltip_text=_("Tocar em seguida"),
                )
                add_button = Gtk.Button(
                    icon_name="list-add-symbolic", tooltip_text=_("Adicionar ao fim")
                )
                for button in (next_button, add_button):
                    button.add_css_class("flat")
                    row.add_suffix(button)
                next_button.connect(
                    "clicked",
                    lambda *_args, selected=item: GLib.idle_add(
                        self._promote_related, selected, True
                    ),
                )
                add_button.connect(
                    "clicked",
                    lambda *_args, selected=item: GLib.idle_add(
                        self._promote_related, selected, False
                    ),
                )
                related.append(row)
            box.append(related)
        else:
            note = Gtk.Label(
                label=_("As recomendações aparecem conforme a fila avança."), xalign=0, wrap=True
            )
            note.add_css_class("dim-label")
            box.append(note)
        self.queue_popover.set_child(box)
        self._render_expanded_related()

    def _move_queue_item(self, position: int, direction: int) -> None:
        target = position + direction
        if position < 0 or target < 0 or position >= len(self.queue) or target >= len(self.queue):
            return
        self.queue[position], self.queue[target] = self.queue[target], self.queue[position]
        if self.queue_index == position:
            self.queue_index = target
        elif self.queue_index == target:
            self.queue_index = position
        self._render_queue()
        self._save_playback_state()

    def _remove_queue_item(self, position: int) -> None:
        if position < 0 or position >= len(self.queue):
            return
        removing_current = position == self.queue_index
        self.queue.pop(position)
        if not self.queue:
            self._stop_player()
            return
        if position < self.queue_index:
            self.queue_index -= 1
        elif self.queue_index >= len(self.queue):
            self.queue_index = len(self.queue) - 1
        self._render_queue()
        self._save_playback_state()
        if removing_current:
            self.play_item(self.queue[self.queue_index])

    def _promote_related(self, item: LibraryItem, play_next: bool) -> None:
        self.related_items = [
            candidate for candidate in self.related_items if candidate.id != item.id
        ]
        position = min(len(self.queue), self.queue_index + 1) if play_next else len(self.queue)
        self.queue.insert(position, item)
        self._render_queue()
        self._save_playback_state()

    def _select_queue_item(self, position: int) -> None:
        self.queue_index = position
        self._render_queue()
        self.queue_popover.popdown()
        self._save_playback_state()
        self.play_item(self.queue[position])

    def play_item(self, item: LibraryItem) -> None:
        resume_position = (
            self._restored_position_ms if getattr(self, "current_item", None) is item else 0
        )
        self._restored_position_ms = 0
        self._pending_seek_ms = resume_position
        self._play_request += 1
        request_id = self._play_request
        self._stream_ready = False
        self._stream_recovery_attempts = 0
        self._lyrics_request += 1
        self.current_lyrics_document = None
        self._lyrics_item_id = None
        for view in self._lyric_views:
            view["generation"] += 1
            view["follow_generation"] += 1
        self._lyric_views.clear()
        self._active_lyric_index = -1
        self.current_item = item
        self._refresh_detail_track_states()
        self._refresh_home_song_rows()
        self._set_footer_item_state(True)
        self.now_title.set_label(item.title)
        self.now_subtitle.set_label(item.subtitle or "YouTube Music")
        if item.thumbnail:
            self._load_artwork(item.thumbnail, self.now_cover, size=128)
        else:
            self.now_cover.set_paintable(None)
            self.ambient_background.set_paintable(None)
        self._refresh_expanded_player()
        self.player_bar.set_visible(not self.expanded_revealer.get_reveal_child())
        self.play_button.set_sensitive(False)
        self.expanded_play_button.set_sensitive(False)
        self.progress.set_sensitive(False)
        self.progress.set_value(0)
        self.expanded_progress.set_sensitive(False)
        self.expanded_progress.set_value(0)
        self.elapsed_label.set_label(_("0:00"))
        self.expanded_elapsed_label.set_label(_("0:00"))
        self.duration_label.set_label(_("0:00"))
        self.expanded_duration_label.set_label(_("0:00"))
        self.toast_overlay.add_toast(
            Adw.Toast(title=_("Preparando {title}…").format(title=item.title), timeout=2)
        )
        if self.lyrics_button.get_active() or (
            self.expanded_revealer.get_reveal_child()
            and self.expanded_stack.get_visible_child_name() == "lyrics"
        ):
            GLib.idle_add(self._load_current_lyrics)

        def worker():
            try:
                if item.id.startswith("local:"):
                    local_path = self.storage.local_media_path(item.id)
                    if not local_path or not local_path.is_file():
                        raise FileNotFoundError(_("O arquivo local não está mais disponível"))
                    GLib.idle_add(self._start_stream, request_id, local_path.as_uri(), None, None)
                    return
                offline_path = self.downloads.offline_path(item.id)
                if offline_path:
                    GLib.idle_add(self._start_stream, request_id, offline_path.as_uri(), None, None)
                    return
                stream = self.youtube.resolve_stream(item.id)
                GLib.idle_add(
                    self._start_stream,
                    request_id,
                    stream.url,
                    stream.duration_ms,
                    stream.playback_tracking_url,
                )
            except Exception as exc:
                GLib.idle_add(self._play_request_error, request_id, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _start_stream(
        self,
        request_id: int,
        url: str,
        duration_ms: int | None,
        playback_tracking_url: str | None = None,
    ):
        if request_id != self._play_request:
            return False
        self._stream_ready = True
        self.play_button.set_sensitive(True)
        self.expanded_play_button.set_sensitive(True)
        self.current_duration_ms = duration_ms or 0
        self.duration_label.set_label(self._format_time(self.current_duration_ms))
        self.expanded_duration_label.set_label(self._format_time(self.current_duration_ms))
        self.progress.set_sensitive(True)
        self.expanded_progress.set_sensitive(True)
        self.player.play(url)
        if self._pending_seek_ms:
            GLib.timeout_add(700, self._apply_pending_seek, request_id, self._pending_seek_ms)
        self._history_tracking_request = request_id
        GLib.timeout_add_seconds(
            30,
            self._register_qualified_playback,
            request_id,
            self.current_item,
            playback_tracking_url,
        )
        self._save_playback_state()
        self.mpris.update(self.current_item, (duration_ms or 0) * 1000)
        return False

    def _register_qualified_playback(
        self,
        request_id: int,
        item: LibraryItem,
        tracking_url: str | None,
    ) -> bool:
        if (
            request_id != self._play_request
            or request_id != self._history_tracking_request
            or self.player.position_us < 28_000_000
            or not self.storage.history_enabled()
        ):
            return False
        if self._history_recorded_request == request_id:
            return False
        self.storage.record_history(item, self.player.position_us // 1000)
        self._history_recorded_request = request_id
        if tracking_url:
            threading.Thread(
                target=lambda: self._register_remote_playback(tracking_url, item.playlist_id),
                daemon=True,
                name="playback-history",
            ).start()
        return False

    def _register_remote_playback(self, tracking_url: str, playlist_id: str | None) -> None:
        try:
            self.youtube.register_playback(tracking_url, playlist_id)
        except Exception:
            LOGGER.debug(
                "Não foi possível registrar a reprodução remota; o histórico local foi mantido",
                exc_info=True,
            )

    def _apply_pending_seek(self, request_id: int, position_ms: int) -> bool:
        if request_id == self._play_request and self.current_duration_ms > position_ms:
            self.player.seek(position_ms * 1000)
        self._pending_seek_ms = 0
        return False

    def _play_request_error(self, request_id: int, error: str):
        if request_id == self._play_request:
            return self._player_error(error)
        return False

    def _toggle_player(self) -> None:
        """Pause/resume a loaded stream, or resolve the selected track again."""
        if self._stream_ready:
            self.player.toggle()
        elif getattr(self, "current_item", None):
            self.play_item(self.current_item)

    @staticmethod
    def _format_time(milliseconds: int) -> str:
        seconds = max(0, milliseconds // 1000)
        return f"{seconds // 60}:{seconds % 60:02d}"

    def _update_progress(self):
        if self._stream_ready and self.current_duration_ms <= 0:
            discovered_duration = self.player.duration_us // 1000
            if discovered_duration > 0:
                self.current_duration_ms = discovered_duration
                duration = self._format_time(discovered_duration)
                self.duration_label.set_label(duration)
                self.expanded_duration_label.set_label(duration)
                self.progress.set_sensitive(True)
                self.expanded_progress.set_sensitive(True)
        if self.current_duration_ms > 0:
            position_ms = self.player.position_us // 1000
            self._updating_progress = True
            value = min(100, position_ms * 100 / self.current_duration_ms)
            self.progress.set_value(value)
            self.expanded_progress.set_value(value)
            self._updating_progress = False
            elapsed = self._format_time(position_ms)
            self.elapsed_label.set_label(elapsed)
            self.expanded_elapsed_label.set_label(elapsed)
            self._update_synced_lyrics(position_ms)
            if time.monotonic() - self._last_queue_save >= 5:
                self._save_playback_state(position_ms)
        return GLib.SOURCE_CONTINUE

    def _seek_requested(self, _scale, _scroll, value):
        if not self._updating_progress and self.current_duration_ms > 0:
            position_us = int(self.current_duration_ms * 1000 * value / 100)
            if self.player.seek(position_us):
                elapsed = self._format_time(position_us // 1000)
                self.elapsed_label.set_label(elapsed)
                self.expanded_elapsed_label.set_label(elapsed)
                self._update_synced_lyrics(position_us // 1000, allow_backward=True)
        return False

    def _player_state(self, playing: bool):
        icon = "media-playback-pause-symbolic" if playing else "media-playback-start-symbolic"
        self.play_button.set_icon_name(icon)
        self.expanded_play_button.set_icon_name(icon)
        self._refresh_detail_track_states()
        self._refresh_home_song_rows()
        self.mpris.update()
        return False

    def _pause(self):
        if self.player.playing:
            self.player.toggle()

    def _resume(self):
        if not self.player.playing:
            self._toggle_player()

    def _player_error(self, error: str):
        self._stream_ready = False
        item = getattr(self, "current_item", None)
        if item is not None and self._stream_recovery_attempts < 1:
            self._stream_recovery_attempts += 1
            request_id = self._play_request
            self.play_button.set_sensitive(False)
            self.expanded_play_button.set_sensitive(False)
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=_("O stream falhou; renovando a conexão…"),
                    timeout=3,
                )
            )

            def recover() -> None:
                try:
                    stream = self.youtube.resolve_stream(item.id, force=True)
                    GLib.idle_add(
                        self._start_stream,
                        request_id,
                        stream.url,
                        stream.duration_ms,
                        stream.playback_tracking_url,
                    )
                except Exception as exc:
                    GLib.idle_add(self._player_recovery_failed, request_id, str(exc))

            threading.Thread(target=recover, daemon=True, name="stream-recovery").start()
            return False
        self.play_button.set_sensitive(True)
        self.play_button.set_icon_name("media-playback-start-symbolic")
        self.expanded_play_button.set_sensitive(True)
        self.expanded_play_button.set_icon_name("media-playback-start-symbolic")
        self.toast_overlay.add_toast(
            Adw.Toast(title=_("Falha na reprodução: {error}").format(error=error), timeout=6)
        )
        return False

    def _player_recovery_failed(self, request_id: int, error: str) -> bool:
        if request_id != self._play_request:
            return False
        self.play_button.set_sensitive(True)
        self.play_button.set_icon_name("media-playback-start-symbolic")
        self.expanded_play_button.set_sensitive(True)
        self.expanded_play_button.set_icon_name("media-playback-start-symbolic")
        self.toast_overlay.add_toast(
            Adw.Toast(
                title=_("Falha na reprodução após renovar o stream: {error}").format(error=error),
                timeout=6,
            )
        )
        return False

    def _stop_player(self) -> None:
        self._play_request += 1
        self._lyrics_request += 1
        self._autoplay_request += 1
        self._autoplay_loading = False
        self._waiting_for_autoplay = False
        self._stream_ready = False
        self.player.stop()
        self.lyrics_popover.popdown()
        self._hide_expanded_player()
        self.current_item = None
        self.queue = []
        self.related_items = []
        self.queue_index = -1
        self.storage.clear_playback_state()
        self.current_duration_ms = 0
        self.expanded_progress.set_value(0)
        self.expanded_progress.set_sensitive(False)
        self.expanded_elapsed_label.set_label(_("0:00"))
        self.expanded_duration_label.set_label(_("0:00"))
        self._set_footer_item_state(False)
        self._render_queue()
        self._refresh_detail_track_states()
        self._refresh_home_song_rows()
        self.mpris.clear()

    def login_dialog(self) -> None:
        try:
            from .auth import LoginWindow

            LoginWindow(
                self,
                self.storage.web_data_dir,
                self._integrated_login_done,
                self.manual_login_dialog,
            ).present()
        except (ImportError, ValueError) as exc:
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=_("Navegador integrado indisponível: {error}").format(error=exc),
                    timeout=5,
                )
            )
            self.manual_login_dialog()

    def _integrated_login_done(self, cookie: str) -> None:
        self.storage.save_cookie(cookie)
        self._load_account_avatar("")
        self._refresh_account_avatar()
        self.sections = {}
        self.home_sections = []
        self.explore_data = ExploreData([], [], [])
        self._render()
        self.toast_overlay.add_toast(Adw.Toast(title=_("Conta conectada. Sincronizando…")))
        self.sync()
        self.sync_home()
        self.sync_explore()

    def manual_login_dialog(self) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Conectar ao YouTube Music"),
            body=_(
                "No navegador, abra music.youtube.com já conectado, copie o cabeçalho Cookie de uma requisição nas ferramentas de desenvolvedor e cole abaixo. A senha nunca é solicitada."
            ),
        )
        entry = Gtk.PasswordEntry(
            show_peek_icon=True, placeholder_text=_("SAPISID=…; __Secure-3PAPISID=…")
        )
        entry.set_text(self.storage.load_cookie())
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", _("Cancelar"))
        if self.storage.load_cookie():
            dialog.add_response("disconnect", _("Desconectar"))
            dialog.set_response_appearance("disconnect", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.add_response("connect", _("Conectar"))
        dialog.set_response_appearance("connect", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("connect")

        def response(_dialog, name):
            if name == "disconnect":
                self.youtube.disconnect()
                self._clear_account_avatar()
                self.sections = {}
                self.home_sections = []
                self.explore_data = ExploreData([], [], [])
                self._render()
            elif name == "connect":
                value = entry.get_text().strip()
                if not self.youtube.connect(value):
                    self.toast_overlay.add_toast(
                        Adw.Toast(title=_("Cookie inválido: SAPISID não encontrado"))
                    )
                    return
                self._load_account_avatar("")
                self._refresh_account_avatar()
                self._render()
                self.sync()
                self.sync_home()
                self.sync_explore()

        dialog.connect("response", response)
        dialog.present(self)

    def sync(self) -> None:
        cookie = self.storage.load_cookie()
        if not cookie:
            self.login_dialog()
            return
        self.toast_overlay.add_toast(Adw.Toast(title=_("Sincronizando biblioteca…"), timeout=2))

        def worker():
            try:
                sections = self.youtube.sync_library()
                GLib.idle_add(self._sync_done, sections, None)
            except Exception as exc:
                GLib.idle_add(self._sync_done, None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def sync_home(self) -> None:
        cookie = self.storage.load_cookie()
        if not cookie:
            return

        def worker():
            try:
                sections = self.youtube.sync_home()
                GLib.idle_add(self._home_sync_done, sections, None)
            except Exception as exc:
                GLib.idle_add(self._home_sync_done, None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def sync_explore(self) -> None:
        cookie = self.storage.load_cookie()
        if not cookie:
            return

        def worker():
            try:
                data = self.youtube.sync_explore()
                GLib.idle_add(self._explore_sync_done, data, None)
            except Exception as exc:
                GLib.idle_add(self._explore_sync_done, None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _home_sync_done(self, sections, error):
        if error:
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=_("Não foi possível atualizar o início: {error}").format(error=error),
                    timeout=5,
                )
            )
            return False
        self.home_sections = sections
        if self.main_view == "home" and not self.back.get_visible():
            self._render_home()
            self.stack.set_visible_child_name("home")
        return False

    def _explore_sync_done(self, data, error):
        if error:
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=_("Não foi possível atualizar o Explorar: {error}").format(error=error),
                    timeout=5,
                )
            )
            return False
        self.explore_data = data
        if self.main_view == "explore" and not self.back.get_visible():
            self.show_explore()
        return False

    def _sync_done(self, sections, error):
        if error:
            self.toast_overlay.add_toast(
                Adw.Toast(title=_("Falha na sincronização: {error}").format(error=error), timeout=6)
            )
            return False
        self.sections = sections
        self._refresh_current_like_from_library()
        self._render()
        if self.main_view == "home" and not self.back.get_visible():
            self._render_home()
            self.stack.set_visible_child_name("home")
        elif self.main_view == "explore" and not self.back.get_visible():
            self.show_explore()
        total = sum(map(len, sections.values()))
        self.toast_overlay.add_toast(
            Adw.Toast(
                title=ngettext(
                    "Biblioteca atualizada · {count} item",
                    "Biblioteca atualizada · {count} itens",
                    total,
                ).format(count=total)
            )
        )
        return False


class HarmoniaApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_startup(self):
        Adw.Application.do_startup(self)
        Gtk.Window.set_default_icon_name(APP_ID)
        provider = Gtk.CssProvider()
        provider.load_from_path(str(Path(__file__).with_name("style.css")))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def do_activate(self):
        window = self.get_active_window() or HarmoniaWindow(self)
        window.present()


def main() -> int:
    GLib.set_prgname(APP_ID)
    GLib.set_application_name(_("Harmonia"))
    try:
        return HarmoniaApplication().run()
    except KeyboardInterrupt:
        return 130
