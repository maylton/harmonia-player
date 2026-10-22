#!/usr/bin/env python3
"""Vendor the optional Harmonia icon themes from Iconify.

The application never contacts Iconify at runtime. Run this script only when
updating the bundled assets, then review and commit the resulting SVG files.
Pass theme names to refresh only those:

    python3 tools/sync_icons.py HarmoniaFluent
"""

from __future__ import annotations

import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ICONS: dict[str, tuple[str, str, str, str]] = {
    "accessories-dictionary-symbolic": (
        "book-2",
        "menu-book-rounded",
        "book-open-20-regular",
        "book",
    ),
    "applications-multimedia-symbolic": ("apps", "apps-rounded", "apps-20-regular", "app"),
    "audio-headphones-symbolic": (
        "headphones",
        "headphones-rounded",
        "headphones-20-regular",
        "headphones",
    ),
    "audio-input-microphone-symbolic": ("microphone", "mic-rounded", "mic-20-regular", "mic"),
    "audio-volume-high-symbolic": (
        "volume",
        "volume-up-rounded",
        "speaker-2-20-regular",
        "speaker-3",
    ),
    "audio-x-generic-symbolic": (
        "music",
        "music-note-rounded",
        "music-note-2-20-regular",
        "music-note",
    ),
    "avatar-default-symbolic": (
        "user-circle",
        "person-rounded",
        "person-20-regular",
        "person-crop-circle",
    ),
    "bookmark-new-symbolic": (
        "bookmark-plus",
        "bookmark-add-rounded",
        "bookmark-add-20-regular",
        "bookmark",
    ),
    "contact-new-symbolic": (
        "user-plus",
        "person-add-rounded",
        "person-add-20-regular",
        "person-badge-plus",
    ),
    "dialog-error-symbolic": (
        "alert-circle",
        "error-rounded",
        "error-circle-20-regular",
        "exclamationmark-circle",
    ),
    "document-edit-symbolic": (
        "file-pencil",
        "edit-document-rounded",
        "document-edit-20-regular",
        "pencil",
    ),
    "document-open-recent-symbolic": ("history", "history-rounded", "history-20-regular", "clock"),
    "document-open-symbolic": (
        "file-description",
        "description-rounded",
        "document-20-regular",
        "doc-text",
    ),
    "document-save-symbolic": ("device-floppy", "save-rounded", "save-20-regular", "floppy-disk"),
    "edit-copy-symbolic": ("copy", "content-copy-rounded", "copy-20-regular", "doc-on-doc"),
    "emblem-ok-symbolic": (
        "circle-check",
        "check-circle-rounded",
        "checkmark-circle-20-regular",
        "checkmark-circle",
    ),
    "emblem-shared-symbolic": ("share", "share-rounded", "share-20-regular", "square-arrow-up"),
    "find-location-symbolic": (
        "compass",
        "explore-rounded",
        "compass-northwest-20-regular",
        "compass",
    ),
    "folder-download-symbolic": (
        "folder-down",
        "download-for-offline-rounded",
        "arrow-download-20-regular",
        "arrow-down-circle",
    ),
    "folder-music-symbolic": (
        "library",
        "library-music-rounded",
        "library-20-regular",
        "music-albums",
    ),
    "go-down-symbolic": (
        "chevron-down",
        "keyboard-arrow-down-rounded",
        "chevron-down-20-regular",
        "chevron-down",
    ),
    "go-home-symbolic": ("home", "home-rounded", "home-20-regular", "house"),
    "go-next-symbolic": (
        "chevron-right",
        "chevron-right-rounded",
        "chevron-right-20-regular",
        "chevron-right",
    ),
    "go-previous-symbolic": (
        "chevron-left",
        "chevron-left-rounded",
        "chevron-left-20-regular",
        "chevron-left",
    ),
    "go-up-symbolic": (
        "chevron-up",
        "keyboard-arrow-up-rounded",
        "chevron-up-20-regular",
        "chevron-up",
    ),
    "list-add-symbolic": (
        "playlist-add",
        "playlist-add-rounded",
        "text-bullet-list-add-20-regular",
        "text-badge-plus",
    ),
    "list-remove-symbolic": (
        "playlist-x",
        "playlist-remove-rounded",
        "text-bullet-list-dismiss-20-regular",
        "text-badge-minus",
    ),
    "media-optical-symbolic": ("disc", "album-rounded", "album-20-regular", "smallcircle-circle"),
    "media-playback-pause-symbolic": (
        "player-pause-filled",
        "pause-rounded",
        "pause-20-filled",
        "pause-fill",
    ),
    "media-playback-start-symbolic": (
        "player-play-filled",
        "play-arrow-rounded",
        "play-20-filled",
        "play-fill",
    ),
    "media-playlist-consecutive-symbolic": (
        "playlist",
        "queue-music-rounded",
        "text-bullet-list-ltr-20-regular",
        "music-note-list",
    ),
    "media-playlist-repeat-symbolic": (
        "repeat",
        "repeat-rounded",
        "arrow-repeat-all-20-regular",
        "repeat",
    ),
    "media-playlist-shuffle-symbolic": (
        "arrows-shuffle",
        "shuffle-rounded",
        "arrow-shuffle-20-regular",
        "shuffle",
    ),
    "media-skip-backward-symbolic": (
        "player-skip-back-filled",
        "skip-previous-rounded",
        "previous-20-filled",
        "backward-end-fill",
    ),
    "media-skip-forward-symbolic": (
        "player-skip-forward-filled",
        "skip-next-rounded",
        "next-20-filled",
        "forward-end-fill",
    ),
    "non-starred-symbolic": ("star", "star-outline-rounded", "star-20-regular", "star"),
    "object-select-symbolic": ("check", "check-rounded", "checkmark-20-regular", "checkmark"),
    "open-menu-symbolic": ("menu-2", "menu-rounded", "navigation-20-regular", "line-horizontal-3"),
    "preferences-system-symbolic": ("settings", "settings-rounded", "settings-20-regular", "gear"),
    "preferences-system-time-symbolic": ("clock", "timer-rounded", "timer-20-regular", "timer"),
    "starred-symbolic": ("star-filled", "star-rounded", "star-20-filled", "star-fill"),
    "system-log-out-symbolic": (
        "logout",
        "logout-rounded",
        "sign-out-20-regular",
        "square-arrow-right",
    ),
    "system-search-symbolic": ("search", "search-rounded", "search-20-regular", "search"),
    "user-trash-symbolic": ("trash", "delete-rounded", "delete-20-regular", "trash"),
    "view-fullscreen-symbolic": (
        "maximize",
        "fullscreen-rounded",
        "full-screen-maximize-20-regular",
        "arrow-up-left-arrow-down-right",
    ),
    "view-list-symbolic": (
        "list",
        "format-list-bulleted-rounded",
        "list-20-regular",
        "list-bullet",
    ),
    "view-more-symbolic": ("dots", "more-horiz-rounded", "more-horizontal-20-regular", "ellipsis"),
    "view-refresh-symbolic": (
        "refresh",
        "refresh-rounded",
        "arrow-sync-20-regular",
        "arrow-clockwise",
    ),
    "window-close-symbolic": ("x", "close-rounded", "dismiss-20-regular", "xmark"),
}

