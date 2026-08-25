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

        RowLayout {
            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.gridUnit * 1.5

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Kirigami.Heading {
                    text: "Biblioteca"
                    level: 1
                }

                Controls.Label {
                    text: "Seu conteúdo salvo no YouTube Music"
                    opacity: 0.7
                }
            }

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
                            color: Qt.rgba(0, 0, 0, 0.36)
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
