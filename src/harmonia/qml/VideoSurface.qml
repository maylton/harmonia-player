import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Item {
    id: root
    clip: true

    Component.onCompleted: videoBackend.registerSurface(root)
    onVisibleChanged: videoBackend.refreshAvailability()

    Rectangle {
        anchors.fill: parent
        color: "black"
        radius: Math.max(6, Kirigami.Units.cornerRadius)
        z: -1
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
        visible: !videoBackend.available && !videoBackend.loading
        text: "Vídeo indisponível"
        explanation: "A saída de vídeo do GStreamer não está disponível para esta faixa."
        icon.name: "video-x-generic"
        z: 2
    }
}
