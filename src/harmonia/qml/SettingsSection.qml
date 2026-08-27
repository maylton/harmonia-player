import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Rectangle {
    id: root

    property string title: ""
    property string subtitle: ""
    property string iconName: "configure"
    default property alias contentData: body.data

    implicitHeight: sectionLayout.implicitHeight + Kirigami.Units.gridUnit * 2
    radius: Math.max(12, Kirigami.Units.cornerRadius * 1.8)
    color: Qt.rgba(
        Kirigami.Theme.alternateBackgroundColor.r,
        Kirigami.Theme.alternateBackgroundColor.g,
        Kirigami.Theme.alternateBackgroundColor.b,
        0.78
    )
    border.width: 1
    border.color: Qt.rgba(
        Kirigami.Theme.textColor.r,
        Kirigami.Theme.textColor.g,
        Kirigami.Theme.textColor.b,
        0.08
    )

    ColumnLayout {
        id: sectionLayout
        anchors.fill: parent
        anchors.margins: Kirigami.Units.gridUnit
        spacing: Kirigami.Units.largeSpacing

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.largeSpacing

            Rectangle {
                Layout.preferredWidth: Kirigami.Units.gridUnit * 2.35
                Layout.preferredHeight: width
                radius: width / 2
                color: Qt.rgba(
                    Kirigami.Theme.highlightColor.r,
                    Kirigami.Theme.highlightColor.g,
                    Kirigami.Theme.highlightColor.b,
                    0.13
                )
                antialiasing: true

                Kirigami.Icon {
                    anchors.centerIn: parent
                    width: Kirigami.Units.iconSizes.medium
                    height: width
                    source: root.iconName
                    isMask: true
                    color: Kirigami.Theme.textColor
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2

                Kirigami.Heading {
                    Layout.fillWidth: true
                    text: root.title
                    level: 2
                }

                Text {
                    Layout.fillWidth: true
                    visible: root.subtitle.length > 0
                    text: root.subtitle
                    color: Kirigami.Theme.textColor
                    opacity: 0.62
                    wrapMode: Text.WordWrap
                    font: Kirigami.Theme.smallFont
                }
            }
        }

        Kirigami.Separator {
            Layout.fillWidth: true
            opacity: 0.55
        }

        ColumnLayout {
            id: body
            Layout.fillWidth: true
            spacing: Kirigami.Units.largeSpacing
        }
    }
}
