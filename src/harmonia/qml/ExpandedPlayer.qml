import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Controls.Dialog {
    id: root

    modal: true
    closePolicy: Controls.Popup.CloseOnEscape
    standardButtons: Controls.Dialog.NoButton
    padding: 0
    width: parent ? parent.width : Kirigami.Units.gridUnit * 58
    height: parent ? parent.height : Kirigami.Units.gridUnit * 40
    x: 0
    y: 0

    onOpened: {
        if (viewTabs.currentIndex === 1)
            backend.loadLyrics()
    }

    background: Rectangle {
        color: Kirigami.Theme.backgroundColor
    }

    contentItem: Item {
        Image {
            anchors.fill: parent
            source: backend.currentArtwork
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            cache: true
            opacity: status === Image.Ready ? 0.14 : 0
        }

        Rectangle {
            anchors.fill: parent
            color: Kirigami.Theme.backgroundColor
            opacity: 0.82
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.gridUnit * 1.4
            spacing: Kirigami.Units.largeSpacing

            RowLayout {
                Layout.fillWidth: true

                Controls.ToolButton {
                    text: "Fechar player expandido"
                    icon.name: "go-down"
                    display: Controls.AbstractButton.IconOnly
                    onClicked: root.close()
                    Controls.ToolTip.visible: hovered
                    Controls.ToolTip.text: text
                }

                Item { Layout.fillWidth: true }

                Controls.TabBar {
                    id: viewTabs
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 25

                    Controls.TabButton {
                        text: "Música"
                        icon.name: "audio-headphones"
                    }

                    Controls.TabButton {
                        text: "Letras"
                        icon.name: "view-media-lyrics"
                    }

                    Controls.TabButton {
                        text: "Relacionadas"
                        icon.name: "media-playlist-consecutive"
                    }

                    onCurrentIndexChanged: {
                        if (currentIndex === 1)
                            backend.loadLyrics()
                    }
                }

                Item { Layout.fillWidth: true }
                Item { Layout.preferredWidth: Kirigami.Units.iconSizes.medium }
            }

            StackLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: viewTabs.currentIndex

                Item {
                    RowLayout {
                        anchors.centerIn: parent
                        width: Math.min(parent.width, Kirigami.Units.gridUnit * 54)
                        spacing: Kirigami.Units.gridUnit * 3

                        CoverArt {
                            Layout.preferredWidth: Math.min(Kirigami.Units.gridUnit * 21, parent.width * 0.42)
                            Layout.preferredHeight: width
                            source: backend.currentArtwork
                            kind: "songs"
                            emphasized: true
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: Kirigami.Units.largeSpacing

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: Kirigami.Units.smallSpacing

                                Kirigami.Heading {
                                    Layout.fillWidth: true
                                    text: backend.currentTitle
                                    level: 1
                                    wrapMode: Text.WordWrap
                                }

                                Controls.Label {
                                    Layout.fillWidth: true
                                    text: backend.currentArtist
                                    opacity: 0.72
                                    wrapMode: Text.WordWrap
                                }
                            }

                            RowLayout {
                                Layout.alignment: Qt.AlignHCenter
                                spacing: Kirigami.Units.largeSpacing

                                Controls.ToolButton {
                                    icon.name: "media-playlist-shuffle"
                                    checkable: true
                                    checked: backend.shuffle
                                    onClicked: backend.toggleShuffle()
                                    Controls.ToolTip.visible: hovered
                                    Controls.ToolTip.text: "Ordem aleatória"
                                }

                                Controls.ToolButton {
                                    icon.name: "media-skip-backward"
                                    enabled: backend.currentId.length > 0
                                    onClicked: backend.previous()
                                    Controls.ToolTip.visible: hovered
                                    Controls.ToolTip.text: "Anterior"
                                }

                                Controls.RoundButton {
                                    Layout.preferredWidth: Kirigami.Units.gridUnit * 4
                                    Layout.preferredHeight: width
                                    icon.name: backend.playing ? "media-playback-pause" : "media-playback-start"
                                    enabled: backend.currentId.length > 0
                                    onClicked: backend.togglePlayback()
                                }

                                Controls.ToolButton {
                                    icon.name: "media-skip-forward"
                                    enabled: backend.canNext
                                    onClicked: backend.next()
                                    Controls.ToolTip.visible: hovered
                                    Controls.ToolTip.text: "Próxima"
                                }

                                Controls.ToolButton {
                                    icon.name: "media-playlist-repeat"
                                    checkable: true
                                    checked: backend.repeat
                                    onClicked: backend.toggleRepeat()
                                    Controls.ToolTip.visible: hovered
                                    Controls.ToolTip.text: "Repetir"
                                }

                                Controls.ToolButton {
                                    icon.name: "media-playlist-consecutive"
                                    checkable: true
                                    checked: backend.autoplay
                                    onClicked: backend.toggleAutoplay()
                                    Controls.ToolTip.visible: hovered
                                    Controls.ToolTip.text: "Reprodução automática"
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true

                                Controls.Label { text: root.formatTime(backend.position); opacity: 0.7 }

                                Controls.Slider {
                                    Layout.fillWidth: true
                                    from: 0
                                    to: Math.max(1, backend.duration)
                                    value: backend.position
                                    enabled: backend.duration > 0
                                    onPressedChanged: if (!pressed) backend.seek(Math.round(value))
                                }

                                Controls.Label { text: root.formatTime(backend.duration); opacity: 0.7 }
                            }

                            RowLayout {
                                Layout.alignment: Qt.AlignHCenter

                                Controls.ToolButton {
                                    icon.name: backend.currentLiked ? "favorite" : "non-starred"
                                    enabled: backend.currentId.length > 0
                                    onClicked: backend.toggleLike(backend.currentId)
                                    Controls.ToolTip.visible: hovered
                                    Controls.ToolTip.text: backend.currentLiked ? "Remover das curtidas" : "Curtir"
                                }

                                Kirigami.Icon {
                                    source: backend.volume === 0 ? "audio-volume-muted" : "audio-volume-high"
                                }

                                Controls.Slider {
                                    Layout.preferredWidth: Kirigami.Units.gridUnit * 10
                                    from: 0
                                    to: 100
                                    value: backend.volume
                                    onMoved: backend.setVolume(Math.round(value))
                                }

                                Controls.ToolButton {
                                    icon.name: "window-close"
                                    enabled: backend.currentId.length > 0
                                    onClicked: {
                                        backend.stopPlayback()
                                        root.close()
                                    }
                                    Controls.ToolTip.visible: hovered
                                    Controls.ToolTip.text: "Parar"
                                }
                            }
                        }
                    }
                }

                LyricsView {
                    expanded: true
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.leftMargin: Kirigami.Units.gridUnit * 5
                    Layout.rightMargin: Kirigami.Units.gridUnit * 5
                }

                Item {
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.leftMargin: Kirigami.Units.gridUnit * 7
                        anchors.rightMargin: Kirigami.Units.gridUnit * 7
                        spacing: Kirigami.Units.largeSpacing

                        PageHeader {
                            Layout.fillWidth: true
                            title: "Relacionadas"
                            subtitle: backend.autoplay
                                      ? "A reprodução automática usa estas recomendações para continuar a fila."
                                      : "Ative a reprodução automática para continuar ouvindo músicas relacionadas."

                            Controls.Switch {
                                checked: backend.autoplay
                                onToggled: backend.toggleAutoplay()
                            }
                        }

                        Controls.BusyIndicator {
                            Layout.alignment: Qt.AlignHCenter
                            visible: backend.autoplayLoading
                            running: visible
                        }

                        ListView {
                            id: relatedList
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            spacing: Kirigami.Units.smallSpacing
                            model: backend.relatedItems

                            delegate: Controls.ItemDelegate {
                                required property int index
                                required property var modelData
                                width: relatedList.width
                                height: Kirigami.Units.gridUnit * 4

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

                                    Controls.ToolButton {
                                        icon.name: "media-playlist-consecutive"
                                        onClicked: backend.promoteRelated(index, true)
                                        Controls.ToolTip.visible: hovered
                                        Controls.ToolTip.text: "Tocar em seguida"
                                    }

                                    Controls.ToolButton {
                                        icon.name: "list-add"
                                        onClicked: backend.promoteRelated(index, false)
                                        Controls.ToolTip.visible: hovered
                                        Controls.ToolTip.text: "Adicionar ao fim"
                                    }
                                }
                            }

                            Kirigami.PlaceholderMessage {
                                anchors.centerIn: parent
                                visible: backend.relatedItems.length === 0 && !backend.autoplayLoading
                                text: "As recomendações aparecem conforme a fila avança."
                                icon.name: "media-playlist-consecutive"
                            }
                        }
                    }
                }
            }
        }
    }

    function formatTime(ms) {
        if (!ms || ms < 0)
            return "0:00"
        const total = Math.floor(ms / 1000)
        const minutes = Math.floor(total / 60)
        const seconds = total % 60
        return minutes + ":" + (seconds < 10 ? "0" : "") + seconds
    }
}
