import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Column {
    id: root

    property string title: ""
    property var items: []
    property bool showHeader: true
    signal itemActivated(int index, string kind)

    width: parent ? parent.width : implicitWidth
    spacing: Kirigami.Units.smallSpacing

    function scrollBy(direction) {
        const step = Math.max(Kirigami.Units.gridUnit * 20, shelf.width * 0.82)
        const maximum = Math.max(0, shelf.contentWidth - shelf.width)
        shelf.contentX = Math.max(0, Math.min(maximum, shelf.contentX + direction * step))
    }

    RowLayout {
        id: header
        visible: root.showHeader
        width: parent.width
        spacing: Kirigami.Units.smallSpacing

        Kirigami.Heading {
            Layout.fillWidth: true
            text: root.title
            level: 2
        }

        Controls.ToolButton {
            icon.name: "go-previous"
            enabled: shelf.contentX > 1
            display: Controls.AbstractButton.IconOnly
            onClicked: root.scrollBy(-1)
            Controls.ToolTip.visible: hovered
            Controls.ToolTip.text: "Voltar em " + root.title
        }

        Controls.ToolButton {
            icon.name: "go-next"
            enabled: shelf.contentX + shelf.width < shelf.contentWidth - 1
            display: Controls.AbstractButton.IconOnly
            onClicked: root.scrollBy(1)
            Controls.ToolTip.visible: hovered
            Controls.ToolTip.text: "Avançar em " + root.title
        }
    }

    ListView {
        id: shelf
        width: parent.width
        height: Kirigami.Units.gridUnit * 12.2
        orientation: ListView.Horizontal
        spacing: Kirigami.Units.largeSpacing
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: root.items

        Behavior on contentX {
            NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
        }

        delegate: Controls.ItemDelegate {
            id: cardDelegate
            required property int index
            required property var modelData

            width: Kirigami.Units.gridUnit * 9.3
            height: ListView.view.height
            padding: 0
            hoverEnabled: true
            onClicked: root.itemActivated(modelData.index, modelData.kind)

            contentItem: Column {
                spacing: Kirigami.Units.smallSpacing

                Item {
                    width: parent.width
                    height: width

                    Rectangle {
                        anchors.fill: parent
                        radius: modelData.kind === "artists" ? width / 2 : Kirigami.Units.cornerRadius
                        clip: true
                        color: Kirigami.Theme.alternateBackgroundColor

                        Image {
                            anchors.fill: parent
                            source: modelData.thumbnail
                            fillMode: Image.PreserveAspectCrop
                            asynchronous: true
                            cache: true
                        }

                        Kirigami.Icon {
                            anchors.centerIn: parent
                            width: Kirigami.Units.iconSizes.large
                            height: width
                            source: modelData.kind === "artists" ? "avatar-default" : "audio-x-generic"
                            visible: !modelData.thumbnail
                        }
                    }

                    Rectangle {
                        anchors.fill: parent
                        radius: modelData.kind === "artists" ? width / 2 : Kirigami.Units.cornerRadius
                        color: Qt.rgba(0, 0, 0, 0.38)
                        visible: cardDelegate.hovered
                    }

                    Kirigami.Icon {
                        anchors.centerIn: parent
                        width: Kirigami.Units.iconSizes.large
                        height: width
                        source: modelData.kind === "songs" || modelData.kind === "videos"
                              ? "media-playback-start"
                              : "go-next"
                        color: "white"
                        visible: cardDelegate.hovered
                    }
                }

                Controls.Label {
                    width: parent.width
                    text: modelData.title
                    font.weight: Font.DemiBold
                    maximumLineCount: 1
                    elide: Text.ElideRight
                }

                Controls.Label {
                    width: parent.width
                    text: modelData.subtitle
                    opacity: 0.68
                    maximumLineCount: 1
                    elide: Text.ElideRight
                }
            }
        }
    }
}
