import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents

Rectangle {
    id: root

    property bool ambientMode: false
    signal lyricsRequested()
    signal queueRequested()
    signal expandedRequested()

    implicitHeight: Kirigami.Units.gridUnit * 4
    color: ambientMode
           ? Qt.rgba(
                 Kirigami.Theme.backgroundColor.r,
                 Kirigami.Theme.backgroundColor.g,
                 Kirigami.Theme.backgroundColor.b,
                 0.88
             )
           : Kirigami.Theme.backgroundColor
    border.width: 0

    Rectangle {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 1
        color: Kirigami.Theme.disabledTextColor
        opacity: 0.28
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: Kirigami.Units.largeSpacing
        spacing: Kirigami.Units.largeSpacing

        RowLayout {
            Layout.preferredWidth: Kirigami.Units.gridUnit * 21
            Layout.maximumWidth: Kirigami.Units.gridUnit * 26
            spacing: Kirigami.Units.largeSpacing

            Controls.AbstractButton {
                Layout.preferredWidth: Kirigami.Units.gridUnit * 3.1
                Layout.preferredHeight: width
                enabled: backend.currentId.length > 0
                onClicked: root.expandedRequested()
                background: Item {}
                contentItem: CoverArt {
                    source: backend.currentArtwork
                    kind: "songs"
                    cornerRadius: Math.max(5, Kirigami.Units.cornerRadius)
                }
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: "Expandir player"
            }

            Controls.AbstractButton {
                Layout.fillWidth: true
                enabled: backend.currentId.length > 0
                onClicked: root.expandedRequested()
                background: Item {}

                contentItem: ColumnLayout {
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
            }

            Controls.ToolButton {
                id: footerLikeButton
                enabled: backend.currentId.length > 0
                onClicked: backend.toggleLike(backend.currentId)
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: backend.currentLiked ? "Remover das curtidas" : "Curtir"

                contentItem: Kirigami.Icon {
                    source: "love-symbolic"
                    isMask: true
                    color: backend.currentLiked
                           ? Kirigami.Theme.highlightColor
                           : Kirigami.Theme.textColor
                    opacity: footerLikeButton.enabled
                             ? (backend.currentLiked ? 1.0 : 0.78)
                             : 0.38
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0

            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: Kirigami.Units.smallSpacing

                Controls.ToolButton {
                    icon.name: "media-playlist-shuffle"
                    checked: backend.shuffle
                    checkable: true
                    enabled: backend.currentId.length > 0
                    onClicked: backend.toggleShuffle()
                    Controls.ToolTip.visible: hovered
                    Controls.ToolTip.text: "Ordem aleatória"
                }

                Controls.ToolButton {
                    icon.name: "media-skip-backward"
                    enabled: backend.currentId.length > 0 && (backend.canPrevious || backend.position > 5000)
                    onClicked: backend.previous()
                    Controls.ToolTip.visible: hovered
                    Controls.ToolTip.text: "Anterior"
                }

                Controls.ToolButton {
                    icon.name: backend.playing ? "media-playback-pause" : "media-playback-start"
                    enabled: backend.currentId.length > 0
                    onClicked: backend.togglePlayback()
                    Controls.ToolTip.visible: hovered
                    Controls.ToolTip.text: backend.playing ? "Pausar" : "Reproduzir"
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
                    checked: backend.repeat
                    checkable: true
                    enabled: backend.currentId.length > 0
                    onClicked: backend.toggleRepeat()
                    Controls.ToolTip.visible: hovered
                    Controls.ToolTip.text: "Repetir fila"
                }

                Controls.ToolButton {
                    text: "∞"
                    display: Controls.AbstractButton.TextOnly
                    font.weight: Font.DemiBold
                    font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.15
                    checked: backend.autoplay
                    checkable: true
                    enabled: backend.currentId.length > 0
                    onClicked: backend.toggleAutoplay()
                    Controls.ToolTip.visible: hovered
                    Controls.ToolTip.text: backend.autoplayLoading
                                           ? "Carregando reprodução automática…"
                                           : backend.autoplay
                                             ? "Reprodução automática ativada"
                                             : "Reprodução automática desativada"
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Controls.Label {
                    text: root.formatTime(backend.position)
                    opacity: 0.7
                }

                PlasmaComponents.Slider {
                    Layout.fillWidth: true
                    from: 0
                    to: Math.max(1, backend.duration)
                    value: backend.position
                    enabled: backend.duration > 0
                    onPressedChanged: if (!pressed) backend.seek(Math.round(value))
                }

                Controls.Label {
                    text: root.formatTime(backend.duration)
                    opacity: 0.7
                }
            }
        }

        RowLayout {
            Layout.preferredWidth: Kirigami.Units.gridUnit * 15
            visible: root.width >= 820
            spacing: Kirigami.Units.smallSpacing

            Controls.ToolButton {
                text: "Letras"
                icon.name: "view-media-lyrics"
                display: Controls.AbstractButton.IconOnly
                enabled: backend.currentId.length > 0
                onClicked: root.lyricsRequested()
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: text
            }

            Controls.ToolButton {
                text: "Fila de reprodução"
                icon.name: "view-media-playlist"
                display: Controls.AbstractButton.IconOnly
                enabled: backend.queueItems.length > 0
                onClicked: root.queueRequested()
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: text
            }

            Kirigami.Icon {
                visible: root.width >= 980
                source: backend.volume === 0 ? "audio-volume-muted" : "audio-volume-high"
                isMask: true
                color: Kirigami.Theme.textColor
            }

            PlasmaComponents.Slider {
                Layout.fillWidth: true
                visible: root.width >= 980
                from: 0
                to: 100
                value: backend.volume
                onMoved: backend.setVolume(Math.round(value))
            }

            Controls.ToolButton {
                text: "Parar"
                icon.name: "media-playback-stop"
                enabled: backend.currentId.length > 0
                onClicked: backend.stopPlayback()
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: text
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
