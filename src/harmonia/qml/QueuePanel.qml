import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Controls.Dialog {
    id: root

    title: "Fila de reprodução"
    modal: false
    standardButtons: Controls.Dialog.Close
    width: Math.min(
        parent ? parent.width - Kirigami.Units.gridUnit * 4 : Kirigami.Units.gridUnit * 34,
        Kirigami.Units.gridUnit * 34
    )
    height: Math.min(
        parent ? parent.height - Kirigami.Units.gridUnit * 4 : Kirigami.Units.gridUnit * 36,
        Kirigami.Units.gridUnit * 36
    )
    x: parent ? parent.width - width - Kirigami.Units.gridUnit * 1.2 : 0
    y: parent ? (parent.height - height) / 2 : 0

    contentItem: ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        RowLayout {
            Layout.fillWidth: true

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0

                Controls.Label {
                    text: backend.queueItems.length + (backend.queueItems.length === 1 ? " faixa" : " faixas")
                    font.weight: Font.DemiBold
                }

                Controls.Label {
                    text: "A fila é preservada entre sessões do Harmonia"
                    opacity: 0.65
                }
            }

            Controls.Label { text: "Autoplay" }

            Controls.Switch {
                checked: backend.autoplay
                enabled: backend.currentId.length > 0
                onToggled: backend.toggleAutoplay()
            }
        }

        Controls.TabBar {
            id: tabs
            Layout.fillWidth: true

            Controls.TabButton {
                text: "Fila"
                icon.name: "view-media-playlist"
            }

            Controls.TabButton {
                text: "Relacionadas"
                icon.name: "media-playlist-consecutive"
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: tabs.currentIndex

            Item {
                ListView {
                    id: queueList
                    anchors.fill: parent
                    clip: true
                    spacing: Kirigami.Units.smallSpacing
                    model: backend.queueItems

                    delegate: Controls.ItemDelegate {
                        id: queueDelegate
                        required property int index
                        required property var modelData

                        width: queueList.width
                        height: Kirigami.Units.gridUnit * 4
                        highlighted: modelData.current
                        onClicked: backend.selectQueueItem(index)

                        contentItem: RowLayout {
                            spacing: Kirigami.Units.smallSpacing

                            Item {
                                Layout.preferredWidth: Kirigami.Units.gridUnit * 3
                                Layout.preferredHeight: width

                                CoverArt {
                                    anchors.fill: parent
                                    source: modelData.thumbnail
                                    kind: modelData.kind
                                }

                                Rectangle {
                                    anchors.fill: parent
                                    radius: Kirigami.Units.cornerRadius
                                    color: Qt.rgba(0, 0, 0, 0.34)
                                    visible: modelData.current
                                }

                                Kirigami.Icon {
                                    anchors.centerIn: parent
                                    width: Kirigami.Units.iconSizes.medium
                                    height: width
                                    source: "audio-volume-high"
                                    color: "white"
                                    visible: modelData.current
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 0

                                Controls.Label {
                                    Layout.fillWidth: true
                                    text: modelData.title
                                    font.weight: modelData.current ? Font.Bold : Font.DemiBold
                                    color: modelData.current
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

                            Controls.ToolButton {
                                text: "Mover para cima"
                                icon.name: "go-up"
                                display: Controls.AbstractButton.IconOnly
                                enabled: index > 0
                                onClicked: backend.moveQueueItem(queueDelegate.index, -1)
                                Controls.ToolTip.visible: hovered
                                Controls.ToolTip.text: text
                            }

                            Controls.ToolButton {
                                text: "Mover para baixo"
                                icon.name: "go-down"
                                display: Controls.AbstractButton.IconOnly
                                enabled: index + 1 < backend.queueItems.length
                                onClicked: backend.moveQueueItem(queueDelegate.index, 1)
                                Controls.ToolTip.visible: hovered
                                Controls.ToolTip.text: text
                            }

                            Controls.ToolButton {
                                text: "Remover da fila"
                                icon.name: "edit-delete"
                                display: Controls.AbstractButton.IconOnly
                                onClicked: backend.removeQueueItem(queueDelegate.index)
                                Controls.ToolTip.visible: hovered
                                Controls.ToolTip.text: text
                            }
                        }
                    }

                    Kirigami.PlaceholderMessage {
                        anchors.centerIn: parent
                        width: Math.min(parent.width, Kirigami.Units.gridUnit * 24)
                        visible: backend.queueItems.length === 0
                        text: "A fila está vazia"
                        explanation: "Escolha uma música ou use “Tocar tudo” em uma seção."
                        icon.name: "view-media-playlist"
                    }
                }
            }

            Item {
                ListView {
                    id: relatedList
                    anchors.fill: parent
                    clip: true
                    spacing: Kirigami.Units.smallSpacing
                    model: backend.relatedItems

                    delegate: Controls.ItemDelegate {
                        id: relatedDelegate
                        required property int index
                        required property var modelData

                        width: relatedList.width
                        height: Kirigami.Units.gridUnit * 4

                        contentItem: RowLayout {
                            spacing: Kirigami.Units.smallSpacing

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

                            Controls.ToolButton {
                                text: "Tocar em seguida"
                                icon.name: "media-playlist-consecutive"
                                display: Controls.AbstractButton.IconOnly
                                onClicked: backend.promoteRelated(relatedDelegate.index, true)
                                Controls.ToolTip.visible: hovered
                                Controls.ToolTip.text: text
                            }

                            Controls.ToolButton {
                                text: "Adicionar ao fim"
                                icon.name: "list-add"
                                display: Controls.AbstractButton.IconOnly
                                onClicked: backend.promoteRelated(relatedDelegate.index, false)
                                Controls.ToolTip.visible: hovered
                                Controls.ToolTip.text: text
                            }
                        }
                    }

                    Kirigami.PlaceholderMessage {
                        anchors.centerIn: parent
                        width: Math.min(parent.width, Kirigami.Units.gridUnit * 24)
                        visible: backend.relatedItems.length === 0 && !backend.autoplayLoading
                        text: "Sem recomendações ainda"
                        explanation: backend.autoplay
                                     ? "As recomendações aparecem conforme a fila avança."
                                     : "Ative o Autoplay para carregar músicas relacionadas."
                        icon.name: "media-playlist-consecutive"
                    }

                    Controls.BusyIndicator {
                        anchors.centerIn: parent
                        running: backend.autoplayLoading
                        visible: running
                    }
                }
            }
        }
    }
}
