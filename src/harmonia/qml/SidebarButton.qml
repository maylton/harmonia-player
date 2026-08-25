import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Controls.AbstractButton {
    id: root

    property string iconName: ""
    property string fallbackIcon: "application-x-executable"

    hoverEnabled: true
    checkable: true
    implicitHeight: Kirigami.Units.gridUnit * 2.15

    background: Rectangle {
        radius: Math.max(6, Kirigami.Units.cornerRadius)
        color: root.checked
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
            Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
            Layout.preferredHeight: width
            source: root.iconName
            fallback: root.fallbackIcon
            isMask: true
            color: root.checked ? Kirigami.Theme.textColor : Kirigami.Theme.disabledTextColor
            selected: root.checked
        }

        Controls.Label {
            Layout.fillWidth: true
            text: root.text
            color: root.checked ? Kirigami.Theme.textColor : Kirigami.Theme.disabledTextColor
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }
    }
}
