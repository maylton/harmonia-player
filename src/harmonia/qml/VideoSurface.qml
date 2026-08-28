import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import org.freedesktop.gstreamer.Qt6GLVideoItem 1.0

Item {
    id: root
    clip: true

    Rectangle {
        anchors.fill: parent
        color: "black"
        radius: Math.max(6, Kirigami.Units.cornerRadius)
        z: -1
    }

    GstGLQt6VideoItem {
        id: videoItem
        objectName: "harmoniaVideoItem"
        anchors.fill: parent

        Component.onCompleted: Qt.callLater(function() {
            videoBackend.registerSurface(videoItem)
        })
    }

    Controls.BusyIndicator {
        anchors.centerIn: parent
        running: visible
        visible: videoBackend.loading
        z: 2
    }

    Kirigami.PlaceholderMessage {
        anchors.centerIn: parent
        width: Math.min(parent.width * 0.8, Kirigami.Units.gridUnit * 18)
        visible: !videoBackend.outputReady && !videoBackend.loading
        text: "Vídeo indisponível"
        explanation: videoBackend.outputError.length > 0
                     ? videoBackend.outputError
                     : "A saída de vídeo do GStreamer não está disponível."
        icon.name: "video-x-generic"
        z: 2
    }
}
