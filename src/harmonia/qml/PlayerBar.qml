import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Rectangle {
    id: root

    property bool ambientMode: false
    signal lyricsRequested()
    signal queueRequested()
    signal expandedRequested()

    readonly property bool showSecondaryControls: width >= 920
    readonly property bool showVolumeControls: width >= 1080
    readonly property real centerMinWidth: Kirigami.Units.gridUnit * 18
    readonly property real centerMaxWidth: Kirigami.Units.gridUnit * 34
    readonly property real seekMinWidth: Kirigami.Units.gridUnit * 10
    readonly property real seekPreferredWidth: Kirigami.Units.gridUnit * 18
    readonly property real seekMaxWidth: Kirigami.Units.gridUnit * 26
    readonly property real volumeMinWidth: Kirigami.Units.gridUnit * 5
    readonly property real volumePreferredWidth: Kirigami.Units.gridUnit * 5.6
    readonly property real volumeMaxWidth: Kirigami.Units.gridUnit * 6.5

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
        spacing: Kirigami.Units.gridUnit

        RowLayout {
            Layout.minimumWidth: Kirigami.Units.gridUnit * 13
            Layout.preferredWidth: Kirigami.Units.gridUnit * 18
            Layout.maximumWidth: Kirigami.Units.gridUnit * 22
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
                icon.name: "love-symbolic"
                icon.color: backend.currentLiked
                            ? Kirigami.Theme.highlightColor
                            : Kirigami.Theme.textColor
                enabled: backend.currentId.length > 0
                onClicked: backend.toggleLike(backend.currentId)
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: backend.currentLiked ? "Remover das curtidas" : "Curtir"
            }
        }

        Item {
            id: centerRegion
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumWidth: root.centerMinWidth

            ColumnLayout {
                anchors.centerIn: parent
                width: Math.min(
                    root.centerMaxWidth,
                    Math.max(root.centerMinWidth, centerRegion.width)
                )
                spacing: Kirigami.Units.smallSpacing

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

                    SeekSlider {
                        Layout.fillWidth: true
                        Layout.minimumWidth: root.seekMinWidth
                        Layout.preferredWidth: root.seekPreferredWidth
                        Layout.maximumWidth: root.seekMaxWidth
                        playbackPosition: backend.position
                        playbackDuration: backend.duration
                        onSeekRequested: function(positionMs) {
                            backend.seek(positionMs)
                        }
                    }

                    Controls.Label {
                        text: root.formatTime(backend.duration)
                        opacity: 0.7
                    }
                }
            }
        }

        RowLayout {
            Layout.minimumWidth: root.showVolumeControls
                                 ? Kirigami.Units.gridUnit * 13
                                 : Kirigami.Units.gridUnit * 7
            Layout.preferredWidth: root.showVolumeControls
                                   ? Kirigami.Units.gridUnit * 15
                                   : Kirigami.Units.gridUnit * 8
            Layout.maximumWidth: root.showVolumeControls
                                 ? Kirigami.Units.gridUnit * 17
                                 : Kirigami.Units.gridUnit * 9
            Layout.alignment: Qt.AlignRight | Qt.AlignVCenter
            visible: root.showSecondaryControls
            spacing: Kirigami.Units.largeSpacing

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
                visible: root.showVolumeControls
                source: backend.volume === 0 ? "audio-volume-muted" : "audio-volume-high"
                isMask: false
            }

            Controls.Slider {
                Layout.minimumWidth: root.volumeMinWidth
                Layout.preferredWidth: root.volumePreferredWidth
                Layout.maximumWidth: root.volumeMaxWidth
                visible: root.showVolumeControls
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
