import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Item {
    id: root

    ColumnLayout {
        anchors.fill: parent
        spacing: Kirigami.Units.smallSpacing

        PageHeader {
            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.gridUnit * 1.5
            title: "Downloads"
            subtitle: "Músicas disponíveis para ouvir offline neste dispositivo"
        }

        ListView {
            id: downloadList
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: Kirigami.Units.gridUnit * 1.2
            Layout.rightMargin: Kirigami.Units.gridUnit * 1.2
            Layout.bottomMargin: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.smallSpacing
            clip: true
            model: backend.downloadItems

            delegate: Controls.ItemDelegate {
                required property int index
                required property var modelData

                width: downloadList.width
                height: Kirigami.Units.gridUnit * 5.2
                enabled: true

                contentItem: RowLayout {
                    spacing: Kirigami.Units.largeSpacing

                    CoverArt {
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 3.5
                        Layout.preferredHeight: width
                        source: modelData.thumbnail
                        kind: modelData.kind
                        cornerRadius: Math.max(5, Kirigami.Units.cornerRadius)
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing

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

                        Controls.ProgressBar {
                            Layout.fillWidth: true
                            visible: modelData.status === "downloading" || modelData.status === "queued"
                            from: 0
                            to: 1
                            value: modelData.progress
                            indeterminate: modelData.status === "queued" && modelData.totalBytes === 0
                        }

                        Controls.Label {
                            Layout.fillWidth: true
                            text: modelData.status === "completed"
                                  ? "Disponível offline"
                                  : modelData.status === "downloading"
                                    ? Math.round(modelData.progress * 100) + "%"
                                    : modelData.status === "paused"
                                      ? "Pausado"
                                      : modelData.status === "failed"
                                        ? "Falhou: " + modelData.error
                                        : "Na fila"
                            color: modelData.status === "failed"
                                 ? Kirigami.Theme.negativeTextColor
                                 : Kirigami.Theme.textColor
                            opacity: modelData.status === "failed" ? 1 : 0.68
                            elide: Text.ElideRight
                        }
                    }

                    Controls.ToolButton {
                        visible: modelData.status === "downloading" || modelData.status === "queued"
                        icon.name: "media-playback-pause"
                        onClicked: backend.pauseDownload(modelData.id)
                        Controls.ToolTip.visible: hovered
                        Controls.ToolTip.text: "Pausar"
                    }

                    Controls.ToolButton {
                        visible: modelData.status === "paused" || modelData.status === "failed"
                        icon.name: "media-playback-start"
                        onClicked: backend.resumeDownload(modelData.id)
                        Controls.ToolTip.visible: hovered
                        Controls.ToolTip.text: "Retomar"
                    }

                    Controls.ToolButton {
                        icon.name: "edit-delete"
                        onClicked: backend.removeDownload(modelData.id)
                        Controls.ToolTip.visible: hovered
                        Controls.ToolTip.text: "Remover download"
                    }
                }
            }

            Kirigami.PlaceholderMessage {
                anchors.centerIn: parent
                visible: backend.downloadItems.length === 0
                text: "Nenhum download ainda"
                explanation: "Use o menu de uma música ou o botão Baixar em um álbum."
                icon.name: "download"
            }
        }
    }
}
