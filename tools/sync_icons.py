#!/usr/bin/env python3
"""Vendor the optional Harmonia icon themes from Iconify.

The application never contacts Iconify at runtime. Run this script only when
updating the bundled assets, then review and commit the resulting SVG files.
Pass theme names to refresh only those:

    python3 tools/sync_icons.py HarmoniaFluent
"""

from __future__ import annotations

import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ICONS: dict[str, tuple[str, str]] = {
    "accessories-dictionary-symbolic": ("book-2", "menu-book-rounded", "book-open-20-regular"),
    "applications-multimedia-symbolic": ("apps", "apps-rounded", "apps-20-regular"),
    "audio-headphones-symbolic": ("headphones", "headphones-rounded", "headphones-20-regular"),
    "audio-input-microphone-symbolic": ("microphone", "mic-rounded", "mic-20-regular"),
    "audio-volume-high-symbolic": ("volume", "volume-up-rounded", "speaker-2-20-regular"),
    "audio-x-generic-symbolic": ("music", "music-note-rounded", "music-note-2-20-regular"),
    "avatar-default-symbolic": ("user-circle", "person-rounded", "person-20-regular"),
    "bookmark-new-symbolic": ("bookmark-plus", "bookmark-add-rounded", "bookmark-add-20-regular"),
    "contact-new-symbolic": ("user-plus", "person-add-rounded", "person-add-20-regular"),
    "dialog-error-symbolic": ("alert-circle", "error-rounded", "error-circle-20-regular"),
    "document-edit-symbolic": ("file-pencil", "edit-document-rounded", "document-edit-20-regular"),
    "document-open-recent-symbolic": ("history", "history-rounded", "history-20-regular"),
    "document-open-symbolic": ("file-description", "description-rounded", "document-20-regular"),
    "document-save-symbolic": ("device-floppy", "save-rounded", "save-20-regular"),
    "edit-copy-symbolic": ("copy", "content-copy-rounded", "copy-20-regular"),
    "emblem-ok-symbolic": ("circle-check", "check-circle-rounded", "checkmark-circle-20-regular"),
    "emblem-shared-symbolic": ("share", "share-rounded", "share-20-regular"),
    "find-location-symbolic": ("compass", "explore-rounded", "compass-northwest-20-regular"),
    "folder-download-symbolic": (
        "folder-down",
        "download-for-offline-rounded",
        "arrow-download-20-regular",
    ),
    "folder-music-symbolic": ("library", "library-music-rounded", "library-20-regular"),
    "go-down-symbolic": ("chevron-down", "keyboard-arrow-down-rounded", "chevron-down-20-regular"),
    "go-home-symbolic": ("home", "home-rounded", "home-20-regular"),
    "go-next-symbolic": ("chevron-right", "chevron-right-rounded", "chevron-right-20-regular"),
    "go-previous-symbolic": ("chevron-left", "chevron-left-rounded", "chevron-left-20-regular"),
    "go-up-symbolic": ("chevron-up", "keyboard-arrow-up-rounded", "chevron-up-20-regular"),
    "list-add-symbolic": (
        "playlist-add",
        "playlist-add-rounded",
        "text-bullet-list-add-20-regular",
    ),
    "list-remove-symbolic": (
        "playlist-x",
        "playlist-remove-rounded",
        "text-bullet-list-dismiss-20-regular",
    ),
    "media-optical-symbolic": ("disc", "album-rounded", "album-20-regular"),
    "media-playback-pause-symbolic": ("player-pause-filled", "pause-rounded", "pause-20-filled"),
    "media-playback-start-symbolic": ("player-play-filled", "play-arrow-rounded", "play-20-filled"),
    "media-playlist-consecutive-symbolic": (
        "playlist",
        "queue-music-rounded",
        "text-bullet-list-ltr-20-regular",
    ),
    "media-playlist-repeat-symbolic": ("repeat", "repeat-rounded", "arrow-repeat-all-20-regular"),
    "media-playlist-shuffle-symbolic": (
        "arrows-shuffle",
        "shuffle-rounded",
        "arrow-shuffle-20-regular",
    ),
    "media-skip-backward-symbolic": (
        "player-skip-back-filled",
        "skip-previous-rounded",
        "previous-20-filled",
    ),
    "media-skip-forward-symbolic": (
        "player-skip-forward-filled",
        "skip-next-rounded",
        "next-20-filled",
    ),
    "non-starred-symbolic": ("star", "star-outline-rounded", "star-20-regular"),
    "object-select-symbolic": ("check", "check-rounded", "checkmark-20-regular"),
    "open-menu-symbolic": ("menu-2", "menu-rounded", "navigation-20-regular"),
    "preferences-system-symbolic": ("settings", "settings-rounded", "settings-20-regular"),
    "preferences-system-time-symbolic": ("clock", "timer-rounded", "timer-20-regular"),
    "starred-symbolic": ("star-filled", "star-rounded", "star-20-filled"),
    "system-log-out-symbolic": ("logout", "logout-rounded", "sign-out-20-regular"),
    "system-search-symbolic": ("search", "search-rounded", "search-20-regular"),
    "user-trash-symbolic": ("trash", "delete-rounded", "delete-20-regular"),
    "view-fullscreen-symbolic": (
        "maximize",
        "fullscreen-rounded",
        "full-screen-maximize-20-regular",
    ),
    "view-list-symbolic": ("list", "format-list-bulleted-rounded", "list-20-regular"),
    "view-more-symbolic": ("dots", "more-horiz-rounded", "more-horizontal-20-regular"),
    "view-refresh-symbolic": ("refresh", "refresh-rounded", "arrow-sync-20-regular"),
    "window-close-symbolic": ("x", "close-rounded", "dismiss-20-regular"),
}

