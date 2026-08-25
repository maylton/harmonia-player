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


def main() -> int:
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "org.kde.desktop")

    app = QApplication(sys.argv)
    QCoreApplication.setApplicationName("Harmonia")
    QCoreApplication.setOrganizationName("Harmonia")
    QCoreApplication.setOrganizationDomain("io.github.harmonia")
    app.setDesktopFileName(APP_ID)

    fallback = QIcon.fromTheme("audio-headphones")
    app.setWindowIcon(QIcon.fromTheme(APP_ID, fallback))

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

    qml_file = Path(__file__).with_name("qml") / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_file)))
    if not engine.rootObjects():
        backend.shutdown()
        return 1

    app.aboutToQuit.connect(backend.shutdown)
    return app.exec()
