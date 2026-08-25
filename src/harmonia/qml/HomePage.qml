import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Item {
    id: root

    signal detailRequested()

    Flickable {
        id: homeFlick
        anchors.fill: parent
        contentWidth: width
        contentHeight: contentColumn.height + Kirigami.Units.gridUnit * 3
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Column {
            id: contentColumn
            x: Kirigami.Units.gridUnit * 1.5
            y: Kirigami.Units.gridUnit * 1.35
            width: Math.max(0, homeFlick.width - Kirigami.Units.gridUnit * 3)
            spacing: Kirigami.Units.gridUnit * 1.65

            PageHeader {
                title: "Início"
                subtitle: "Escolhas feitas para você pelo YouTube Music"
            }

            Repeater {
                model: backend.homeSections

                delegate: Column {
                    required property int index
                    required property var modelData
                    property int sectionIndex: index

                    width: contentColumn.width
                    spacing: 0

                    SongShelf {
                        width: parent.width
                        visible: modelData.songSection
                        height: visible ? implicitHeight : 0
                        title: modelData.title
                        columns: modelData.columns
                        onItemActivated: function(itemIndex) {
                            backend.openHomeItem(sectionIndex, itemIndex)
                        }
                        onPlayAll: backend.playHomeSection(sectionIndex)
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
                            backend.openHomeItem(sectionIndex, itemIndex)
                            if (kind !== "songs" && kind !== "videos")
                                root.detailRequested()
                        }
                    }
                }
            }

            Kirigami.PlaceholderMessage {
                width: parent.width
                visible: backend.homeSections.length === 0 && !backend.busy
                text: backend.loggedIn
                      ? "Sincronize para carregar suas recomendações"
                      : "Conecte sua conta para começar"
                icon.name: "audio-headphones"
            }
        }
    }
}
