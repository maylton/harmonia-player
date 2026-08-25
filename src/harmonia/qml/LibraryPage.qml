import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Dialogs as Dialogs
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
            Layout.bottomMargin: Kirigami.Units.smallSpacing
            title: "Biblioteca"
            subtitle: backend.libraryDescription

            Controls.ComboBox {
                id: originBox
                Layout.preferredWidth: Kirigami.Units.gridUnit * 12
                model: backend.libraryOrigins
                textRole: "label"
                valueRole: "key"

                Component.onCompleted: syncOrigin()
                onActivated: backend.setLibraryOrigin(currentValue)

                function syncOrigin() {
                    for (let i = 0; i < count; ++i) {
                        if (valueAt(i) === backend.currentLibraryOrigin) {
                            currentIndex = i
                            return
                        }
                    }
                }
            }

            Controls.ComboBox {
                id: sortBox
                Layout.preferredWidth: Kirigami.Units.gridUnit * 9
                model: [
                    { "label": "Mais recentes", "value": "recent" },
                    { "label": "A-Z", "value": "title" }
                ]
                textRole: "label"

                Component.onCompleted: currentIndex = backend.currentLibrarySort === "title" ? 1 : 0
                onActivated: backend.setLibrarySort(model[currentIndex].value)
            }
        }

        Connections {
            target: backend

            function onLibraryChanged() {
                originBox.syncOrigin()
                sortBox.currentIndex = backend.currentLibrarySort === "title" ? 1 : 0
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.gridUnit * 1.5
            Layout.rightMargin: Kirigami.Units.gridUnit * 1.5
            spacing: Kirigami.Units.smallSpacing

            Controls.ButtonGroup { id: categoryGroup }

            Repeater {
                model: backend.libraryCategories

                delegate: Controls.Button {
                    required property var modelData
                    text: modelData.label
                    checkable: true
                    checked: modelData.key === backend.currentLibraryCategory
                    ButtonGroup.group: categoryGroup
                    onClicked: backend.setLibraryCategory(modelData.key)
                }
            }

            Item { Layout.fillWidth: true }

            Controls.Button {
                visible: backend.libraryIsLocal
                text: "Adicionar arquivos"
                icon.name: "document-open"
                flat: true
                onClicked: localFilesDialog.open()
            }

            Controls.Button {
                visible: backend.libraryIsLocal
                text: "Nova playlist local"
                icon.name: "list-add"
                onClicked: localPlaylistDialog.open()
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: backend.currentLibraryCategory === "songs" ? 0 : 1

            ListView {
                id: songList
                clip: true
                spacing: Kirigami.Units.smallSpacing
                model: backend.libraryItems
                leftMargin: Kirigami.Units.gridUnit * 1.2
                rightMargin: Kirigami.Units.gridUnit * 1.2
                bottomMargin: Kirigami.Units.largeSpacing

                delegate: Controls.ItemDelegate {
                    id: songRow
                    required property int index
                    required property var modelData
                    width: songList.width
                    height: Kirigami.Units.gridUnit * 4
                    hoverEnabled: true
                    onClicked: backend.openLibraryItem(index)

                    contentItem: RowLayout {
                        spacing: Kirigami.Units.largeSpacing

                        CoverArt {
                            Layout.preferredWidth: Kirigami.Units.gridUnit * 3
                            Layout.preferredHeight: width
                            source: modelData.thumbnail
                            kind: modelData.kind
                            cornerRadius: Math.max(5, Kirigami.Units.cornerRadius)
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0

                            Controls.Label {
                                Layout.fillWidth: true
                                text: modelData.title
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                            }

                            Controls.Label {
                                Layout.fillWidth: true
                                text: modelData.subtitle
                                opacity: 0.68
                                elide: Text.ElideRight
                            }
                        }

                        Kirigami.Icon {
                            Layout.preferredWidth: Kirigami.Units.iconSizes.small
                            Layout.preferredHeight: width
                            source: "favorite"
                            color: Kirigami.Theme.highlightColor
                            visible: modelData.liked
                        }

                        Controls.ToolButton {
                            visible: backend.currentLibraryOrigin === "youtube"
                            icon.name: "edit-delete"
                            onClicked: backend.toggleLike(modelData.id)
                            Controls.ToolTip.visible: hovered
                            Controls.ToolTip.text: "Remover das músicas curtidas"
                        }

                        Controls.ToolButton {
                            visible: backend.currentLibraryOrigin === "downloads"
                            icon.name: "edit-delete"
                            onClicked: backend.removeDownload(modelData.id)
                            Controls.ToolTip.visible: hovered
                            Controls.ToolTip.text: "Excluir download"
                        }

                        Controls.ToolButton {
                            visible: backend.currentLibraryOrigin === "local"
                            icon.name: "edit-delete"
                            onClicked: backend.removeLocalItem(modelData.id)
                            Controls.ToolTip.visible: hovered
                            Controls.ToolTip.text: "Remover da biblioteca local"
                        }

                        Kirigami.Icon {
                            Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                            Layout.preferredHeight: width
                            source: "media-playback-start"
                            opacity: songRow.hovered ? 1 : 0.62
                        }
                    }
                }

                Kirigami.PlaceholderMessage {
                    anchors.centerIn: parent
                    visible: backend.libraryItems.length === 0 && !backend.busy
                    text: "Nada nesta visualização"
                    explanation: "Altere a origem ou adicione conteúdo à biblioteca."
                    icon.name: "folder-music"
                }
            }

            GridView {
                id: libraryGrid
                clip: true
                cellWidth: Kirigami.Units.gridUnit * 10
                cellHeight: Kirigami.Units.gridUnit * 12.2
                model: backend.libraryItems
                leftMargin: Kirigami.Units.gridUnit * 1.2
                rightMargin: Kirigami.Units.gridUnit * 1.2
                bottomMargin: Kirigami.Units.largeSpacing

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
                    text: "Nada nesta visualização"
                    explanation: "Altere a origem ou adicione conteúdo à biblioteca."
                    icon.name: "folder-music"
                }
            }
        }
    }

    Dialogs.FileDialog {
        id: localFilesDialog
        title: "Adicionar arquivos de áudio"
        fileMode: Dialogs.FileDialog.OpenFiles
        nameFilters: [
            "Arquivos de áudio (*.mp3 *.m4a *.aac *.ogg *.opus *.flac *.wav *.wma)",
            "Todos os arquivos (*)"
        ]
        onAccepted: backend.addLocalFiles(selectedFiles.map(function(value) { return value.toString() }))
    }

    Controls.Dialog {
        id: localPlaylistDialog
        parent: root
        title: "Nova playlist local"
        modal: true
        standardButtons: Controls.Dialog.Ok | Controls.Dialog.Cancel
        onAccepted: {
            backend.createLocalPlaylist(localPlaylistName.text)
            localPlaylistName.clear()
            root.detailRequested()
        }

        contentItem: Controls.TextField {
            id: localPlaylistName
            placeholderText: "Nome da playlist"
            selectByMouse: true
        }
    }
}