THEMES = {
    "HarmoniaMaterial": ("material-symbols", 1, "Material Symbols", "Apache-2.0"),
    # Windows' own icons; offered only on Windows (see host.ICON_STYLES).
    "HarmoniaFluent": ("fluent", 2, "Fluent UI System Icons", "MIT"),
}
# Icons only one theme replaces. The Windows caption buttons keep GTK's own
# icons in every other theme.
THEME_EXTRAS: dict[str, dict[str, str]] = {
    "HarmoniaFluent": {
        "window-minimize-symbolic": "subtract-20-regular",
        "window-maximize-symbolic": "maximize-20-regular",
        "window-restore-symbolic": "square-multiple-20-regular",
    },
}

ROOT = Path(__file__).resolve().parents[1]
ICONS_ROOT = ROOT / "src" / "harmonia" / "icons"
LICENSES = {  # theme -> (file in licenses/, upstream license URL)
    "HarmoniaMaterial": (
        "Material-Symbols-Apache-2.0.txt",
        "https://raw.githubusercontent.com/google/material-design-icons/master/LICENSE",
    ),
    "HarmoniaFluent": (
        "Fluent-UI-System-Icons-MIT.txt",
        "https://raw.githubusercontent.com/microsoft/fluentui-system-icons/main/LICENSE",
    ),
}


def theme_icons(theme: str) -> dict[str, str]:
    """Semantic GTK icon name -> upstream icon name, for one theme."""
    index = THEMES[theme][1]
    return {name: upstream[index] for name, upstream in ICONS.items()} | THEME_EXTRAS.get(theme, {})


def fetch(prefix: str, icon: str) -> str:
    query = urllib.parse.urlencode({"color": "#2e3436", "width": 16, "height": 16})
    request = urllib.request.Request(
        f"https://api.iconify.design/{prefix}/{icon}.svg?{query}",
        headers={"User-Agent": "Harmonia icon vendor script"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read().decode("utf-8")
    ET.fromstring(data)
    return data


def main(selected: list[str]) -> None:
    themes = [theme for theme in THEMES if not selected or theme in selected]
    for theme in themes:
        prefix, _mapping_index, upstream, license_id = THEMES[theme]
        directory = ICONS_ROOT / theme / "scalable" / "actions"
        directory.mkdir(parents=True, exist_ok=True)
        places = ICONS_ROOT / theme / "scalable" / "places"
        icons = theme_icons(theme)
        for semantic_name, upstream_name in icons.items():
            svg = fetch(prefix, upstream_name)
            notice = f"<!-- Source: Iconify {prefix}:{upstream_name}; {upstream} ({license_id}) -->"
            svg = svg.replace(">", f">{notice}", 1) + "\n"
            target = directory / f"{semantic_name}.svg"
            target.write_text(svg, encoding="utf-8")
            duplicate = places / target.name
            if duplicate.exists():
                duplicate.unlink()
        print(f"{theme}: {len(icons)} SVGs synchronized")
    licenses_dir = ROOT / "licenses"
    licenses_dir.mkdir(exist_ok=True)
    for theme in themes:
        filename, url = LICENSES[theme]
        request = urllib.request.Request(url, headers={"User-Agent": "Harmonia icon vendor script"})
        with urllib.request.urlopen(request, timeout=20) as response:
            text = response.read().decode("utf-8")
        (licenses_dir / filename).write_text(text.rstrip() + "\n", encoding="utf-8")
    print(f"Licenses: {len(themes)} synchronized")


if __name__ == "__main__":
    main(sys.argv[1:])
