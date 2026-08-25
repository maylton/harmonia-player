# Harmonia Qt/Kirigami frontend

This branch adds a native Qt 6 / PySide6 / Kirigami frontend for KDE Plasma **without replacing the existing GTK4/libadwaita application**.

The goal is desktop-native presentation with one shared Harmonia core:

- KDE Plasma: Qt/Kirigami is selected automatically when PySide6 is available.
- GNOME and other desktops: GTK4/libadwaita remains the default frontend.
- In a native/source installation where both toolkit stacks are available, a Plasma Qt startup failure falls back to GTK unless Qt was explicitly forced.
- `--gtk`, `--qt`, and `HARMONIA_FRONTEND=gtk|qt` can override automatic selection when the requested toolkit is installed.

## Shared architecture

Both frontends reuse the same non-visual implementation instead of maintaining two music players:

- InnerTube client and `YouTubeMusicService`
- models and catalog data
- SQLite storage/cache and playback persistence
- Secret Service account/session storage
- downloads and offline media
- local media and local playlists
- lyrics providers, synchronized lyrics and translation
- `NativePlayer` / GStreamer playback
- audio processing preferences (EQ, normalization, speed, pitch and silence removal)
- MPRIS integration

The Qt presentation layer is split into small controllers rather than a second monolithic application backend:

- `qt_backend.py`: QML-facing facade and signal wiring
- `qt_catalog.py`: Home, Explore, search and detail/catalog state
- `qt_library.py`: library origins, local media and local playlists
- `qt_playback.py`: queue, playback state, radio and autoplay
- `qt_activity.py`: history, insights and lyrics state
- `qt_preferences.py`: shared settings, DSP, backup and cache controls
- `qt_mutations.py`: likes, subscriptions and remote playlist mutations
- `qt_presenters.py`: conversion of core models to QML-friendly data

The GTK frontend remains intact and continues using its GTK-specific presentation modules.

## Flatpak packaging model

The repository currently keeps two development manifests because Flatpak runtimes are toolkit-specific:

- `io.github.harmonia.Harmonia.yml` uses the GNOME/GTK runtime.
- `io.github.harmonia.Harmonia.KDE.yml` uses `org.kde.Platform` plus the PySide BaseApp.

They contain the same Harmonia source/core but provide different UI runtime dependencies. Therefore, **do not use `--gtk` as a regression test inside the KDE Flatpak** and do not expect `--qt` inside the GTK Flatpak. Test the other frontend from source/native packaging with its dependencies installed, or build the corresponding manifest.

The automatic selector is still useful: the normal executable chooses Qt on Plasma when PySide6 exists and otherwise chooses GTK. The KDE development Flatpak guarantees the Qt dependencies; the GTK Flatpak guarantees the GTK dependencies.

## Current Qt/Kirigami test scope

The KDE frontend currently includes:

- native Kirigami application window using Plasma/Breeze theme colors and icons
- Home and Explore
- universal search and suggestions
- YouTube Music, uploads, downloads, local media and podcasts library origins
- album, artist, remote playlist and local playlist details
- liked songs and library mutations
- remote playlist creation/rename/delete and add-to-playlist actions
- local playlist creation/rename/delete/reordering
- persistent player bar and expanded player
- shared GStreamer playback with play/pause, previous/next, seek, volume and stop
- queue editing, shuffle, repeat, radio and autoplay
- synchronized/plain lyrics, provider switching, offset adjustment, copy and translation
- downloads and offline playback
- history and listening insights
- preferences for streaming, locale, proxy, artwork cache and audio processing
- portable backup export/restore
- MPRIS integration with Plasma media controls
- reuse of an existing Harmonia Secret Service session when available
- manual YouTube Music cookie connection for a fresh Qt installation

An embedded Qt WebEngine login is intentionally not duplicated at this stage. The KDE frontend reuses the same stored account when possible and provides the manual cookie path for a new session.

## Build and install the KDE Flatpak

Make sure the `flathub` remote and `flatpak-builder` are available, then update the branch:

```bash
git fetch origin
git switch feature/qt-kirigami-frontend
git pull --ff-only
```

Build and install the KDE variant:

```bash
flatpak-builder build-kde \
  --user \
  --install-deps-from=flathub \
  --force-clean \
  --ccache \
  --install \
  io.github.harmonia.Harmonia.KDE.yml
```

Run normally from Plasma:

```bash
flatpak run io.github.harmonia.Harmonia
```

It should select the Qt/Kirigami frontend automatically. To make Qt startup errors explicit while debugging, force the same frontend:

```bash
flatpak run io.github.harmonia.Harmonia --qt
```

## Testing both selectors from source

If your host has both GTK and Qt/Kirigami dependencies installed, the same checkout can verify both frontends without changing the source tree:

```bash
PYTHONPATH=src python3 -m harmonia --qt
PYTHONPATH=src python3 -m harmonia --gtk
```

That is the appropriate regression check for confirming that the original GTK frontend is still healthy after the Qt work.

## Suggested KDE smoke test

After the first launch, check these paths before treating the KDE frontend as stable:

1. Confirm the window is visually native to Plasma and uses the current KDE color/icon theme.
2. Open Home, Explore, Library and Search and navigate into album/artist/playlist details.
3. Start a track and test play/pause, seek, previous/next, volume, shuffle and repeat.
4. Open the queue, reorder/remove entries and enable autoplay/related tracks.
5. Open the expanded player and Lyrics; test synced lyrics and seeking from a lyric line.
6. Test Downloads/offline playback and local media/local playlists if you use them.
7. Change an audio preference such as EQ or playback speed and confirm playback keeps working.
8. Check Plasma's media controls/MPRIS while Harmonia is playing.
9. Close and reopen Harmonia to verify queue/playback state persistence.
10. If both native toolkit stacks are installed, run the source checkout once with `--gtk` as the GTK regression check.

When reporting a Qt runtime problem, run the forced frontend from a terminal so the QML/Python error is visible:

```bash
flatpak run io.github.harmonia.Harmonia --qt
```
