import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Item {
    id: root

    signal detailRequested()

    Flickable {
        id: searchFlick
        anchors.fill: parent
        contentWidth: width
        contentHeight: contentColumn.height + Kirigami.Units.gridUnit * 3
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Column {
            id: contentColumn
            x: Kirigami.Units.gridUnit * 1.5
            y: Kirigami.Units.gridUnit * 1.35
            width: Math.max(0, searchFlick.width - Kirigami.Units.gridUnit * 3)
            spacing: Kirigami.Units.gridUnit * 1.4

            PageHeader {
                width: parent.width
                title: backend.searchQuery.length > 0
                       ? "Resultados para “" + backend.searchQuery + "”"
                       : "Pesquisa"
            }

            Kirigami.InlineMessage {
                width: parent.width
                visible: backend.searchHasPartialErrors
                type: Kirigami.MessageType.Warning
                text: "Algumas categorias não puderam ser carregadas; os resultados disponíveis foram preservados."
            }

            Repeater {
                model: backend.searchGroups

                delegate: Column {
                    required property int index
                    required property var modelData
                    property int groupIndex: index

                    width: contentColumn.width
                    spacing: Kirigami.Units.smallSpacing

                    Kirigami.Heading {
                        width: parent.width
                        text: modelData.title
                        level: 2
                    }

                    Repeater {
                        model: modelData.items

                        delegate: Controls.ItemDelegate {
                            id: resultRow
                            required property int index
                            required property var modelData
                            property int itemIndex: index

                            width: contentColumn.width
                            height: Kirigami.Units.gridUnit * 4
                            hoverEnabled: true

                            onClicked: {
                                backend.openSearchItem(groupIndex, itemIndex)
                                if (modelData.kind !== "songs" && modelData.kind !== "videos")
                                    root.detailRequested()
                            }

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
                                    Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                                    Layout.preferredHeight: width
                                    source: modelData.kind === "songs" || modelData.kind === "videos"
                                          ? "media-playback-start"
                                          : "go-next"
                                    opacity: resultRow.hovered ? 1 : 0.62
                                }
                            }
                        }
                    }

                    Controls.Button {
                        visible: modelData.canLoadMore
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "Carregar mais " + modelData.title.toLowerCase()
                        icon.name: "view-more-horizontal"
                        flat: true
                        onClicked: backend.loadMoreSearch(groupIndex)
                    }
                }
            }

            Kirigami.PlaceholderMessage {
                width: parent.width
                height: Kirigami.Units.gridUnit * 14
                visible: backend.searchGroups.length === 0 && !backend.busy
                text: backend.searchQuery.length > 0
                      ? "Nenhum resultado para “" + backend.searchQuery + "”"
                      : "Pesquise músicas, vídeos, álbuns, artistas e playlists"
                icon.name: "edit-find"
            }
        }
    }
}
