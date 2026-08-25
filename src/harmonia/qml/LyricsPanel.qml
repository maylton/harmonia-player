import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Controls.Dialog {
    id: root

    title: "Letras"
    modal: false
    standardButtons: Controls.Dialog.Close
    width: Math.min(
        parent ? parent.width - Kirigami.Units.gridUnit * 4 : Kirigami.Units.gridUnit * 34,
        Kirigami.Units.gridUnit * 34
    )
    height: Math.min(
        parent ? parent.height - Kirigami.Units.gridUnit * 4 : Kirigami.Units.gridUnit * 38,
        Kirigami.Units.gridUnit * 38
    )
    x: parent ? parent.width - width - Kirigami.Units.gridUnit * 1.2 : 0
    y: parent ? (parent.height - height) / 2 : 0

    onOpened: backend.loadLyrics()

    Connections {
        target: backend

        function onLyricPositionChanged() {
            if (syncedList.visible && backend.activeLyricIndex >= 0)
                syncedList.positionViewAtIndex(backend.activeLyricIndex, ListView.Center)
        }
    }

    contentItem: ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        RowLayout {
            Layout.fillWidth: true

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0

                Controls.Label {
                    Layout.fillWidth: true
                    text: backend.currentTitle
                    font.weight: Font.DemiBold
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

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            Controls.Button {
                text: backend.selectedLyricsProvider === "lrclib"
                      ? "Fonte: LRCLIB"
                      : backend.selectedLyricsProvider === "youtube"
                        ? "Fonte: YouTube"
                        : "Fonte: Automática"
                icon.name: "view-refresh"
                flat: true
                onClicked: backend.cycleLyricsProvider()
            }

            Controls.ToolButton {
                text: "Traduzir para português"
                icon.name: "accessories-dictionary"
                enabled: backend.lyricLines.length > 0 || backend.lyricsPlain.length > 0
                onClicked: backend.translateLyrics()
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: text
            }

            Controls.ToolButton {
                text: "Copiar letra"
                icon.name: "edit-copy"
                enabled: backend.lyricLines.length > 0 || backend.lyricsPlain.length > 0
                onClicked: backend.copyLyrics()
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: text
            }

            Item { Layout.fillWidth: true }

            Controls.ToolButton {
                text: "Adiantar 250 ms"
                icon.name: "list-remove"
                onClicked: backend.changeLyricsOffset(-250)
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: text
            }

            Controls.Button {
                text: backend.lyricsOffset === 0
                      ? "Sincronia 0 ms"
                      : (backend.lyricsOffset > 0 ? "+" : "") + backend.lyricsOffset + " ms"
                flat: true
                onClicked: backend.setLyricsOffset(0)
            }

            Controls.ToolButton {
                text: "Atrasar 250 ms"
                icon.name: "list-add"
                onClicked: backend.changeLyricsOffset(250)
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: text
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

                delegate: Controls.ItemDelegate {
                    required property int index
                    required property var modelData
                    width: syncedList.width
                    highlighted: index === backend.activeLyricIndex
                    hoverEnabled: true
                    onClicked: backend.seekLyric(modelData.startMs)

                    contentItem: ColumnLayout {
                        spacing: 2

                        Controls.Label {
                            Layout.fillWidth: true
                            text: modelData.text
                            wrapMode: Text.WordWrap
                            font.weight: index === backend.activeLyricIndex ? Font.Bold : Font.Normal
                            color: index === backend.activeLyricIndex
                                   ? Kirigami.Theme.highlightColor
                                   : Kirigami.Theme.textColor
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
