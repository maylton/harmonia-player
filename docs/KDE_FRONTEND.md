# Harmonia Qt/Kirigami frontend

This branch introduces an experimental native KDE Plasma frontend while keeping the existing GTK4/libadwaita application intact.

## Architecture

The two frontends share the same Python core:

- InnerTube client
- `YouTubeMusicService`
- models
- SQLite storage/cache
- account/session storage

The UI and playback surface are desktop-specific:

- GNOME and other desktops: GTK4/libadwaita + GStreamer
- KDE Plasma: Qt 6 + PySide6 + Kirigami + Qt Multimedia

`harmonia.frontend` detects Plasma from the XDG desktop environment and selects Qt when PySide6 is available. `--gtk`, `--qt`, or `HARMONIA_FRONTEND=gtk|qt` can override automatic selection.

## Build on KDE Linux

```bash
git fetch origin
git switch feature/qt-kirigami-frontend
git pull

flatpak-builder build-kde \
  --user \
  --install-deps-from=flathub-apps-built-locally \
  --force-clean \
  --ccache \
  --install \
  io.github.harmonia.Harmonia.KDE.yml
```

Run normally:

```bash
flatpak run io.github.harmonia.Harmonia
```

On Plasma this should select the Kirigami frontend automatically.

Force one frontend for debugging:

```bash
flatpak run io.github.harmonia.Harmonia --qt
flatpak run io.github.harmonia.Harmonia --gtk
```

## Current Qt vertical slice

Implemented:

- native Kirigami application window
- Plasma/Breeze icons and system colors
- Home sections from the existing Harmonia cache/service
- Library categories and grid
- universal search
- direct song/video playback with Qt Multimedia
- persistent player bar
- play/pause, previous/next, seek and volume
- reuse of the existing Harmonia session through Secret Service when available
- manual cookie fallback
- automatic Plasma detection with GTK fallback

Still to port before frontend parity:

- album, artist and playlist detail navigation
- Explore
- integrated Qt WebEngine login
- MPRIS service for the Qt playback backend
- queue/radio/autoplay parity
- lyrics UI
- downloads UI
- preferences UI
- history and local-library surfaces
- advanced GStreamer DSP features (EQ, normalization, speed/pitch and silence removal) or Qt equivalents

The GTK frontend remains the reference implementation until these items reach parity.
