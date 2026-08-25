import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Item {
    id: root

    signal detailRequested()

    ColumnLayout {
        anchors.fill: parent
        spacing: Kirigami.Units.smallSpacing

        PageHeader {
            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.gridUnit * 1.5
            title: "Biblioteca"
            subtitle: "Seu conteúdo salvo no YouTube Music"

            Controls.ComboBox {
                id: categoryBox
                Layout.preferredWidth: Kirigami.Units.gridUnit * 13
                model: backend.libraryCategories
                textRole: "label"
                valueRole: "key"

                Component.onCompleted: {
                    for (let i = 0; i < count; ++i) {
                        if (valueAt(i) === backend.currentLibraryCategory) {
                            currentIndex = i
                            break
                        }
                    }
                }

                onActivated: backend.setLibraryCategory(currentValue)
            }
        }

        GridView {
            id: libraryGrid
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: Kirigami.Units.gridUnit * 1.2
            Layout.rightMargin: Kirigami.Units.gridUnit * 1.2
            Layout.bottomMargin: Kirigami.Units.largeSpacing
            clip: true
            cellWidth: Kirigami.Units.gridUnit * 10
            cellHeight: Kirigami.Units.gridUnit * 12.2
            model: backend.libraryItems

            delegate: Controls.ItemDelegate {
                id: cardDelegate
                required property int index
                required property var modelData

                width: libraryGrid.cellWidth - Kirigami.Units.smallSpacing
                height: libraryGrid.cellHeight - Kirigami.Units.smallSpacing
                padding: Kirigami.Units.smallSpacing
                hoverEnabled: true

                onClicked: {
                    backend.openLibraryItem(index)
                    if (modelData.kind !== "songs" && modelData.kind !== "videos")
                        root.detailRequested()
                }

                contentItem: Column {
                    spacing: Kirigami.Units.smallSpacing

                    Item {
                        width: parent.width
                        height: width

                        CoverArt {
                            id: cover
                            anchors.fill: parent
                            source: modelData.thumbnail
                            kind: modelData.kind
                        }

                        Rectangle {
                            anchors.fill: parent
                            radius: cover.maskRadius
                            color: Qt.rgba(0, 0, 0, 0.36)
                            visible: cardDelegate.hovered
                        }

                        Rectangle {
                            anchors.centerIn: parent
                            width: Kirigami.Units.gridUnit * 3
                            height: width
                            radius: width / 2
                            color: Qt.rgba(0.05, 0.05, 0.05, 0.78)
                            border.width: 1
                            border.color: Qt.rgba(1, 1, 1, 0.12)
                            visible: cardDelegate.hovered

                            Kirigami.Icon {
                                anchors.centerIn: parent
                                width: Kirigami.Units.iconSizes.large
                                height: width
                                source: modelData.kind === "songs" || modelData.kind === "videos"
                                      ? "media-playback-start"
                                      : "go-next"
                                color: "white"
                            }
                        }
                    }

                    Controls.Label {
                        width: parent.width
                        text: modelData.title
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }

                    Controls.Label {
                        width: parent.width
                        text: modelData.subtitle
                        opacity: 0.68
                        elide: Text.ElideRight
                    }
                }
            }

            Kirigami.PlaceholderMessage {
                anchors.centerIn: parent
                visible: backend.libraryItems.length === 0 && !backend.busy
                text: "Nenhum item nesta categoria"
                icon.name: "folder-music"
            }
        }
    }
}
