from __future__ import annotations

import logging
import re
import threading
import urllib.request
from html import escape
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import queue_view
from .auto_backup import open_storage
from .crossfade_player import CrossfadingPlayer
from .downloads import DownloadManager
from .gtk_media_variants import GtkMediaVariantsMixin
from .gtk_theme import GtkThemeController
from .gtk_video import GtkVideoMixin
from .i18n import _
from .lyrics import GoogleTranslationClient, LyricsResolver
from .lyrics_state import normalize_lyrics_provider
from .models import (
    HistoryEntry,
    LibraryItem,
    LyricsDocument,
    SearchResults,
)
from .mpris import MprisService
from .preferences import Preferences
from .services import YouTubeMusicService
from .theming import DEFAULT_THEME
from .track_rows import DetailTrackRow, HomeSongRow
from .ui import (
    deliver_to_main,
)
from .window_account import WindowAccountMixin
from .window_actions import WindowActionsMixin
from .window_artist import WindowArtistMixin
from .window_artwork import WindowArtworkMixin
from .window_autoplay import WindowAutoplayMixin
from .window_chrome import (
    build_expanded_player,
    build_header,
    build_player_bar,
    build_sidebar,
)
from .window_detail import WindowDetailMixin
from .window_detail_header import WindowDetailHeaderMixin
from .window_history import WindowHistoryMixin
from .window_home import WindowHomeMixin
from .window_insights import WindowInsightsMixin
from .window_item_menu import WindowItemMenuMixin
from .window_library import WindowLibraryMixin
from .window_local_playlists import WindowLocalPlaylistsMixin
from .window_lyrics import WindowLyricsMixin
from .window_optional import WindowOptionalMixin
from .window_playback import WindowPlaybackMixin
from .window_playback_recovery import WindowPlaybackRecoveryMixin
from .window_preferences import WindowPreferencesMixin
from .window_search import WindowSearchMixin
from .window_shelves import WindowShelvesMixin
from .window_social import WindowSocialMixin

LOGGER = logging.getLogger(__name__)
APP_ID = "io.github.harmonia.Harmonia"


