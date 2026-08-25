import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Item {
    id: root

    signal detailRequested()

    ListView {
        id: searchList
        anchors.fill: parent
        anchors.margins: Kirigami.Units.gridUnit * 1.2
        clip: true
        spacing: Kirigami.Units.smallSpacing
        model: backend.searchItems

        delegate: Controls.ItemDelegate {
            required property int index
            required property var modelData

            width: searchList.width
            height: Kirigami.Units.gridUnit * 4

            onClicked: {
                backend.openSearchItem(index)
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

                Controls.Label {
                    text: modelData.kind
                    opacity: 0.55
                }

                Kirigami.Icon {
                    source: modelData.kind === "songs" || modelData.kind === "videos"
                          ? "media-playback-start"
                          : "go-next"
                }
            }
        }

        Kirigami.PlaceholderMessage {
            anchors.centerIn: parent
            width: Math.min(parent.width, Kirigami.Units.gridUnit * 28)
            visible: backend.searchItems.length === 0 && !backend.busy
            text: "Pesquise músicas, vídeos, álbuns, artistas e playlists"
            icon.name: "edit-find"
        }
    }
}
