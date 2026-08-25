import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Item {
    id: root

    signal backRequested()

    Flickable {
        id: detailFlick
        anchors.fill: parent
        contentWidth: width
        contentHeight: contentColumn.height + Kirigami.Units.gridUnit * 3
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Column {
            id: contentColumn
            x: Kirigami.Units.gridUnit * 1.5
            y: Kirigami.Units.gridUnit * 1.4
            width: Math.max(0, detailFlick.width - Kirigami.Units.gridUnit * 3)
            spacing: Kirigami.Units.gridUnit * 1.7

            Controls.Button {
                text: "Voltar"
                icon.name: "go-previous"
                flat: true
                onClicked: root.backRequested()
            }

            RowLayout {
                width: parent.width
                spacing: Kirigami.Units.gridUnit * 2.2

                Rectangle {
                    Layout.preferredWidth: Math.min(Kirigami.Units.gridUnit * 14, contentColumn.width * 0.28)
                    Layout.preferredHeight: width
                    Layout.alignment: Qt.AlignTop
                    radius: backend.detailIsArtist ? width / 2 : Kirigami.Units.cornerRadius
                    clip: true
                    color: Kirigami.Theme.alternateBackgroundColor

                    Image {
                        anchors.fill: parent
                        source: backend.detailItem.thumbnail || ""
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                    }

                    Kirigami.Icon {
                        anchors.centerIn: parent
                        width: Kirigami.Units.iconSizes.huge
                        height: width
                        source: backend.detailIsArtist ? "avatar-default" : "audio-x-generic"
                        visible: !backend.detailItem.thumbnail
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignBottom
                    spacing: Kirigami.Units.smallSpacing

                    Controls.Label {
                        Layout.fillWidth: true
                        text: backend.detailIsArtist
                              ? "ARTISTA"
                              : backend.detailItem.kind === "albums"
                                ? "ÁLBUM"
                                : backend.detailItem.kind === "playlists"
                                  ? "PLAYLIST"
                                  : "COLEÇÃO"
                        opacity: 0.62
                        font.weight: Font.DemiBold
                    }

                    Kirigami.Heading {
                        Layout.fillWidth: true
                        text: backend.detailItem.title || "Carregando…"
                        level: 1
                        wrapMode: Text.WordWrap
                    }

                    Controls.Label {
                        Layout.fillWidth: true
                        visible: (backend.detailSubscribers || backend.detailItem.subtitle || "").length > 0
                        text: backend.detailSubscribers || backend.detailItem.subtitle || ""
                        opacity: 0.72
                        wrapMode: Text.WordWrap
                    }

                    Controls.Label {
                        Layout.fillWidth: true
                        visible: backend.detailDescription.length > 0
                        text: backend.detailDescription
                        opacity: 0.72
                        wrapMode: Text.WordWrap
                        maximumLineCount: 4
                        elide: Text.ElideRight
                    }

                    RowLayout {
                        Layout.topMargin: Kirigami.Units.smallSpacing

                        Controls.Button {
                            text: "Reproduzir"
                            icon.name: "media-playback-start"
                            enabled: backend.detailTracks.length > 0
                            onClicked: backend.playDetailAll()
                        }

                        Controls.Button {
                            text: "Baixar"
                            icon.name: "download"
                            enabled: backend.detailTracks.length > 0
                            flat: true
                            onClicked: backend.downloadDetail()
                        }
                    }
                }
            }

            Column {
                width: parent.width
                spacing: Kirigami.Units.smallSpacing
                visible: !backend.detailIsArtist

                Kirigami.Heading {
                    text: "Faixas"
                    level: 2
                }

                Repeater {
                    model: backend.detailTracks

                    delegate: Controls.ItemDelegate {
                        id: trackRow
                        required property int index
                        required property var modelData

                        width: parent.width
                        height: Kirigami.Units.gridUnit * 3.7
                        hoverEnabled: true
                        highlighted: backend.currentId === modelData.id
                        onClicked: backend.playDetailTrack(index)

                        contentItem: RowLayout {
                            spacing: Kirigami.Units.largeSpacing

                            Controls.Label {
                                Layout.preferredWidth: Kirigami.Units.gridUnit * 2
                                horizontalAlignment: Text.AlignHCenter
                                text: backend.currentId === modelData.id
                                      ? (backend.playing ? "▶" : "Ⅱ")
                                      : (index + 1).toString()
                                opacity: backend.currentId === modelData.id ? 1 : 0.6
                                color: backend.currentId === modelData.id
                                     ? Kirigami.Theme.highlightColor
                                     : Kirigami.Theme.textColor
                            }

                            Rectangle {
                                Layout.preferredWidth: Kirigami.Units.gridUnit * 2.5
                                Layout.preferredHeight: width
                                radius: Kirigami.Units.cornerRadius
                                clip: true
                                color: Kirigami.Theme.alternateBackgroundColor

                                Image {
                                    anchors.fill: parent
                                    source: modelData.thumbnail
                                    fillMode: Image.PreserveAspectCrop
                                    asynchronous: true
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 0

                                Controls.Label {
                                    Layout.fillWidth: true
                                    text: modelData.title
                                    font.weight: Font.DemiBold
                                    color: backend.currentId === modelData.id
                                         ? Kirigami.Theme.highlightColor
                                         : Kirigami.Theme.textColor
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
                                id: options
                                icon.name: "overflow-menu"
                                display: Controls.AbstractButton.IconOnly
                                opacity: trackRow.hovered || trackMenu.visible ? 1 : 0
                                enabled: opacity > 0
                                onClicked: trackMenu.open()

                                Controls.Menu {
                                    id: trackMenu
                                    y: options.height

                                    Controls.MenuItem {
                                        text: modelData.liked ? "Remover das curtidas" : "Curtir música"
                                        onTriggered: backend.toggleLike(modelData.id)
                                    }

                                    Controls.MenuItem {
                                        text: "Baixar"
                                        icon.name: "download"
                                        onTriggered: backend.downloadItem(modelData.id)
                                    }
                                }
                            }
                        }
                    }
                }

                Kirigami.PlaceholderMessage {
                    width: parent.width
                    height: Kirigami.Units.gridUnit * 10
                    visible: backend.detailTracks.length === 0 && !backend.busy
                    text: "Nenhuma faixa disponível"
                    icon.name: "audio-x-generic"
                }
            }

            Repeater {
                model: backend.detailSections
                visible: backend.detailIsArtist

                delegate: Column {
                    required property int index
                    required property var modelData
                    width: contentColumn.width

                    SongShelf {
                        width: parent.width
                        visible: modelData.songSection
                        height: visible ? implicitHeight : 0
                        title: modelData.title
                        columns: modelData.columns
                        onItemActivated: function(itemIndex) {
                            backend.openDetailSectionItem(index, itemIndex)
                        }
                        onPlayAll: backend.playDetailSection(index)
                        onLikeItem: function(itemId) { backend.toggleLike(itemId) }
                        onDownloadItem: function(itemId) { backend.downloadItem(itemId) }
                    }

                    MediaShelf {
                        width: parent.width
                        visible: !modelData.songSection
                        height: visible ? implicitHeight : 0
                        title: modelData.title
                        items: modelData.items
                        onItemActivated: function(itemIndex, kind) {
                            backend.openDetailSectionItem(index, itemIndex)
                        }
                    }
                }
            }
        }
    }
}
