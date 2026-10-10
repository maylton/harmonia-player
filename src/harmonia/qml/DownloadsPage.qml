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
            title: i18n.tr("Downloads")
            subtitle: i18n.ntrf("{count} item · {size} utilizados", "{count} itens · {size} utilizados", backend.downloadItems.length, { size: backend.downloadStorageLabel })

            Controls.Button {
                text: i18n.tr("Validar conta")
                icon.name: "emblem-ok"
                enabled: backend.loggedIn
                onClicked: backend.validateDownloads()
            }
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
                onClicked: if (modelData.status === "completed") backend.playDownload(index)

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

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Kirigami.Units.smallSpacing

                            Controls.Label {
                                Layout.fillWidth: true
                                text: modelData.title
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                            }

                            ExplicitBadge {
                                visible: modelData.explicit === true
                            }
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
                                  ? i18n.tr("Disponível offline")
                                  : modelData.status === "downloading"
                                    ? Math.round(modelData.progress * 100) + "%"
                                    : modelData.status === "paused"
                                      ? i18n.tr("Pausado")
                                      : modelData.status === "failed"
                                        ? i18n.trf("Falhou: {error}", { error: modelData.error })
                                        : i18n.tr("Na fila")
                            color: modelData.status === "failed"
                                 ? Kirigami.Theme.negativeTextColor
                                 : Kirigami.Theme.textColor
                            opacity: modelData.status === "failed" ? 1 : 0.68
                            elide: Text.ElideRight
                        }
                    }

                    Controls.ToolButton {
                        visible: modelData.status === "completed"
                        icon.name: "media-playback-start"
                        onClicked: backend.playDownload(index)
                        Controls.ToolTip.visible: hovered
                        Controls.ToolTip.text: i18n.tr("Reproduzir offline")
                    }

                    Controls.ToolButton {
                        visible: modelData.status === "downloading" || modelData.status === "queued"
                        icon.name: "media-playback-pause"
                        onClicked: backend.pauseDownload(modelData.id)
                        Controls.ToolTip.visible: hovered
                        Controls.ToolTip.text: i18n.tr("Pausar")
                    }

                    Controls.ToolButton {
                        visible: modelData.status === "paused" || modelData.status === "failed"
                        icon.name: "media-playback-start"
                        onClicked: backend.resumeDownload(modelData.id)
                        Controls.ToolTip.visible: hovered
                        Controls.ToolTip.text: i18n.tr("Retomar")
                    }

                    Controls.ToolButton {
                        icon.name: "edit-delete"
                        onClicked: backend.removeDownload(modelData.id)
                        Controls.ToolTip.visible: hovered
                        Controls.ToolTip.text: i18n.tr("Remover download")
                    }
                }
            }

            Kirigami.PlaceholderMessage {
                anchors.centerIn: parent
                visible: backend.downloadItems.length === 0
                text: i18n.tr("Nenhum download")
                explanation: i18n.tr("Use o botão de download em um álbum ou playlist para ouvir offline.")
                icon.name: "download"
            }
        }
    }
}
