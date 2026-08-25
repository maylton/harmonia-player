import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Item {
    id: root

    signal detailRequested()

    Flickable {
        id: exploreFlick
        anchors.fill: parent
        contentWidth: width
        contentHeight: contentColumn.height + Kirigami.Units.gridUnit * 3
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Column {
            id: contentColumn
            x: Kirigami.Units.gridUnit * 1.5
            y: Kirigami.Units.gridUnit * 1.35
            width: Math.max(0, exploreFlick.width - Kirigami.Units.gridUnit * 3)
            spacing: Kirigami.Units.gridUnit * 1.5

            PageHeader {
                title: backend.exploreTitle
                subtitle: backend.exploreCanGoBack
                          ? "Seleção atualizada pelo YouTube Music."
                          : "Lançamentos, paradas e sons para cada momento."

                Controls.Button {
                    visible: backend.exploreCanGoBack
                    text: "Voltar ao Explorar"
                    icon.name: "go-previous"
                    onClicked: backend.resetExplore()
                }
            }

            Column {
                width: parent.width
                spacing: Kirigami.Units.smallSpacing
                visible: backend.exploreShortcuts.length > 0

                Kirigami.Heading {
                    text: "Descubra"
                    level: 2
                }

                Grid {
                    width: parent.width
                    columns: width >= 900 ? 4 : width >= 580 ? 2 : 1
                    spacing: Kirigami.Units.largeSpacing

                    Repeater {
                        model: backend.exploreShortcuts

                        delegate: Controls.Button {
                            required property int index
                            required property var modelData

                            width: (parent.width - (parent.columns - 1) * parent.spacing) / parent.columns
                            height: Kirigami.Units.gridUnit * 3.2
                            text: modelData.title
                            icon.name: modelData.browseId === "FEmusic_new_releases"
                                     ? "media-optical-audio"
                                     : modelData.browseId === "FEmusic_charts"
                                       ? "view-list-details"
                                       : "applications-multimedia"
                            onClicked: backend.openExploreDestination("shortcuts", index)
                        }
                    }
                }
            }

            Repeater {
                model: backend.exploreSections

                delegate: Column {
                    required property int index
                    required property var modelData
                    property int sectionIndex: index

                    width: contentColumn.width

                    SongShelf {
                        width: parent.width
                        visible: modelData.songSection
                        height: visible ? implicitHeight : 0
                        title: modelData.title
                        columns: modelData.columns
                        onItemActivated: function(itemIndex) {
                            backend.openExploreItem(sectionIndex, itemIndex)
                        }
                        onPlayAll: backend.playExploreSection(sectionIndex)
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
                            backend.openExploreItem(sectionIndex, itemIndex)
                            if (kind !== "songs" && kind !== "videos")
                                root.detailRequested()
                        }
                    }
                }
            }

            Column {
                width: parent.width
                spacing: Kirigami.Units.smallSpacing
                visible: backend.exploreGenres.length > 0

                Kirigami.Heading {
                    text: "Momentos e gêneros"
                    level: 2
                }

                Flow {
                    width: parent.width
                    spacing: Kirigami.Units.smallSpacing

                    Repeater {
                        model: backend.exploreGenres

                        delegate: Controls.Button {
                            required property int index
                            required property var modelData
                            text: modelData.title
                            flat: true
                            onClicked: backend.openExploreDestination("genres", index)
                        }
                    }
                }
            }

            Kirigami.PlaceholderMessage {
                width: parent.width
                visible: backend.exploreSections.length === 0
                      && backend.exploreShortcuts.length === 0
                      && backend.exploreGenres.length === 0
                      && !backend.busy
                text: "Sincronize para carregar o Explorar"
                icon.name: "view-refresh"
            }
        }
    }
}
