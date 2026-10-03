import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Item {
    id: root

    onVisibleChanged: {
        if (visible)
            backend.refreshInsights()
    }

    Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: width
        contentHeight: contentColumn.height + Kirigami.Units.gridUnit * 3
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Column {
            id: contentColumn
            x: Kirigami.Units.gridUnit * 1.5
            y: Kirigami.Units.gridUnit * 1.35
            width: Math.max(0, flick.width - Kirigami.Units.gridUnit * 3)
            spacing: Kirigami.Units.gridUnit * 1.4

            PageHeader {
                width: parent.width
                title: i18n.trf("Sua retrospectiva de {year}", { year: backend.insights.year })
                subtitle: i18n.tr("Estatísticas privadas calculadas somente neste dispositivo")
            }

            RowLayout {
                width: parent.width
                spacing: Kirigami.Units.largeSpacing

                Repeater {
                    model: [
                        { label: i18n.tr("Reproduções qualificadas"), value: backend.insights.totalPlays },
                        { label: i18n.tr("Músicas diferentes"), value: backend.insights.uniqueTracks },
                        { label: i18n.tr("Tempo registrado"), value: backend.insights.listenedLabel }
                    ]

                    delegate: Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredHeight: Kirigami.Units.gridUnit * 6
                        radius: Kirigami.Units.cornerRadius
                        color: Kirigami.Theme.alternateBackgroundColor

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: Kirigami.Units.largeSpacing
                            spacing: Kirigami.Units.smallSpacing

                            Controls.Label {
                                Layout.fillWidth: true
                                text: modelData.label
                                opacity: 0.68
                                wrapMode: Text.WordWrap
                            }

                            Kirigami.Heading {
                                Layout.fillWidth: true
                                text: modelData.value
                                level: 1
                            }
                        }
                    }
                }
            }

            Kirigami.PlaceholderMessage {
                width: parent.width
                visible: backend.insights.totalPlays === 0
                text: i18n.tr("Ainda não há estatísticas")
                explanation: i18n.tr("Reproduza músicas por pelo menos 30 segundos para formar sua retrospectiva.")
                icon.name: "office-chart-line"
            }

            Column {
                width: parent.width
                visible: backend.insights.totalPlays > 0
                spacing: Kirigami.Units.smallSpacing

                Kirigami.Heading {
                    text: i18n.tr("Mais ouvidas")
                    level: 2
                }

                Repeater {
                    model: backend.insights.topTracks

                    delegate: Controls.ItemDelegate {
                        id: trackDelegate
                        required property int index
                        required property var modelData

                        width: parent.width
                        height: Kirigami.Units.gridUnit * 4
                        onClicked: backend.playInsightTrack(index)

                        contentItem: RowLayout {
                            spacing: Kirigami.Units.largeSpacing

                            Controls.Label {
                                Layout.preferredWidth: Kirigami.Units.gridUnit * 1.5
                                text: String(trackDelegate.index + 1)
                                horizontalAlignment: Text.AlignHCenter
                                font.weight: Font.DemiBold
                                opacity: 0.7
                            }

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
                                text: i18n.ntr("{count} reprodução", "{count} reproduções", modelData.plays)
                                opacity: 0.7
                            }
                        }
                    }
                }
            }

            RowLayout {
                width: parent.width
                visible: backend.insights.totalPlays > 0
                spacing: Kirigami.Units.gridUnit * 2

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignTop
                    spacing: Kirigami.Units.smallSpacing

                    Kirigami.Heading {
                        text: i18n.tr("Artistas mais ouvidos")
                        level: 2
                    }

                    Repeater {
                        model: backend.insights.topArtists

                        delegate: RowLayout {
                            required property int index
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: Kirigami.Units.largeSpacing

                            Controls.Label {
                                Layout.preferredWidth: Kirigami.Units.gridUnit * 1.5
                                text: String(index + 1)
                                horizontalAlignment: Text.AlignHCenter
                                opacity: 0.65
                            }

                            Controls.Label {
                                Layout.fillWidth: true
                                text: modelData.name
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                            }

                            Controls.Label {
                                text: modelData.plays
                                opacity: 0.68
                            }
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignTop
                    spacing: Kirigami.Units.smallSpacing

                    Kirigami.Heading {
                        text: i18n.tr("Atividade mensal")
                        level: 2
                    }

                    Repeater {
                        model: backend.insights.months

                        delegate: RowLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: Kirigami.Units.smallSpacing

                            Controls.Label {
                                Layout.preferredWidth: Kirigami.Units.gridUnit * 2.2
                                text: modelData.label
                            }

                            Controls.ProgressBar {
                                Layout.fillWidth: true
                                from: 0
                                to: 1
                                value: modelData.ratio
                            }

                            Controls.Label {
                                Layout.preferredWidth: Kirigami.Units.gridUnit * 2
                                text: modelData.plays
                                horizontalAlignment: Text.AlignRight
                                opacity: 0.68
                            }
                        }
                    }
                }
            }
        }
    }
}