class HarmoniaWindow(
    # The video layers come first: they extend playback methods of the
    # mixins below (play_item, _stop_player, _seek_playback...) through super().
    GtkMediaVariantsMixin,
    GtkVideoMixin,
    WindowPreferencesMixin,
    WindowHistoryMixin,
    WindowInsightsMixin,
    WindowHomeMixin,
    WindowLibraryMixin,
    WindowLocalPlaylistsMixin,
    WindowShelvesMixin,
    WindowArtworkMixin,
    WindowDetailMixin,
    WindowDetailHeaderMixin,
    WindowArtistMixin,
    WindowSearchMixin,
    WindowItemMenuMixin,
    WindowActionsMixin,
    WindowLyricsMixin,
    WindowPlaybackMixin,
    WindowAutoplayMixin,
    WindowPlaybackRecoveryMixin,
    WindowOptionalMixin,
    WindowSocialMixin,
    WindowAccountMixin,
    Adw.ApplicationWindow,
):
    def __init__(self, app: Adw.Application):
        super().__init__(
            application=app, title=_("Harmonia"), default_width=1080, default_height=760
        )
        self.storage = open_storage()
        self.preferences = Preferences.load(self.storage)
        self._initialize_social()
        self.youtube = YouTubeMusicService(self.storage)
        self.lyrics_resolver = LyricsResolver(self.youtube.lyrics)
        self.translation_client = GoogleTranslationClient()
        self._load_lyrics_settings()
        self.downloads = DownloadManager(
            self.storage,
            self.youtube,
            lambda record: GLib.idle_add(self._download_updated, record),
        )
        self.sections = self.storage.load_library()
        self.home_sections = self.storage.load_home()
        self.explore_data = self.storage.load_explore()
        self._initialize_state()
        self._build_layout()
        self._start_player(app)
        build_player_bar(self)
        self._add_compact_breakpoint()
        build_expanded_player(self)
        self._start_up()
        # Last: the video layer wraps the expanded player's artwork, built above.
        self._video_feature_init()

    def _load_lyrics_settings(self) -> None:
        self.lyrics_provider = normalize_lyrics_provider(
            self.storage.get_setting("lyrics_provider", "auto")
        )
        try:
            self.lyrics_offset_ms = int(self.storage.get_setting("lyrics_offset_ms", "0"))
        except ValueError:
            self.lyrics_offset_ms = 0
        self.current_lyrics_document: LyricsDocument | None = None
        self._lyrics_item_id: str | None = None
        self._lyric_views: list[dict] = []
        self._active_lyric_index = -1

    def _initialize_state(self) -> None:
        """Defaults of the queue, playback, requests and page state."""
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
        self._icon_settings_handler = 0
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
        self.detail_track_rows: list[DetailTrackRow] = []
        self.home_song_rows: list[HomeSongRow] = []
        self.shuffle_buttons: list[Gtk.Button] = []
        self.repeat_buttons: list[Gtk.Button] = []
        self.like_buttons: list[Gtk.Button] = []
        self.current_liked = False

    def _build_layout(self) -> None:
        """Toasts over the ambient background, header, navigation pane and pages."""
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
        build_header(self)
        self._load_account_avatar(
            self.storage.get_setting("account_avatar_url", "") if self.storage.load_cookie() else ""
        )
        self.main_shell = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.main_shell.set_vexpand(True)
        build_sidebar(self)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        # Pages paint their own backgrounds; clipping keeps a theme's rounded
        # content corner (Windows 11) visible over them.
        self.stack.set_overflow(Gtk.Overflow.HIDDEN)
        self.main_shell.append(self.stack)
        self.root.append(self.main_shell)

    def _start_player(self, app: Adw.Application) -> None:
        """The GStreamer player and its desktop media controls (MPRIS)."""
        self.player = CrossfadingPlayer(self._player_state, self._player_error, self._play_next)
        # No crossfade while a video plays in sync with the audio or a cast
        # device has the track.
        self.player.crossfade_allowed = lambda: (
            getattr(self, "_media_mode", "audio") == "audio"
            and getattr(self, "cast_renderer", None) is None
        )
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

    def _add_compact_breakpoint(self) -> None:
        # A single breakpoint covers both the compact navigation and the compact
        # player bar; a narrower duplicate would only repeat these setters.
        compact_player = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 900px"))
        compact_player.add_setter(self.sidebar, "visible", False)
        compact_player.add_setter(self.sidebar_separator, "visible", False)
        compact_player.add_setter(self.compact_menu, "visible", True)
        compact_player.add_setter(self.footer_secondary, "visible", False)
        compact_player.add_setter(self.player_bar, "spacing", 8)
        self.add_breakpoint(compact_player)

    def _start_up(self) -> None:
        """Apply the preferences, show the first page and resume the session."""
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

    def _set_active_nav(self, key: str) -> None:
        viewport = self.sidebar_scroll.get_child()
        for name, button in self.nav_buttons.items():
            if name == key:
                button.add_css_class("sidebar-active")
                # Keep the active entry visible when the navigation list scrolls.
                if isinstance(viewport, Gtk.Viewport) and hasattr(viewport, "scroll_to"):
                    viewport.scroll_to(button, None)
            else:
                button.remove_css_class("sidebar-active")

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
        self.now_subtitle.show_item(None, _("Escolha uma faixa para começar"))
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
        self.expanded_subtitle.show_item(item, subtitle or "YouTube Music")
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
        # The description is Pango markup; callers pass plain text such as a
        # track title, which may hold a bare "&".
        status = Adw.StatusPage(icon_name=icon, title=title, description=escape(description))
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
        self.expanded_related_container.append(
            queue_view.expanded_content(
                self.queue,
                self.queue_index,
                self.related_items,
                self._queue_actions(select=self._select_expanded_queue_item),
            )
        )

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
                deliver_to_main(self._history_loaded, remote, None)
            except Exception as exc:
                deliver_to_main(self._history_loaded, [], str(exc))

        threading.Thread(target=worker, daemon=True, name="account-history").start()


class HarmoniaApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_startup(self):
        Adw.Application.do_startup(self)
        Gtk.Window.set_default_icon_name(APP_ID)
        # The theme controller owns style.css and the colour scheme. The default
        # theme is dark, so libadwaita's own widgets match it until the window
        # applies the saved preference.
        self.theme_controller = GtkThemeController(Gdk.Display.get_default())
        self.theme_controller.apply(DEFAULT_THEME)

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
