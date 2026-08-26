import QtQuick
import QtQuick.Controls as Controls

Controls.Slider {
    id: root

    property real playbackPosition: 0
    property real playbackDuration: 0
    property bool mouseSeeking: false
    signal seekRequested(int positionMs)

    from: 0
    to: Math.max(1, playbackDuration)
    enabled: playbackDuration > 0

    Component.onCompleted: syncFromPlayback()

    onPlaybackPositionChanged: {
        if (!mouseSeeking)
            syncFromPlayback()
    }

    onPlaybackDurationChanged: {
        if (!mouseSeeking)
            syncFromPlayback()
    }

    onMoved: {
        if (!mouseSeeking)
            seekRequested(Math.round(value))
    }

    MouseArea {
        anchors.fill: parent
        z: 100
        acceptedButtons: Qt.LeftButton
        hoverEnabled: true
        preventStealing: true
        enabled: root.enabled
        cursorShape: root.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor

        onPressed: function(mouse) {
            root.forceActiveFocus()
            root.mouseSeeking = true
            root.setValueFromX(mouse.x)
        }

        onPositionChanged: function(mouse) {
            if (pressed)
                root.setValueFromX(mouse.x)
        }

        onReleased: function(mouse) {
            root.setValueFromX(mouse.x)
            root.mouseSeeking = false
            root.seekRequested(Math.round(root.value))
        }

        onCanceled: {
            root.mouseSeeking = false
            root.syncFromPlayback()
        }
    }

    function syncFromPlayback() {
        value = Math.max(from, Math.min(to, playbackPosition))
    }

    function setValueFromX(x) {
        const handleWidth = root.handle ? root.handle.width : 0
        const usableWidth = Math.max(
            1,
            root.width - root.leftPadding - root.rightPadding - handleWidth
        )
        const start = root.leftPadding + handleWidth / 2
        let visualPosition = Math.max(0, Math.min(1, (x - start) / usableWidth))
        if (root.mirrored)
            visualPosition = 1 - visualPosition
        root.value = root.valueAt(visualPosition)
    }
}
