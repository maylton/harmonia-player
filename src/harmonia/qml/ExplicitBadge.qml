import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

// YouTube Music's "E" for explicit content, as the GTK frontend draws it.
Rectangle {
    id: badge

    property bool large: false

    implicitWidth: Math.max(implicitHeight, label.implicitWidth + (large ? 10 : 6))
    implicitHeight: label.implicitHeight + (large ? 2 : 0)
    radius: large ? 4 : 3
    color: Qt.rgba(Kirigami.Theme.textColor.r, Kirigami.Theme.textColor.g,
                   Kirigami.Theme.textColor.b, 0.16)

    Controls.Label {
        id: label
        anchors.centerIn: parent
        text: "E"
        font.pixelSize: badge.large ? 14 : 10
        font.weight: Font.ExtraBold
        opacity: 0.78
    }

    Controls.ToolTip.text: i18n.tr("Conteúdo explícito")
    Controls.ToolTip.visible: hover.hovered
    HoverHandler { id: hover }
}
