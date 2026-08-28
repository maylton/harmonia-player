import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Column {
    id: root

    property string title: ""
    property var columns: []
    signal itemActivated(int index)
    signal playAll()
    signal likeItem(string itemId)
    signal downloadItem(string itemId)

    width: parent ? parent.width : implicitWidth
    spacing: Kirigami.Units.smallSpacing

    function visibleColumns() {
        const viewport = Math.max(1, shelf.width)
        const gap = Kirigami.Units.largeSpacing
        if ((viewport - gap * 2) / 3 >= 320)
            return 3
        if ((viewport - gap) / 2 >= 320)
            return 2
        return 1
    }

    function columnWidth() {
        const viewport = Math.max(1, shelf.width)
        const gap = Kirigami.Units.largeSpacing
        const count = visibleColumns()
        if (count === 1)
            return Math.max(280, viewport * 0.9)
        return (viewport - gap * (count - 1)) / count
    }

    function scrollBy(direction) {
        const step = Math.max(360, shelf.width * 0.82)
        const maximum = Math.max(0, shelf.contentWidth - shelf.width)
        shelf.contentX = Math.max(0, Math.min(maximum, shelf.contentX + direction * step))
    }

    RowLayout {
        id: header
        width: parent.width
        spacing: Kirigami.Units.smallSpacing

        Kirigami.Heading {
            Layout.fillWidth: true
            text: root.title
            level: 2
        }

        Controls.Button {
            text: "Tocar tudo"
            icon.name: "media-playback-start"
            flat: true
            onClicked: root.playAll()
        }

        Controls.ToolButton {
            icon.name: "go-previous"
            enabled: shelf.contentX > 1
            display: Controls.AbstractButton.IconOnly
            onClicked: root.scrollBy(-1)
        }

        Controls.ToolButton {
            icon.name: "go-next"
            enabled: shelf.contentX + shelf.width < shelf.contentWidth - 1
            display: Controls.AbstractButton.IconOnly
            onClicked: root.scrollBy(1)
        }
    }

    ListView {
        id: shelf
        width: parent.width
        height: Kirigami.Units.gridUnit * 14.2
        orientation: ListView.Horizontal
        spacing: Kirigami.Units.largeSpacing
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: root.columns

        Behavior on contentX {
            NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
        }

        delegate: Column {
            required property int index
            required property var modelData

            width: root.columnWidth()
            height: ListView.view.height
            spacing: 0

            Repeater {
                model: modelData

                delegate: Controls.ItemDelegate {
                    id: songRow
                    required property int index
                    required property var modelData

                    width: parent.width
                    height: Kirigami.Units.gridUnit * 3.55
                    padding: Kirigami.Units.smallSpacing
                    hoverEnabled: true
                    highlighted: backend.currentId === modelData.id
                    onClicked: root.itemActivated(modelData.index)

                    contentItem: RowLayout {
                        spacing: Kirigami.Units.smallSpacing

                        Item {
                            Layout.preferredWidth: Kirigami.Units.gridUnit * 2.65
                            Layout.preferredHeight: width

                            CoverArt {
                                id: cover
                                anchors.fill: parent
                                source: modelData.thumbnail
                                kind: modelData.kind
                                cornerRadius: Math.max(5, Kirigami.Units.cornerRadius)
                                z: 0
                            }

                            Rectangle {
                                anchors.fill: parent
                                radius: cover.maskRadius
                                color: Qt.rgba(0, 0, 0, 0.42)
                                antialiasing: true
                                visible: songRow.hovered || backend.currentId === modelData.id
                                z: 1
                            }

                            Kirigami.Icon {
                                anchors.centerIn: parent
                                width: Kirigami.Units.iconSizes.medium
                                height: width
                                source: backend.currentId === modelData.id && backend.playing
                                      ? "media-playback-pause"
                                      : "media-playback-start"
                                color: "white"
                                visible: songRow.hovered || backend.currentId === modelData.id
                                z: 2
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0

                            Controls.Label {
                                Layout.fillWidth: true
                                text: modelData.title
                                font.weight: backend.currentId === modelData.id ? Font.Bold : Font.DemiBold
                                color: backend.currentId === modelData.id
                                     ? Kirigami.Theme.highlightColor
                                     : Kirigami.Theme.textColor
                                elide: Text.ElideRight
                            }

                            Controls.Label {
                                Layout.fillWidth: true
                                text: modelData.subtitle || "YouTube Music"
                                opacity: 0.68
                                elide: Text.ElideRight
                            }
                        }

                        Kirigami.Icon {
                            Layout.preferredWidth: Kirigami.Units.iconSizes.small
                            Layout.preferredHeight: width
                            source: "love-symbolic"
                            isMask: true
                            visible: modelData.liked
                            color: Kirigami.Theme.highlightColor
                        }

                        Controls.ToolButton {
                            id: options
                            icon.name: "overflow-menu"
                            display: Controls.AbstractButton.IconOnly
                            opacity: songRow.hovered || menu.visible ? 1 : 0
                            enabled: opacity > 0
                            onClicked: menu.open()

                            Controls.Menu {
                                id: menu
                                y: options.height

                                Controls.MenuItem {
                                    text: modelData.liked ? "Remover das curtidas" : "Curtir música"
                                    icon.name: "love-symbolic"
                                    onTriggered: root.likeItem(modelData.id)
                                }

                                Controls.MenuItem {
                                    text: "Baixar"
                                    icon.name: "download"
                                    onTriggered: root.downloadItem(modelData.id)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