THEMES = {
    "HarmoniaMaterial": ("material-symbols", 1, "Material Symbols", "Apache-2.0"),
    # Windows' own icons; offered only on Windows (see host.ICON_STYLES).
    "HarmoniaFluent": ("fluent", 2, "Fluent UI System Icons", "MIT"),
    # Apple's SF Symbols may not be redistributed; Framework7's are drawn after iOS.
    "HarmoniaFramework7": ("f7", 3, "Framework7 Icons", "MIT"),
}
# Freedesktop icon themes already use Harmonia's icon names, so their files are
# taken from the upstream repository as they are: (URL with {context}, {size}
# and {name}, sizes to try, upstream, license). A few names they lack map to
# their closest icon.
FREEDESKTOP_THEMES = {
    "HarmoniaBreeze": (
        "https://raw.githubusercontent.com/KDE/breeze-icons/master/icons/{context}/{size}/{name}.svg",
        ("16", "22"),
        "Breeze Icons (KDE)",
        "LGPL-3.0-or-later",
    ),
    "HarmoniaPapirus": (
        "https://raw.githubusercontent.com/PapirusDevelopmentTeam/papirus-icon-theme/master"
        "/Papirus/{size}/symbolic/{context}/{name}-symbolic.svg",
        ("16x16",),
        "Papirus Icon Theme",
        "GPL-3.0-only",
    ),
}
FREEDESKTOP_CONTEXTS = (
    "actions",
    "places",
    "status",
    "devices",
    "apps",
    "emblems",
    "categories",
    "mimetypes",
)
FREEDESKTOP_ALIASES: dict[str, dict[str, str]] = {
    # Breeze draws some of these names in colour (the System Settings app,
    # file types, emblems), which a symbolic icon would fill in one flat
    # shape; its monochrome action icons stand in for them.
    "HarmoniaBreeze": {
        "accessories-dictionary-symbolic": "translate",
        "audio-x-generic-symbolic": "media-album-track",
        "dialog-error-symbolic": "dialog-cancel",
        "emblem-shared-symbolic": "document-share",
        "preferences-system-symbolic": "configure",
        "applications-multimedia-symbolic": "media-playlist-play",
        "avatar-default-symbolic": "user-identity",
        "emblem-ok-symbolic": "dialog-ok-apply",
        "media-playlist-consecutive-symbolic": "media-playlist-play",
        "object-select-symbolic": "dialog-ok-apply",
        "open-menu-symbolic": "application-menu",
        "preferences-system-time-symbolic": "chronometer",
        "view-list-symbolic": "view-list-details",
        "view-more-symbolic": "overflow-menu",
    },
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
# Names Harmonia uses that adwaita-icon-theme 51 moved to AdwaitaLegacy. A copy
# at the root of the bundled icon folder is an unthemed icon, which GTK only
# uses when no theme in the lookup has the name, so it fills the gap without
# replacing any theme's own icon.
UNTHEMED_FALLBACKS = ("emblem-ok-symbolic", "emblem-shared-symbolic")
FALLBACK_THEME = "HarmoniaMaterial"
LICENSES = {  # theme -> (file in licenses/, upstream license URL)
    "HarmoniaMaterial": (
        "Material-Symbols-Apache-2.0.txt",
        "https://raw.githubusercontent.com/google/material-design-icons/master/LICENSE",
    ),
    "HarmoniaFluent": (
        "Fluent-UI-System-Icons-MIT.txt",
        "https://raw.githubusercontent.com/microsoft/fluentui-system-icons/main/LICENSE",
    ),
    "HarmoniaFramework7": (
        "Framework7-Icons-MIT.txt",
        "https://raw.githubusercontent.com/framework7io/framework7-icons/master/LICENSE",
    ),
    "HarmoniaBreeze": (
        "Breeze-Icons-LGPL-3.0.txt",
        "https://raw.githubusercontent.com/KDE/breeze-icons/master/COPYING-ICONS",
    ),
    "HarmoniaPapirus": (
        "Papirus-Icon-Theme-GPL-3.0.txt",
        "https://raw.githubusercontent.com/PapirusDevelopmentTeam/papirus-icon-theme/master/LICENSE",
    ),
}


def theme_icons(theme: str) -> dict[str, str]:
    """Semantic GTK icon name -> upstream icon name, for one theme."""
    if theme in FREEDESKTOP_THEMES:
        aliases = FREEDESKTOP_ALIASES.get(theme, {})
        return {name: aliases.get(name, name.removesuffix("-symbolic")) for name in ICONS}
    index = THEMES[theme][1]
    return {name: upstream[index] for name, upstream in ICONS.items()} | THEME_EXTRAS.get(theme, {})


def _download(url: str) -> str | None:
    request = urllib.request.Request(url, headers={"User-Agent": "Harmonia icon vendor script"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def fetch_freedesktop(theme: str, icon: str) -> tuple[str, str]:
    """The SVG of ``icon`` and where in the upstream tree it was found.

    Git keeps symlinks as files holding their target, which is followed.
    """
    template, sizes, _upstream, _license = FREEDESKTOP_THEMES[theme]
    for size in sizes:
        for context in FREEDESKTOP_CONTEXTS:
            url = template.format(context=context, size=size, name=icon)
            data = _download(url)
            for _hop in range(4):
                if data is None or data.lstrip().startswith("<"):
                    break
                url = urllib.parse.urljoin(url, data.strip())
                data = _download(url)
            if data is not None:
                # KDE colours icons through a stylesheet and currentColor; GTK
                # recolours symbolic icons from a plain fill.
                data = re.sub(r"<style[^>]*>.*?</style>", "", data, flags=re.S)
                data = data.replace("currentColor", "#2e3436")
                ET.fromstring(data)
                return data, url.split("/master/", 1)[1]
    raise LookupError(f"{theme}: {icon} não foi encontrado")


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


def write_unthemed_fallbacks() -> None:
    source = ICONS_ROOT / FALLBACK_THEME / "scalable" / "actions"
    for name in UNTHEMED_FALLBACKS:
        shutil.copyfile(source / f"{name}.svg", ICONS_ROOT / f"{name}.svg")
    print(f"Unthemed fallbacks: {len(UNTHEMED_FALLBACKS)} copied from {FALLBACK_THEME}")


def main(selected: list[str]) -> None:
    every = [*THEMES, *FREEDESKTOP_THEMES]
    themes = [theme for theme in every if not selected or theme in selected]
    for theme in themes:
        directory = ICONS_ROOT / theme / "scalable" / "actions"
        directory.mkdir(parents=True, exist_ok=True)
        places = ICONS_ROOT / theme / "scalable" / "places"
        icons = theme_icons(theme)
        for semantic_name, upstream_name in icons.items():
            if theme in FREEDESKTOP_THEMES:
                _template, _sizes, upstream, license_id = FREEDESKTOP_THEMES[theme]
                svg, path = fetch_freedesktop(theme, upstream_name)
                notice = f"<!-- Source: {upstream} {path} ({license_id}) -->"
            else:
                prefix, _mapping_index, upstream, license_id = THEMES[theme]
                svg = fetch(prefix, upstream_name)
                notice = (
                    f"<!-- Source: Iconify {prefix}:{upstream_name}; {upstream} ({license_id}) -->"
                )
            svg = svg.replace(">", f">{notice}", 1) + "\n"
            target = directory / f"{semantic_name}.svg"
            target.write_text(svg, encoding="utf-8")
            duplicate = places / target.name
            if duplicate.exists():
                duplicate.unlink()
        print(f"{theme}: {len(icons)} SVGs synchronized")
    if FALLBACK_THEME in themes:
        write_unthemed_fallbacks()
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
