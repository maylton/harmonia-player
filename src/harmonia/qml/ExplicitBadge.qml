import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

// YouTube Music's "E" for explicit content, as the GTK frontend draws it.
Rectangle {
    id: badge

    property bool large: false

    implicitWidth: Math.max(implicitHeight, label.implicitWidth + (large ? 6 : 4))
    implicitHeight: label.implicitHeight
    radius: large ? 3 : 2
    color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                   Kirigami.Theme.textColor.b, 0.13)

    Controls.Label {
        id: label
        anchors.centerIn: parent
        text: "E"
        font.pixelSize: badge.large ? 11 : 8
        font.weight: Font.Bold
        opacity: 0.7
    }

    Controls.ToolTip.text: i18n.tr("Conteúdo explícito")
    Controls.ToolTip.visible: hover.hovered
    HoverHandler { id: hover }
}
