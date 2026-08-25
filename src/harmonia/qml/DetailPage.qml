import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Dialogs as Dialogs
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Item {
    id: root

    signal backRequested()
    property string pendingPlaylistItemId: ""

    function openAddToPlaylist(itemId) {
        pendingPlaylistItemId = itemId
        addToPlaylistDialog.open()
    }

    AmbientBackdrop {
        anchors.fill: parent
        source: backend.detailItem.thumbnail || ""
        active: source.length > 0
        artworkOpacity: preferences.backgroundBlur ? 0.46 : 0.31
        shadeOpacity: preferences.backgroundBlur ? 0.56 : 0.80
        saturation: backend.detailIsArtist ? -0.08 : -0.16
        blurMax: backend.detailIsArtist ? 28 : 38
        blurMultiplier: 0.45
        requestedSize: 1400
    }

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

                CoverArt {
                    Layout.preferredWidth: Math.min(Kirigami.Units.gridUnit * 14, contentColumn.width * 0.28)
                    Layout.preferredHeight: width
                    Layout.alignment: Qt.AlignTop
                    source: backend.detailItem.thumbnail || ""
                    kind: backend.detailIsArtist ? "artists" : (backend.detailItem.kind || "item")
                    emphasized: true
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignBottom
                    spacing: Kirigami.Units.smallSpacing

                    Controls.Label {
                        Layout.fillWidth: true
                        text: backend.detailIsArtist
                              ? "ARTISTA"
                              : backend.detailIsLocalPlaylist
                                ? "PLAYLIST LOCAL"
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

                    Flow {
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing

                        Controls.Button {
                            text: "Reproduzir"
                            icon.name: "media-playback-start"
                            enabled: backend.detailTracks.length > 0
                            onClicked: backend.playDetailAll()
                        }

                        Controls.ToolButton {
                            text: "Ordem aleatória"
                            icon.name: "media-playlist-shuffle"
                            enabled: backend.detailTracks.length > 0
                            onClicked: backend.shuffleDetail()
                            Controls.ToolTip.visible: hovered
                            Controls.ToolTip.text: text
                        }

                        Controls.Button {
                            visible: backend.detailItem.kind === "albums" || backend.detailItem.kind === "playlists"
                            text: backend.detailSaved ? "Salvo" : "Salvar"
                            icon.name: backend.detailSaved ? "emblem-ok" : "bookmark-new"
                            flat: true
                            onClicked: backend.toggleDetailSaved()
                        }

                        Controls.Button {
                            visible: backend.detailIsArtist
                            text: backend.detailArtistSubscribed ? "Inscrito" : "Inscrever-se"
                            icon.name: backend.detailArtistSubscribed ? "emblem-ok" : "list-add-user"
                            flat: !backend.detailArtistSubscribed
                            onClicked: backend.toggleArtistSubscription()
                        }

                        Controls.Button {
                            visible: !backend.detailIsLocalPlaylist
                            text: "Baixar"
                            icon.name: "download"
                            enabled: backend.detailTracks.length > 0
                            flat: true
                            onClicked: backend.downloadDetail()
                        }

                        Controls.Button {
                            visible: backend.detailIsLocalPlaylist
                            text: "Adicionar arquivos"
                            icon.name: "list-add"
                            flat: true
                            onClicked: localPlaylistFiles.open()
                        }

                        Controls.ToolButton {
                            id: detailMenuButton
                            text: "Mais opções"
                            icon.name: "overflow-menu"
                            display: Controls.AbstractButton.IconOnly
                            onClicked: detailMenu.open()
                            Controls.ToolTip.visible: hovered
                            Controls.ToolTip.text: text

                            Controls.Menu {
                                id: detailMenu
                                y: detailMenuButton.height

                                Controls.MenuItem {
                                    visible: backend.detailItem.kind === "playlists" || backend.detailIsLocalPlaylist
                                    text: "Renomear playlist"
                                    icon.name: "document-edit"
                                    onTriggered: renameDialog.open()
                                }

                                Controls.MenuItem {
                                    visible: backend.detailItem.kind === "playlists" || backend.detailIsLocalPlaylist
                                    text: "Excluir playlist"
                                    icon.name: "edit-delete"
                                    onTriggered: deleteDialog.open()
                                }
                            }
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

                            CoverArt {
                                Layout.preferredWidth: Kirigami.Units.gridUnit * 2.5
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
                                isMask: true
                                color: Kirigami.Theme.highlightColor
                                visible: modelData.liked
                            }

                            RowLayout {
                                visible: backend.detailIsLocalPlaylist
                                spacing: 0

                                Controls.ToolButton {
                                    icon.name: "go-up"
                                    enabled: index > 0
                                    onClicked: backend.moveCurrentLocalPlaylistItem(index, -1)
                                    Controls.ToolTip.visible: hovered
                                    Controls.ToolTip.text: "Mover para cima"
                                }

                                Controls.ToolButton {
                                    icon.name: "go-down"
                                    enabled: index + 1 < backend.detailTracks.length
                                    onClicked: backend.moveCurrentLocalPlaylistItem(index, 1)
                                    Controls.ToolTip.visible: hovered
                                    Controls.ToolTip.text: "Mover para baixo"
                                }

                                Controls.ToolButton {
                                    icon.name: "list-remove"
                                    onClicked: backend.removeCurrentLocalPlaylistItem(index)
                                    Controls.ToolTip.visible: hovered
                                    Controls.ToolTip.text: "Remover da playlist"
                                }
                            }

                            Controls.ToolButton {
                                id: options
                                visible: !backend.detailIsLocalPlaylist
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
                                        text: "Adicionar à playlist"
                                        icon.name: "list-add"
                                        onTriggered: root.openAddToPlaylist(modelData.id)
                                    }

                                    Controls.MenuItem {
                                        text: "Baixar"
                                        icon.name: "download"
                                        onTriggered: backend.downloadItem(modelData.id)
                                    }

                                    Controls.MenuItem {
                                        visible: backend.detailItem.kind === "playlists" && modelData.setVideoId.length > 0
                                        text: "Remover desta playlist"
                                        icon.name: "list-remove"
                                        onTriggered: backend.removeDetailTrackFromPlaylist(index)
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
                    spacing: Kirigami.Units.smallSpacing

                    RowLayout {
                        width: parent.width
                        visible: modelData.canExpand

                        Item { Layout.fillWidth: true }

                        Controls.Button {
                            text: "Mostrar tudo"
                            icon.name: "go-next"
                            flat: true
                            onClicked: backend.expandDetailSection(index)
                        }
                    }

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

    Controls.Dialog {
        id: addToPlaylistDialog
        parent: root
        title: "Adicionar à playlist"
        modal: true
        standardButtons: Controls.Dialog.Ok | Controls.Dialog.Cancel
        enabled: backend.playlistChoices.length > 0
        onAccepted: backend.addItemToPlaylist(root.pendingPlaylistItemId, playlistChoice.currentIndex)

        contentItem: ColumnLayout {
            spacing: Kirigami.Units.largeSpacing

            Controls.Label {
                Layout.fillWidth: true
                text: backend.playlistChoices.length > 0
                      ? "Escolha uma playlist remota ou local."
                      : "Crie uma playlist primeiro."
                wrapMode: Text.WordWrap
            }

            Controls.ComboBox {
                id: playlistChoice
                Layout.fillWidth: true
                model: backend.playlistChoices
                textRole: "title"
                enabled: count > 0
            }
        }
    }

    Controls.Dialog {
        id: renameDialog
        parent: root
        title: "Renomear playlist"
        modal: true
        standardButtons: Controls.Dialog.Ok | Controls.Dialog.Cancel
        onOpened: renameField.text = backend.detailItem.title || ""
        onAccepted: {
            if (backend.detailIsLocalPlaylist)
                backend.renameCurrentLocalPlaylist(renameField.text)
            else
                backend.renameCurrentRemotePlaylist(renameField.text)
        }

        contentItem: Controls.TextField {
            id: renameField
            selectByMouse: true
        }
    }

    Controls.Dialog {
        id: deleteDialog
        parent: root
        title: "Excluir playlist?"
        modal: true
        standardButtons: Controls.Dialog.Ok | Controls.Dialog.Cancel
        onAccepted: {
            if (backend.detailIsLocalPlaylist)
                backend.deleteCurrentLocalPlaylist()
            else
                backend.deleteCurrentRemotePlaylist()
            root.backRequested()
        }

        contentItem: Controls.Label {
            text: backend.detailIsLocalPlaylist
                  ? "A playlist local será removida deste dispositivo. Os arquivos de áudio serão preservados."
                  : "A playlist será removida permanentemente da sua conta do YouTube Music."
            wrapMode: Text.WordWrap
        }
    }

    Dialogs.FileDialog {
        id: localPlaylistFiles
        title: "Adicionar arquivos à playlist"
        fileMode: Dialogs.FileDialog.OpenFiles
        nameFilters: [
            "Arquivos de áudio (*.mp3 *.m4a *.aac *.ogg *.opus *.flac *.wav *.wma)",
            "Todos os arquivos (*)"
        ]
        onAccepted: backend.addFilesToCurrentLocalPlaylist(
            selectedFiles.map(function(value) { return value.toString() })
        )
    }
}
