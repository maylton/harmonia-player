from __future__ import annotations

import logging
import re
import threading
import urllib.request
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .downloads import DownloadManager
from .i18n import _
from .lyrics import GoogleTranslationClient, LyricsResolver
from .models import (
    HistoryEntry,
    LibraryItem,
    LyricsDocument,
    SearchResults,
)
from .mpris import MprisService
from .player import NativePlayer
from .preferences import Preferences
from .services import YouTubeMusicService
from .storage import Storage
from .ui import (
    menu_action_button,
    set_icon_selected,
    style_icon_button,
)
from .window_account import WindowAccountMixin
from .window_actions import WindowActionsMixin
from .window_constants import EXPLORE_ICON, LIKED_ICON
from .window_detail import WindowDetailMixin
from .window_history import WindowHistoryMixin
from .window_home import WindowHomeMixin
from .window_insights import WindowInsightsMixin
from .window_library import WindowLibraryMixin
from .window_lyrics import WindowLyricsMixin
from .window_optional import WindowOptionalMixin
from .window_playback import WindowPlaybackMixin
from .window_preferences import WindowPreferencesMixin
from .window_search import WindowSearchMixin
from .window_social import WindowSocialMixin

LOGGER = logging.getLogger(__name__)
APP_ID = "io.github.harmonia.Harmonia"


class HarmoniaWindow(
    WindowPreferencesMixin,
    WindowHistoryMixin,
    WindowInsightsMixin,
    WindowHomeMixin,
    WindowLibraryMixin,
    WindowDetailMixin,
    WindowSearchMixin,
    WindowActionsMixin,
    WindowLyricsMixin,
    WindowPlaybackMixin,
    WindowOptionalMixin,
    WindowSocialMixin,
    WindowAccountMixin,
    Adw.ApplicationWindow,
):
    def __init__(self, app: Adw.Application):
        super().__init__(
            application=app, title=_("Harmonia"), default_width=1080, default_height=760
        )
        self.storage = Storage()
        self.preferences = Preferences.load(self.storage)
        self._initialize_social()
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
        self._initialize_optional_services()
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
                "seek": self._seek_playback,
            },
            {
                "repeat": lambda: self.repeat_enabled,
                "shuffle": lambda: self.shuffle_enabled,
                "playing": self._playback_is_playing,
                "position": self._playback_position_us,
            },
        )
        self.connect("close-request", self._shutdown_application)
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
            (_("Estatísticas"), "applications-multimedia-symbolic", self.show_insights),
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
                "insights",
                _("Estatísticas"),
                "applications-multimedia-symbolic",
                self.show_insights,
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
        elif self.main_view == "history" or self.main_view == "insights":
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
