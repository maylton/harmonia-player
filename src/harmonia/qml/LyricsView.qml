import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Item {
    id: root

    property bool expanded: false

    ColumnLayout {
        anchors.fill: parent
        spacing: Kirigami.Units.largeSpacing

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.largeSpacing

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0

                Controls.Label {
                    Layout.fillWidth: true
                    text: backend.currentTitle
                    font.weight: Font.DemiBold
                    font.pointSize: root.expanded
                                    ? Kirigami.Theme.defaultFont.pointSize * 1.2
                                    : Kirigami.Theme.defaultFont.pointSize
                    elide: Text.ElideRight
                }

                Controls.Label {
                    Layout.fillWidth: true
                    text: backend.currentArtist
                    opacity: 0.68
                    elide: Text.ElideRight
                }
            }

            Controls.Label {
                visible: backend.lyricsProvider.length > 0
                text: backend.lyricsProvider
                opacity: 0.58
            }

            Controls.ToolButton {
                text: "Recarregar letra"
                icon.name: "view-refresh"
                display: Controls.AbstractButton.IconOnly
                enabled: backend.currentId.length > 0 && !backend.lyricsLoading
                onClicked: backend.reloadLyrics()
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: text
            }
        }

        Flow {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            Controls.Button {
                id: providerButton
                text: backend.selectedLyricsProvider === "lrclib"
                      ? "LRCLIB"
                      : backend.selectedLyricsProvider === "youtube"
                        ? "YouTube"
                        : "Automática"
                flat: true
                onClicked: backend.cycleLyricsProvider()
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "Alterar fonte da letra"

                contentItem: RowLayout {
                    spacing: Kirigami.Units.smallSpacing

                    Kirigami.Icon {
                        Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                        Layout.preferredHeight: width
                        source: "view-refresh"
                        isMask: true
                        color: Kirigami.Theme.textColor
                    }

                    Controls.Label {
                        text: providerButton.text
                        color: Kirigami.Theme.textColor
                    }
                }
            }

            Controls.Button {
                id: translateButton
                text: "Traduzir"
                flat: true
                enabled: backend.lyricLines.length > 0 || backend.lyricsPlain.length > 0
                onClicked: backend.translateLyrics()
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "Traduzir para português"

                contentItem: RowLayout {
                    spacing: Kirigami.Units.smallSpacing
                    opacity: translateButton.enabled ? 1 : 0.45

                    Kirigami.Icon {
                        Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                        Layout.preferredHeight: width
                        source: "accessories-dictionary"
                        isMask: true
                        color: Kirigami.Theme.textColor
                    }

                    Controls.Label {
                        text: translateButton.text
                        color: Kirigami.Theme.textColor
                    }
                }
            }

            Controls.Button {
                id: copyButton
                text: "Copiar"
                flat: true
                enabled: backend.lyricLines.length > 0 || backend.lyricsPlain.length > 0
                onClicked: backend.copyLyrics()
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "Copiar letra"

                contentItem: RowLayout {
                    spacing: Kirigami.Units.smallSpacing
                    opacity: copyButton.enabled ? 1 : 0.45

                    Kirigami.Icon {
                        Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                        Layout.preferredHeight: width
                        source: "edit-copy"
                        isMask: true
                        color: Kirigami.Theme.textColor
                    }

                    Controls.Label {
                        text: copyButton.text
                        color: Kirigami.Theme.textColor
                    }
                }
            }

            Row {
                spacing: 0

                Controls.ToolButton {
                    text: "−250 ms"
                    display: Controls.AbstractButton.TextOnly
                    onClicked: backend.changeLyricsOffset(-250)
                    Controls.ToolTip.visible: hovered
                    Controls.ToolTip.text: "Adiantar letra em 250 ms"
                }

                Controls.ToolButton {
                    text: backend.lyricsOffset === 0
                          ? "0 ms"
                          : (backend.lyricsOffset > 0 ? "+" : "") + backend.lyricsOffset + " ms"
                    display: Controls.AbstractButton.TextOnly
                    onClicked: backend.setLyricsOffset(0)
                    Controls.ToolTip.visible: hovered
                    Controls.ToolTip.text: "Zerar ajuste de sincronia"
                }

                Controls.ToolButton {
                    text: "+250 ms"
                    display: Controls.AbstractButton.TextOnly
                    onClicked: backend.changeLyricsOffset(250)
                    Controls.ToolTip.visible: hovered
                    Controls.ToolTip.text: "Atrasar letra em 250 ms"
                }
            }
        }

        Controls.BusyIndicator {
            Layout.alignment: Qt.AlignHCenter
            running: backend.lyricsLoading
            visible: running
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: backend.lyricLines.length > 0 ? 0 : 1

            ListView {
                id: syncedList
                clip: true
                spacing: Kirigami.Units.smallSpacing
                model: backend.lyricLines

                Connections {
                    target: backend

                    function onLyricPositionChanged() {
                        if (syncedList.visible && backend.activeLyricIndex >= 0)
                            syncedList.positionViewAtIndex(backend.activeLyricIndex, ListView.Center)
                    }
                }

                delegate: Controls.ItemDelegate {
                    id: lyricDelegate
                    required property int index
                    required property var modelData
                    width: syncedList.width
                    hoverEnabled: true
                    highlighted: false
                    leftPadding: Kirigami.Units.largeSpacing
                    rightPadding: Kirigami.Units.largeSpacing
                    topPadding: Kirigami.Units.smallSpacing
                    bottomPadding: Kirigami.Units.smallSpacing
                    onClicked: backend.seekLyric(modelData.startMs)

                    background: Rectangle {
                        radius: Math.max(8, Kirigami.Units.cornerRadius * 1.4)
                        color: lyricDelegate.index === backend.activeLyricIndex
                               ? Qt.rgba(
                                   Kirigami.Theme.highlightColor.r,
                                   Kirigami.Theme.highlightColor.g,
                                   Kirigami.Theme.highlightColor.b,
                                   0.16
                               )
                               : lyricDelegate.hovered
                                 ? Qt.rgba(
                                     Kirigami.Theme.textColor.r,
                                     Kirigami.Theme.textColor.g,
                                     Kirigami.Theme.textColor.b,
                                     0.055
                                 )
                                 : "transparent"
                    }

                    contentItem: ColumnLayout {
                        spacing: 2

                        Controls.Label {
                            Layout.fillWidth: true
                            text: modelData.text
                            wrapMode: Text.WordWrap
                            font.weight: lyricDelegate.index === backend.activeLyricIndex
                                         ? Font.Bold
                                         : Font.Normal
                            font.pointSize: root.expanded
                                            ? Kirigami.Theme.defaultFont.pointSize * 1.15
                                            : Kirigami.Theme.defaultFont.pointSize
                            color: Kirigami.Theme.textColor
                        }

                        Controls.Label {
                            Layout.fillWidth: true
                            visible: modelData.translation.length > 0
                            text: modelData.translation
                            wrapMode: Text.WordWrap
                            opacity: 0.62
                        }
                    }
                }
            }

            Controls.ScrollView {
                clip: true

                Column {
                    width: parent.width
                    spacing: Kirigami.Units.largeSpacing
                    padding: Kirigami.Units.largeSpacing

                    Controls.Label {
                        width: parent.width - Kirigami.Units.largeSpacing * 2
                        text: backend.lyricsPlain
                        wrapMode: Text.WordWrap
                        lineHeight: 1.35
                        textFormat: Text.PlainText
                        font.pointSize: root.expanded
                                        ? Kirigami.Theme.defaultFont.pointSize * 1.1
                                        : Kirigami.Theme.defaultFont.pointSize
                    }

                    Controls.Label {
                        width: parent.width - Kirigami.Units.largeSpacing * 2
                        visible: backend.lyricsTranslation.length > 0
                        text: backend.lyricsTranslation
                        wrapMode: Text.WordWrap
                        lineHeight: 1.35
                        opacity: 0.62
                        textFormat: Text.PlainText
                    }
                }
            }
        }

        Kirigami.PlaceholderMessage {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !backend.lyricsLoading
                     && backend.lyricLines.length === 0
                     && backend.lyricsPlain.length === 0
            text: backend.currentId.length > 0 ? "Letra não encontrada" : "Nenhuma música reproduzindo"
            explanation: backend.currentId.length > 0
                         ? "Tente recarregar ou altere o provedor de letras."
                         : "Escolha uma faixa para ver a letra."
            icon.name: "view-media-lyrics"
        }
    }
}
