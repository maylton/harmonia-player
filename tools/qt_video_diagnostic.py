#!/usr/bin/env python3
"""Small Qt/GStreamer video-output diagnostic.

Examples:
    python tools/qt_video_diagnostic.py --mode synthetic
    python tools/qt_video_diagnostic.py --mode playbin --uri /tmp/sample.mp4
    python tools/qt_video_diagnostic.py --mode dash --uri http://127.0.0.1:...
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import gi
import shiboken6

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402
from PySide6.QtCore import QObject, QTimer, Signal, Slot  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harmonia.qt_video import _set_foreign_pointer_property  # noqa: E402

LOGGER = logging.getLogger("harmonia.qt_video_diagnostic")

QML = """
import QtQuick
import QtQuick.Window
import org.freedesktop.gstreamer.Qt6GLVideoItem 1.0

Window {
    width: 960
    height: 540
    visible: true
    color: "black"
    GstGLQt6VideoItem {
        id: video
        objectName: "diagnosticVideoItem"
        anchors.fill: parent
    }
    Component.onCompleted: diagnostic.attach(video)
}
"""


class Diagnostic(QObject):
    prepare_requested = Signal(object, object)

    def __init__(self, mode: str, uri: str | None) -> None:
        super().__init__()
        self.mode = mode
        self.uri = uri
        self.pipeline = None
        self.sink = None
        self.output = None
        self.prepare_requested.connect(self._start_when_ready)

    @Slot(QObject)
    def attach(self, item: QObject) -> None:
        window = item.window()
        LOGGER.info("Qt video surface registered")
        if window is None:
            LOGGER.error("Qt diagnostic item has no QQuickWindow")
            return
        LOGGER.info(
            "Qt video QQuickWindow available: graphicsApi=%s rendererGraphicsApi=%s",
            window.graphicsApi(),
            window.rendererInterface().graphicsApi(),
        )
        window.sceneGraphInitialized.connect(lambda: self.prepare_requested.emit(item, window))
        if window.isSceneGraphInitialized():
            self.prepare_requested.emit(item, window)

    def _start_when_ready(self, item: QObject, window: QQuickWindow) -> None:
        if self.pipeline is not None:
            return
        LOGGER.info("Qt scene graph initialized")
        LOGGER.info("Qt GL sink preparation starting")
        Gst.init(None)
        pointer = int(shiboken6.getCppPointer(item)[0])
        if self.mode == "synthetic":
            self.pipeline = Gst.parse_launch(
                "videotestsrc is-live=true pattern=ball ! videoconvert ! glupload ! "
                "glcolorconvert ! qml6glsink name=diagnostic-sink"
            )
            self.sink = self.pipeline.get_by_name("diagnostic-sink")
            self.output = self.pipeline
        else:
            if not self.uri:
                raise SystemExit("--uri is required for --mode file/playbin/dash")
            self.sink = Gst.ElementFactory.make("qml6glsink", "diagnostic-sink")
            self.output = Gst.ElementFactory.make("glsinkbin", "diagnostic-glsinkbin")
            self.output.set_property("sink", self.sink)
            self.pipeline = Gst.ElementFactory.make("playbin", "diagnostic-playbin")
            self.pipeline.set_property("uri", self.uri)
            self.pipeline.set_property("video-sink", self.output)

        if self.sink is None:
            raise SystemExit("qml6glsink is unavailable")
        _set_foreign_pointer_property(self.sink, "widget", pointer)
        sink_state = self.sink.set_state(Gst.State.READY)
        LOGGER.info("qml6glsink READY: %s", sink_state)
        if self.output is not self.pipeline:
            bin_state = self.output.set_state(Gst.State.READY)
            LOGGER.info("glsinkbin READY: %s", bin_state)
        if self.mode != "synthetic":
            playbin_state = self.pipeline.set_state(Gst.State.READY)
            LOGGER.info("playbin READY: %s", playbin_state)
        self.pipeline.get_bus().add_signal_watch()
        self.pipeline.get_bus().connect("message", self._message)
        result = self.pipeline.set_state(Gst.State.PLAYING)
        LOGGER.info("diagnostic PLAYING: %s", result)

    def _message(self, _bus, message) -> None:
        if message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            LOGGER.error("GStreamer error from %s: %s (%s)", message.src.get_name(), error, debug)
            QTimer.singleShot(0, QGuiApplication.quit)
        elif message.type == Gst.MessageType.EOS:
            LOGGER.info("GStreamer EOS")
            QTimer.singleShot(0, QGuiApplication.quit)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("synthetic", "file", "playbin", "dash"), default="synthetic")
    parser.add_argument("--uri")
    parser.add_argument("--seconds", type=float, default=8)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    app = QGuiApplication(sys.argv)
    Gst.init(None)
    registration_sink = Gst.ElementFactory.make("qml6glsink", "diagnostic-registration-sink")
    if registration_sink is None:
        LOGGER.error("qml6glsink is unavailable")
        return 1
    diagnostic = Diagnostic(args.mode, args.uri)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("diagnostic", diagnostic)
    engine.loadData(QML.encode("utf-8"))
    if not engine.rootObjects():
        return 1
    QTimer.singleShot(max(1, int(args.seconds * 1000)), app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
