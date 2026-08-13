#!/usr/bin/env python3
"""Vendor the two optional Harmonia icon themes from Iconify.

The application never contacts Iconify at runtime. Run this script only when
updating the bundled assets, then review and commit the resulting SVG files.
"""

from __future__ import annotations

import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ICONS: dict[str, tuple[str, str]] = {
    "accessories-dictionary-symbolic": ("book-2", "menu-book-rounded"),
    "applications-multimedia-symbolic": ("apps", "apps-rounded"),
    "audio-headphones-symbolic": ("headphones", "headphones-rounded"),
    "audio-input-microphone-symbolic": ("microphone", "mic-rounded"),
    "audio-volume-high-symbolic": ("volume", "volume-up-rounded"),
    "audio-x-generic-symbolic": ("music", "music-note-rounded"),
    "avatar-default-symbolic": ("user-circle", "person-rounded"),
    "bookmark-new-symbolic": ("bookmark-plus", "bookmark-add-rounded"),
    "contact-new-symbolic": ("user-plus", "person-add-rounded"),
    "dialog-error-symbolic": ("alert-circle", "error-rounded"),
    "document-edit-symbolic": ("file-pencil", "edit-document-rounded"),
    "document-open-recent-symbolic": ("history", "history-rounded"),
    "document-open-symbolic": ("file-description", "description-rounded"),
    "document-save-symbolic": ("device-floppy", "save-rounded"),
    "edit-copy-symbolic": ("copy", "content-copy-rounded"),
    "emblem-ok-symbolic": ("circle-check", "check-circle-rounded"),
    "find-location-symbolic": ("compass", "explore-rounded"),
    "folder-download-symbolic": ("folder-down", "download-for-offline-rounded"),
    "folder-music-symbolic": ("library", "library-music-rounded"),
    "go-down-symbolic": ("chevron-down", "keyboard-arrow-down-rounded"),
    "go-home-symbolic": ("home", "home-rounded"),
    "go-next-symbolic": ("chevron-right", "chevron-right-rounded"),
    "go-previous-symbolic": ("chevron-left", "chevron-left-rounded"),
    "go-up-symbolic": ("chevron-up", "keyboard-arrow-up-rounded"),
    "list-add-symbolic": ("playlist-add", "playlist-add-rounded"),
    "list-remove-symbolic": ("playlist-x", "playlist-remove-rounded"),
    "media-optical-symbolic": ("disc", "album-rounded"),
    "media-playback-pause-symbolic": ("player-pause-filled", "pause-rounded"),
    "media-playback-start-symbolic": ("player-play-filled", "play-arrow-rounded"),
    "media-playlist-consecutive-symbolic": ("playlist", "queue-music-rounded"),
    "media-playlist-repeat-symbolic": ("repeat", "repeat-rounded"),
    "media-playlist-shuffle-symbolic": ("arrows-shuffle", "shuffle-rounded"),
    "media-skip-backward-symbolic": ("player-skip-back-filled", "skip-previous-rounded"),
    "media-skip-forward-symbolic": ("player-skip-forward-filled", "skip-next-rounded"),
    "non-starred-symbolic": ("star", "star-outline-rounded"),
    "object-select-symbolic": ("check", "check-rounded"),
    "open-menu-symbolic": ("menu-2", "menu-rounded"),
    "preferences-system-symbolic": ("settings", "settings-rounded"),
    "preferences-system-time-symbolic": ("clock", "timer-rounded"),
    "starred-symbolic": ("star-filled", "star-rounded"),
    "system-log-out-symbolic": ("logout", "logout-rounded"),
    "system-search-symbolic": ("search", "search-rounded"),
    "user-trash-symbolic": ("trash", "delete-rounded"),
    "view-fullscreen-symbolic": ("maximize", "fullscreen-rounded"),
    "view-list-symbolic": ("list", "format-list-bulleted-rounded"),
    "view-more-symbolic": ("dots", "more-horiz-rounded"),
    "view-refresh-symbolic": ("refresh", "refresh-rounded"),
    "window-close-symbolic": ("x", "close-rounded"),
}

THEMES = {
    "HarmoniaMaterial": ("material-symbols", 1, "Material Symbols", "Apache-2.0"),
}

ROOT = Path(__file__).resolve().parents[1]
ICONS_ROOT = ROOT / "src" / "harmonia" / "icons"
LICENSES = {
    "Material-Symbols-Apache-2.0.txt": "https://raw.githubusercontent.com/google/material-design-icons/master/LICENSE",
}


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


def main() -> None:
    for theme, (prefix, mapping_index, upstream, license_id) in THEMES.items():
        directory = ICONS_ROOT / theme / "scalable" / "actions"
        directory.mkdir(parents=True, exist_ok=True)
        places = ICONS_ROOT / theme / "scalable" / "places"
        for semantic_name, upstream_names in ICONS.items():
            upstream_name = upstream_names[mapping_index]
            svg = fetch(prefix, upstream_name)
            notice = f"<!-- Source: Iconify {prefix}:{upstream_name}; {upstream} ({license_id}) -->"
            svg = svg.replace(">", f">{notice}", 1) + "\n"
            target = directory / f"{semantic_name}.svg"
            target.write_text(svg, encoding="utf-8")
            duplicate = places / target.name
            if duplicate.exists():
                duplicate.unlink()
        print(f"{theme}: {len(ICONS)} SVGs synchronized")
    licenses_dir = ROOT / "licenses"
    licenses_dir.mkdir(exist_ok=True)
    for filename, url in LICENSES.items():
        request = urllib.request.Request(url, headers={"User-Agent": "Harmonia icon vendor script"})
        with urllib.request.urlopen(request, timeout=20) as response:
            text = response.read().decode("utf-8")
        (licenses_dir / filename).write_text(text.rstrip() + "\n", encoding="utf-8")
    print(f"Licenses: {len(LICENSES)} synchronized")


if __name__ == "__main__":
    main()
