import QtQuick
import QtQuick.Controls as Controls

Controls.Slider {
    id: root

    property real playbackPosition: 0
    property real playbackDuration: 0
    property bool mouseSeeking: false
    property int pendingSeek: -1
    signal seekRequested(int positionMs)

    from: 0
    to: Math.max(1, playbackDuration)
    enabled: playbackDuration > 0

    Component.onCompleted: syncFromPlayback()

    onPlaybackPositionChanged: {
        if (!mouseSeeking && !seekDebounce.running)
            syncFromPlayback()
    }

    onPlaybackDurationChanged: {
        if (!mouseSeeking)
            syncFromPlayback()
    }

    // Keyboard and accessibility-driven slider movement still reaches the
    // backend even though pointer interaction is handled by the overlay below.
    onMoved: queueSeek(Math.round(value), false)

    Timer {
        id: seekDebounce
        interval: 90
        repeat: false
        onTriggered: {
            if (root.pendingSeek >= 0) {
                root.seekRequested(root.pendingSeek)
                root.pendingSeek = -1
            }
        }
    }

    // KDE styles do not consistently move a Slider handle when the groove is
    // clicked.  Map the whole groove ourselves and emit seeks while dragging,
    // not only on release.  This also prevents a 250 ms playback refresh from
    // snapping the handle back before GStreamer accepts the new position.
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
            root.queueSeek(Math.round(root.value), true)
        }

        onPositionChanged: function(mouse) {
            if (!pressed)
                return
            root.setValueFromX(mouse.x)
            root.queueSeek(Math.round(root.value), false)
        }

        onReleased: function(mouse) {
            root.setValueFromX(mouse.x)
            seekDebounce.stop()
            root.pendingSeek = -1
            root.seekRequested(Math.round(root.value))
            // Keep playback updates blocked until the event loop has delivered
            // the final seek to Python/GStreamer.
            Qt.callLater(function() {
                root.mouseSeeking = false
            })
        }

        onCanceled: {
            seekDebounce.stop()
            root.pendingSeek = -1
            root.mouseSeeking = false
            root.syncFromPlayback()
        }
    }

    function queueSeek(positionMs, immediate) {
        pendingSeek = positionMs
        if (immediate) {
            seekDebounce.stop()
            seekRequested(pendingSeek)
            pendingSeek = -1
            return
        }
        seekDebounce.restart()
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
