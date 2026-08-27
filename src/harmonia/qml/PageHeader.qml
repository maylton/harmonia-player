import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

RowLayout {
    id: root

    property string title: ""
    property string subtitle: ""
    default property alias actions: actionBox.data

    width: parent ? parent.width : implicitWidth
    spacing: Kirigami.Units.largeSpacing

    ColumnLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing

        Kirigami.Heading {
            Layout.fillWidth: true
            text: root.title
            level: 1
            wrapMode: Text.WordWrap
        }

        Controls.Label {
            Layout.fillWidth: true
            visible: root.subtitle.length > 0
            text: root.subtitle
            opacity: 0.7
            wrapMode: Text.WordWrap
        }
    }

    RowLayout {
        id: actionBox
        Layout.alignment: Qt.AlignRight | Qt.AlignVCenter
        spacing: Kirigami.Units.smallSpacing
    }
}
