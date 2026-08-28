from __future__ import annotations

import logging
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
from .qt_auth import QtAuthController
from .qt_backend import HarmoniaQtBackend
from .qt_integrated_playback import QtIntegratedPlaybackController
from .qt_integrations import QtIntegrationsController
from .qt_media_variants import OfficialVideoQtController
from .qt_video import create_qml6_video_sink

APP_ID = "io.github.harmonia.Harmonia"
LOGGER = logging.getLogger(__name__)


def _drain_glib_context() -> None:
    """Let GLib helpers progress without a second main loop."""
    context = GLib.MainContext.default()
    for _ in range(64):
        if not context.pending():
            break
        context.iteration(False)


def _application_icon() -> QIcon:
    """Resolve the installed icon before falling back to the theme."""
    data_dirs: list[Path] = []
    for value in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"):
        value = value.strip()
        if value:
            data_dirs.append(Path(value))

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

    # qml6glsink and Qt Quick must share the same OpenGL context.
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    QtWebEngineQuick.initialize()

    app = QApplication(sys.argv)
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(_application_icon())

    # Creating the sink before loading QML registers GstGLQt6VideoItem.
    video_sink = create_qml6_video_sink()

    glib_timer = QTimer()
    glib_timer.setInterval(10)
    glib_timer.timeout.connect(_drain_glib_context)
    glib_timer.start()

    engine = QQmlApplicationEngine()

    qt_backend_module.QtPlaybackController = QtIntegratedPlaybackController
    backend = HarmoniaQtBackend(engine)
    auth = QtAuthController(engine)
    integrations = QtIntegrationsController(backend, backend._executor, engine)
    video = OfficialVideoQtController(backend, video_sink, engine)
    auth.cookieReady.connect(backend.connectCookie)

    context = engine.rootContext()
    context.setContextProperty("backend", backend)
    context.setContextProperty("auth", auth)
    context.setContextProperty("integrations", integrations)
    context.setContextProperty("videoBackend", video)
    context.setContextProperty("preferences", backend.settings)

    qml_file = Path(__file__).with_name("qml") / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_file)))
    if not engine.rootObjects():
        video.shutdown()
        integrations.shutdown()
        backend.shutdown()
        raise RuntimeError("Qt/Kirigami frontend failed to load its QML root object")

    for root in engine.rootObjects():
        if isinstance(root, QQuickWindow):
            LOGGER.debug(
                "Qt graphics API: requested=%s effective=%s renderer=%s",
                QSGRendererInterface.GraphicsApi.OpenGL,
                root.graphicsApi(),
                root.rendererInterface().graphicsApi(),
            )

    app.aboutToQuit.connect(video.shutdown)
    app.aboutToQuit.connect(integrations.shutdown)
    app.aboutToQuit.connect(backend.shutdown)
    return app.exec()
