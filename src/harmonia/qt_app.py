from __future__ import annotations

import os
import sys
from pathlib import Path

from gi.repository import GLib
from PySide6.QtCore import QCoreApplication, QTimer, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
from PySide6.QtWebEngineQuick import QtWebEngineQuick
from PySide6.QtWidgets import QApplication

from . import qt_backend as qt_backend_module
from .potoken import install_potoken_provider
from .qt_auth import QtAuthController
from .qt_backend import HarmoniaQtBackend
from .qt_integrated_playback import QtIntegratedPlaybackController
from .qt_integrations import QtIntegrationsController
from .qt_potoken import QtPoTokenProvider
from .qt_video import QtVideoController, create_qml6_video_sink

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

    QCoreApplication.setApplicationName("Harmonia")
    QCoreApplication.setOrganizationName("Harmonia")
    QCoreApplication.setOrganizationDomain("io.github.harmonia")
    # Qt Quick WebEngine requires initialization before QApplication creates
    # the graphics context used by Chromium's render process.
    QtWebEngineQuick.initialize()

    app = QApplication(sys.argv)
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(_application_icon())

    # Keep BotGuard in a dedicated off-the-record WebEngine page. Extraction
    # workers call it through a thread-safe provider, while all Chromium work
    # remains on Qt's GUI thread.
    potoken = QtPoTokenProvider(app)
    install_potoken_provider(potoken)

    # qml6glsink exchanges OpenGL textures directly with the Qt Quick scene
    # graph. Follow GStreamer's Qt6 example and request OpenGL before the first
    # QQuickWindow is constructed; otherwise Qt may choose Vulkan/RHI and the
    # two graphics contexts are not compatible.
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)

    # Creating qml6glsink before loading QML registers the
    # org.freedesktop.gstreamer.Qt6GLVideoItem module and its
    # GstGLQt6VideoItem type. Keep the element alive for the application's
    # lifetime and let QtVideoController bind it to the QML item below.
    video_sink = create_qml6_video_sink()

    # The shared player, Secret Service and MPRIS implementation use GLib/Gio.
    # Pumping the default context from Qt keeps one event loop and lets both
    # frontends reuse the same non-visual helpers.
    glib_timer = QTimer()
    glib_timer.setInterval(10)
    glib_timer.timeout.connect(_drain_glib_context)
    glib_timer.start()

    engine = QQmlApplicationEngine()

    # Keep HarmoniaQtBackend as the stable facade while selecting the Qt-only
    # playback specialization before the facade constructs its controllers.
    qt_backend_module.QtPlaybackController = QtIntegratedPlaybackController
    backend = HarmoniaQtBackend(engine)
    auth = QtAuthController(engine)
    integrations = QtIntegrationsController(backend, backend._executor, engine)
    video = QtVideoController(backend, video_sink, engine)
    auth.cookieReady.connect(backend.connectCookie)

    context = engine.rootContext()
    context.setContextProperty("backend", backend)
    context.setContextProperty("auth", auth)
    context.setContextProperty("integrations", integrations)
    context.setContextProperty("videoBackend", video)
    # Appearance belongs to the existing preference controller rather than the
    # broad QML facade. Both GTK and Qt therefore read/write the same settings.
    context.setContextProperty("preferences", backend.settings)

    qml_file = Path(__file__).with_name("qml") / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_file)))
    if not engine.rootObjects():
        video.shutdown()
        integrations.shutdown()
        backend.shutdown()
        install_potoken_provider(None)
        raise RuntimeError("Qt/Kirigami frontend failed to load its QML root object")

    # Integrations/video still use the backend player/executor, so close them
    # before HarmoniaQtBackend shuts those shared resources down.
    app.aboutToQuit.connect(video.shutdown)
    app.aboutToQuit.connect(integrations.shutdown)
    app.aboutToQuit.connect(backend.shutdown)
    app.aboutToQuit.connect(lambda: install_potoken_provider(None))
    return app.exec()
