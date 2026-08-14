# Harmonia

A native GTK 4 and libadwaita client for accessing your YouTube Music library on Linux. Harmonia is inspired by [Metrolist](https://github.com/MetrolistGroup/Metrolist) and ports its InnerTube integration to Python. The interface and playback engine are native; WebKitGTK is used only for the integrated sign-in flow.

> **Beta 0.1:** This is a testing release. InnerTube is not a public API and may change without notice. Use Harmonia only with your own account. The application never requests or stores your Google password.

## Features

- adaptive GTK 4 and libadwaita interface;
- automatic sign-in through an embedded WebKitGTK browser with secure session capture;
- manual cookie authentication as a fallback, using `SAPISIDHASH`;
- native synchronization of playlists, songs, albums, and artists;
- pagination through continuation tokens;
- local cache for accessing the latest synchronized library while offline;
- real artwork with local caching and background loading;
- playlist, album, and artist pages with complete track listings;
- native GStreamer playback with streams resolved through InnerTube;
- persistent player bar with playback controls;
- native search with playable results;
- playback queue with previous, next, and automatic track progression;
- radio and autoplay through `watch-next`, extending the queue with recommendations;
- MPRIS integration for GNOME, KDE, media keys, and desktop media controls;
- transactional SQLite persistence with automatic migration from the legacy JSON cache;
- bidirectional actions for liking songs, subscribing to artists, and managing playlists;
- local history of changes sent to YouTube Music;
- personalized Home powered by `FEmusic_home`, preserving the account's original sections;
- complete Home pagination, including mixtapes, old favorites, discoveries, and additional shelves;
- seekable progress bar, playback times, and a navigable queue;
- responsive desktop layout with a sidebar, persistent search, and a three-section player bar;
- square music artwork with centered cropping and circular treatment for artists;
- segmented library filters, volume, shuffle, and repeat controls;
- native YouTube Music lyrics with synchronized scrolling and SQLite caching;
- native Explore page with releases, charts, trends, videos, moods, and genres;
- credentials protected by the desktop Secret Service, including safe migration from legacy storage;
- preferences for quality, language, region, proxy, cache, and audio processing;
- equalizer, normalization, speed, pitch, silence removal, and sleep timer;
- optional ambient background and GTK or Material Expressive icon themes;
- Brazilian Portuguese and English interface translations;
- private annual listening statistics and on-device recap;
- portable backup and validated restore without account credentials or audio files;
- optional Last.fm now-playing and scrobbling with browser authorization;
- optional Discord Rich Presence through local IPC only;
- Listen Together sessions for synchronizing a queue and playback across Harmonia
  clients on the same local network;
- opt-in song recognition through AudD or a compatible configurable provider,
  using a temporary microphone sample that is deleted immediately;
- UPnP/DLNA renderer discovery, playback handoff, remote transport controls, and
  LAN streaming for downloaded or local tracks;
- Flatpak manifest, application icon, gettext catalogs, and AppStream metadata.

## Running from source

Harmonia requires Python 3.11 or later, PyGObject, GTK 4, libadwaita, WebKitGTK 6, GStreamer 1.0 with audio plugins, and libsecret.

```bash
PYTHONPATH=src python3 -m harmonia
```

When the application opens, select **Connect to YouTube Music** to authenticate through the embedded browser. Manual entry of the `Cookie` header remains available for environments without WebKitGTK.

## Installing with Meson

System-wide installation:

```bash
meson setup build --buildtype=release
meson compile -C build
sudo meson install -C build
```

Installation for the current user:

```bash
meson setup build-user --prefix="$HOME/.local" --buildtype=release
meson compile -C build-user
meson install -C build-user
```

## Installing on Linux

The portable installer detects Flatpak, configures Flathub for the current user,
downloads the official bundle, verifies its SHA-256 checksum, and installs the
required runtime automatically:

```bash
curl -fLO https://raw.githubusercontent.com/maylton/harmonia-player/main/install.sh
chmod +x install.sh
./install.sh --run
```

Inspecting a downloaded script before running it is recommended. Use
`./install.sh --help` for system-wide, local-bundle, and uninstall options. The
installer supports distributions based on APT, DNF/YUM, Zypper, Pacman, APK,
XBPS, and eopkg when Flatpak itself still needs to be installed.

To install a bundle downloaded manually from the corresponding GitHub release:

```bash
./install.sh --bundle ./Harmonia-0.1.0-beta.1-x86_64.flatpak --run
```

The bundle includes both Brazilian Portuguese and English translations. The
GNOME runtime is resolved separately by Flatpak.

## Tests

```bash
python3 -m pip install -e '.[test]' ruff
ruff check src tests tools
ruff format --check src tests tools
PYTHONPATH=src python3 -m pytest -q
```

Desktop integration and metadata can be checked with:

```bash
desktop-file-validate data/io.github.harmonia.Harmonia.desktop
appstreamcli validate --no-net --strict data/io.github.harmonia.Harmonia.metainfo.xml
```

## Project structure

- `src/harmonia/innertube.py`: authentication, requests, pagination, and API parsing;
- `src/harmonia/app.py`: window composition and libadwaita interface coordination;
- `src/harmonia/window_*.py`: domain-specific window behavior for Home, library,
  details, search, playback, lyrics, account, history, and preferences;
- `src/harmonia/services.py`: YouTube Music service orchestration;
- `src/harmonia/ui.py`: shared interaction components and visual primitives;
- `src/harmonia/player.py`: native GStreamer playback;
- `src/harmonia/together.py`: authenticated local-network playback sessions;
- `src/harmonia/recognition.py`: temporary audio capture and recognition providers;
- `src/harmonia/cast.py`: UPnP/DLNA discovery, transport, and local media relay;
- `src/harmonia/storage.py`: session and local cache persistence;
- `tests/`: protocol, parser, interface, playback, and integration tests.

## License

Harmonia is licensed under GPL-3.0-or-later. Metrolist is also licensed under GPL-3.0; Harmonia is an independent implementation based on the protocol's observable behavior and the architecture of the reference project.
