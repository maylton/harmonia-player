"""The top-level pages, shared by the navigation pane and the compact menu."""

from __future__ import annotations

from collections.abc import Callable

from ..i18n import _
from ..window_constants import EXPLORE_ICON, LIKED_ICON

# The navigation pane puts this heading before the first of these pages.
YOUR_MUSIC_STARTS_AT = "songs"


def navigation_entries(window) -> tuple[tuple[str, str, str, Callable[[], None]], ...]:
    """(key, label, icon, open) of every top-level page, in navigation order."""
    return (
        ("home", _("Início"), "go-home-symbolic", window.show_home),
        ("explore", _("Explorar"), EXPLORE_ICON, window.show_explore),
        ("library", _("Biblioteca"), "folder-music-symbolic", window.show_library),
        ("songs", _("Músicas curtidas"), LIKED_ICON, lambda: window.show_category("songs")),
        (
            "playlists",
            _("Playlists"),
            "view-list-symbolic",
            lambda: window.show_category("playlists"),
        ),
        (
            "artists",
            _("Artistas"),
            "avatar-default-symbolic",
            lambda: window.show_category("artists"),
        ),
        ("history", _("Histórico"), "document-open-recent-symbolic", window.show_history),
        (
            "insights",
            _("Estatísticas"),
            "applications-multimedia-symbolic",
            window.show_insights,
        ),
        ("downloads", _("Downloads"), "folder-download-symbolic", window.show_downloads),
        ("settings", _("Preferências"), "preferences-system-symbolic", window.show_settings),
    )
