import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Item {
    id: root

    onVisibleChanged: {
        if (visible)
            backend.refreshHistory()
    }

    ListView {
        id: historyList
        anchors.fill: parent
        anchors.margins: Kirigami.Units.gridUnit * 1.4
        spacing: Kirigami.Units.smallSpacing
        clip: true
        model: backend.historyItems

        header: ColumnLayout {
            width: historyList.width
            spacing: Kirigami.Units.largeSpacing

            PageHeader {
                Layout.fillWidth: true
                title: "Histórico"
                subtitle: "Reproduções da conta e deste dispositivo"

                Controls.ToolButton {
                    text: "Atualizar"
                    icon.name: "view-refresh"
                    display: Controls.AbstractButton.IconOnly
                    enabled: !backend.historyLoading
                    onClicked: backend.refreshHistory()
                    Controls.ToolTip.visible: hovered
                    Controls.ToolTip.text: text
                }

                Controls.Button {
                    text: "Limpar local"
                    icon.name: "edit-clear-history"
                    enabled: backend.hasLocalHistory
                    onClicked: backend.clearLocalHistory()
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: historyPrivacy.implicitHeight + Kirigami.Units.largeSpacing * 2
                radius: Kirigami.Units.cornerRadius
                color: Kirigami.Theme.alternateBackgroundColor

                RowLayout {
                    id: historyPrivacy
                    anchors.fill: parent
                    anchors.margins: Kirigami.Units.largeSpacing

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0

                        Controls.Label {
                            text: "Registrar neste dispositivo"
                            font.weight: Font.DemiBold
                        }

                        Controls.Label {
                            Layout.fillWidth: true
                            text: "Quando desativado, o Harmonia não grava novas reproduções localmente."
                            opacity: 0.68
                            wrapMode: Text.WordWrap
                        }
                    }

                    Controls.Switch {
                        checked: backend.historyEnabled
                        onToggled: backend.setHistoryEnabled(checked)
                    }
                }
            }

            Controls.BusyIndicator {
                Layout.alignment: Qt.AlignHCenter
                running: backend.historyLoading
                visible: running
            }

            Item { implicitHeight: Kirigami.Units.smallSpacing }
        }

        delegate: Column {
            id: entryDelegate
            required property int index
            required property var modelData

            width: historyList.width
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Heading {
                visible: index === 0 || backend.historyItems[index - 1].group !== modelData.group
                height: visible ? implicitHeight : 0
                text: modelData.group
                level: 3
                opacity: 0.78
                topPadding: index === 0 ? 0 : Kirigami.Units.largeSpacing
            }

            Controls.ItemDelegate {
                width: parent.width
                height: Kirigami.Units.gridUnit * 4.1
                hoverEnabled: true
                onClicked: backend.playHistoryItem(entryDelegate.index)

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
                            text: modelData.subtitle || (modelData.source === "remote" ? "YouTube Music" : "Neste dispositivo")
                            opacity: 0.68
                            elide: Text.ElideRight
                        }
                    }

                    Controls.Label {
                        text: modelData.playedLabel
                        opacity: 0.58
                    }

                    Controls.ToolButton {
                        text: "Remover do histórico"
                        icon.name: "edit-delete"
                        display: Controls.AbstractButton.IconOnly
                        enabled: modelData.canRemove
                        onClicked: backend.removeHistoryItem(entryDelegate.index)
                        Controls.ToolTip.visible: hovered
                        Controls.ToolTip.text: text
                    }
                }
            }
        }

        Kirigami.PlaceholderMessage {
            anchors.centerIn: parent
            width: Math.min(parent.width, Kirigami.Units.gridUnit * 28)
            visible: backend.historyItems.length === 0 && !backend.historyLoading
            text: "Nenhuma reprodução"
            explanation: "As músicas tocadas por pelo menos 30 segundos aparecerão aqui."
            icon.name: "edit-clear-history"
        }
    }
}
