import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Controls.Dialog {
    id: root

    title: "Letras"
    modal: false
    standardButtons: Controls.Dialog.Close
    width: Math.min(
        parent ? parent.width - Kirigami.Units.gridUnit * 4 : Kirigami.Units.gridUnit * 34,
        Kirigami.Units.gridUnit * 34
    )
    height: Math.min(
        parent ? parent.height - Kirigami.Units.gridUnit * 4 : Kirigami.Units.gridUnit * 38,
        Kirigami.Units.gridUnit * 38
    )
    x: parent ? parent.width - width - Kirigami.Units.gridUnit * 1.2 : 0
    y: parent ? (parent.height - height) / 2 : 0

    onOpened: backend.loadLyrics()

    contentItem: LyricsView {}
}
