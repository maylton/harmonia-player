from __future__ import annotations

import os
import sys
from pathlib import Path

from gi.repository import GLib
from PySide6.QtCore import QCoreApplication, QTimer, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication

from .qt_backend import HarmoniaQtBackend

APP_ID = "io.github.harmonia.Harmonia"


def _drain_glib_context() -> None:
    """Let shared Gio/GStreamer helpers progress without a second main loop."""
    context = GLib.MainContext.default()
    for _ in range(64):
        if not context.pending():
            break
        context.iteration(False)


def _application_icon() -> QIcon:
    """Resolve the installed Harmonia icon before falling back to the theme."""
    data_dirs: list[Path] = []
    for value in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"):
        value = value.strip()
        if value:
            data_dirs.append(Path(value))

    # Flatpak installs application data below /app/share. Keep it explicit in
    # case the desktop theme does not include that directory in QIcon's lookup.
    flatpak_share = Path("/app/share")
    if flatpak_share not in data_dirs:
        data_dirs.insert(0, flatpak_share)

    theme_paths = list(QIcon.themeSearchPaths())
    for data_dir in data_dirs:
        icon_dir = str(data_dir / "icons")
        if icon_dir not in theme_paths:
            theme_paths.append(icon_dir)
    QIcon.setThemeSearchPaths(theme_paths)

    themed = QIcon.fromTheme(APP_ID)
    if not themed.isNull():
        return themed

    sizes = ("256x256", "128x128", "64x64", "48x48", "32x32", "16x16")
    for data_dir in data_dirs:
        for size in sizes:
            candidate = data_dir / "icons" / "hicolor" / size / "apps" / f"{APP_ID}.png"
            if candidate.is_file():
                return QIcon(str(candidate))

    # Source-tree fallback for local development outside Meson/Flatpak.
    repository_root = Path(__file__).resolve().parents[2]
    for size in sizes:
        candidate = repository_root / "data" / "icons" / "hicolor" / size / "apps" / f"{APP_ID}.png"
        if candidate.is_file():
            return QIcon(str(candidate))

    return QIcon.fromTheme("audio-headphones")


def main() -> int:
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "org.kde.desktop")

    app = QApplication(sys.argv)
    QCoreApplication.setApplicationName("Harmonia")
    QCoreApplication.setOrganizationName("Harmonia")
    QCoreApplication.setOrganizationDomain("io.github.harmonia")
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(_application_icon())

    # The shared player, Secret Service and MPRIS implementation use GLib/Gio.
    # Pumping the default context from Qt keeps one event loop and lets both
    # frontends reuse the same non-visual helpers.
    glib_timer = QTimer()
    glib_timer.setInterval(10)
    glib_timer.timeout.connect(_drain_glib_context)
    glib_timer.start()

    engine = QQmlApplicationEngine()
    backend = HarmoniaQtBackend(engine)
    engine.rootContext().setContextProperty("backend", backend)
    # Appearance belongs to the existing preference controller rather than the
    # broad QML facade. Both GTK and Qt therefore read/write the same settings.
    engine.rootContext().setContextProperty("preferences", backend.settings)

    qml_file = Path(__file__).with_name("qml") / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_file)))
    if not engine.rootObjects():
        backend.shutdown()
        raise RuntimeError("Qt/Kirigami frontend failed to load its QML root object")

    app.aboutToQuit.connect(backend.shutdown)
    return app.exec()
