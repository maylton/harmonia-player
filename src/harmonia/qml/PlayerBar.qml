import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Rectangle {
    id: root

    implicitHeight: Kirigami.Units.gridUnit * 4
    color: Kirigami.Theme.backgroundColor
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

            Rectangle {
                Layout.preferredWidth: Kirigami.Units.gridUnit * 3.1
                Layout.preferredHeight: width
                radius: Kirigami.Units.cornerRadius
                clip: true
                color: Kirigami.Theme.alternateBackgroundColor

                Image {
                    anchors.fill: parent
                    source: backend.currentArtwork
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                }

                Kirigami.Icon {
                    anchors.centerIn: parent
                    width: Kirigami.Units.iconSizes.medium
                    height: width
                    source: "audio-x-generic"
                    visible: !backend.currentArtwork
                }
            }

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

            Controls.ToolButton {
                icon.name: backend.currentLiked ? "favorite" : "non-starred"
                enabled: backend.currentId.length > 0
                onClicked: backend.toggleLike(backend.currentId)
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: backend.currentLiked ? "Remover das curtidas" : "Curtir"
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
                }

                Controls.ToolButton {
                    icon.name: backend.playing ? "media-playback-pause" : "media-playback-start"
                    enabled: backend.currentId.length > 0
                    onClicked: backend.togglePlayback()
                }

                Controls.ToolButton {
                    icon.name: "media-skip-forward"
                    enabled: backend.canNext
                    onClicked: backend.next()
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
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Controls.Label {
                    text: root.formatTime(backend.position)
                    opacity: 0.7
                }

                Controls.Slider {
                    id: positionSlider
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
            Layout.preferredWidth: Kirigami.Units.gridUnit * 11
            visible: root.width >= 880
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Icon {
                source: backend.volume === 0 ? "audio-volume-muted" : "audio-volume-high"
            }

            Controls.Slider {
                Layout.fillWidth: true
                from: 0
                to: 100
                value: backend.volume
                onMoved: backend.setVolume(Math.round(value))
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
