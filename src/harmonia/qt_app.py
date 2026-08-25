from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication

from .qt_bridge import HarmoniaQtBridge

APP_ID = "io.github.harmonia.Harmonia"


def main() -> int:
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "org.kde.desktop")

    app = QApplication(sys.argv)
    QCoreApplication.setApplicationName("Harmonia")
    QCoreApplication.setOrganizationName("Harmonia")
    QCoreApplication.setOrganizationDomain("io.github.harmonia")
    app.setDesktopFileName(APP_ID)

    fallback = QIcon.fromTheme("audio-headphones")
    app.setWindowIcon(QIcon.fromTheme(APP_ID, fallback))

    engine = QQmlApplicationEngine()
    backend = HarmoniaQtBridge(engine)
    engine.rootContext().setContextProperty("backend", backend)

    qml_file = Path(__file__).with_name("qml") / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_file)))
    if not engine.rootObjects():
        backend.shutdown()
        return 1

    app.aboutToQuit.connect(backend.shutdown)
    return app.exec()
