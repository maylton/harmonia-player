import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Controls.AbstractButton {
    id: root

    property string iconName: ""
    property string fallbackIcon: "application-x-executable"
    property bool selected: false

    hoverEnabled: true
    checkable: false
    implicitHeight: Kirigami.Units.gridUnit * 2.15

    background: Rectangle {
        radius: Math.max(6, Kirigami.Units.cornerRadius)
        color: root.selected
               ? Qt.rgba(
                     Kirigami.Theme.textColor.r,
                     Kirigami.Theme.textColor.g,
                     Kirigami.Theme.textColor.b,
                     0.13
                 )
               : root.hovered
                 ? Qt.rgba(
                       Kirigami.Theme.textColor.r,
                       Kirigami.Theme.textColor.g,
                       Kirigami.Theme.textColor.b,
                       0.075
                   )
                 : "transparent"
    }

    contentItem: RowLayout {
        spacing: Kirigami.Units.largeSpacing

        Kirigami.Icon {
            Layout.preferredWidth: Kirigami.Units.iconSizes.small
            Layout.preferredHeight: width
            source: root.iconName
            fallback: root.fallbackIcon
            isMask: true
            color: Kirigami.Theme.textColor
            opacity: root.selected ? 1.0 : 0.78
            selected: root.selected
        }

        Controls.Label {
            Layout.fillWidth: true
            text: root.text
            color: Kirigami.Theme.textColor
            opacity: root.selected ? 1.0 : 0.78
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }
    }
}
