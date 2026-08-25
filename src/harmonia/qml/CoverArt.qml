import QtQuick
import QtQuick.Effects
import org.kde.kirigami as Kirigami
import "Artwork.js" as Artwork

Item {
    id: root

    property string source: ""
    property string kind: "item"
    property bool emphasized: false
    property real cornerRadius: emphasized
                                ? Math.max(12, Kirigami.Units.cornerRadius * 1.8)
                                : Math.max(8, Kirigami.Units.cornerRadius * 1.45)
    readonly property bool artist: kind === "artists"
                                   || kind === "artist"
                                   || kind === "uploaded-artists"
    readonly property real maskRadius: artist ? Math.min(width, height) / 2 : cornerRadius
    readonly property int decodeSize: emphasized
                                      ? Math.max(768, Math.ceil(Math.max(width, height) * 2.5))
                                      : Math.max(256, Math.ceil(Math.max(width, height) * 2))
    readonly property string placeholderIcon: {
        if (artist)
            return "avatar-default"
        if (kind === "albums" || kind === "uploaded-albums")
            return "media-optical-audio"
        if (kind === "playlists" || kind === "local-playlists")
            return "view-media-playlist"
        if (kind === "podcasts" || kind === "podcast-episodes")
            return "podcast-amarok"
        return "audio-x-generic"
    }

    Rectangle {
        anchors.fill: parent
        anchors.topMargin: root.emphasized ? 5 : 2
        anchors.leftMargin: root.emphasized ? 2 : 1
        radius: root.maskRadius
        color: "black"
        opacity: root.emphasized ? 0.28 : 0.12
        antialiasing: true
        visible: root.width > 0 && root.height > 0
    }

    Rectangle {
        id: frame
        anchors.fill: parent
        radius: root.maskRadius
        color: Kirigami.Theme.alternateBackgroundColor
        antialiasing: true
        border.width: 1
        border.color: Qt.rgba(
            Kirigami.Theme.textColor.r,
            Kirigami.Theme.textColor.g,
            Kirigami.Theme.textColor.b,
            root.emphasized ? 0.13 : 0.07
        )

        Kirigami.Icon {
            anchors.centerIn: parent
            width: Math.min(parent.width * 0.34, Kirigami.Units.iconSizes.huge)
            height: width
            source: root.placeholderIcon
            isMask: true
            color: Kirigami.Theme.disabledTextColor
            opacity: artwork.status === Image.Error ? 0.72 : 0.46
            visible: artwork.status !== Image.Ready
        }
    }

    Rectangle {
        id: artworkMask
        anchors.fill: parent
        radius: root.maskRadius
        color: "white"
        antialiasing: true
        visible: false
        layer.enabled: true
        layer.smooth: true
        layer.samples: 4
    }

    Image {
        id: artwork
        anchors.fill: parent
        source: useFallback ? root.source : Artwork.highResolutionSource(root.source, root.decodeSize)
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: true
        smooth: true
        mipmap: true
        sourceSize.width: root.decodeSize
        sourceSize.height: root.decodeSize
        visible: status === Image.Ready
        opacity: visible ? 1 : 0
        layer.enabled: visible
        layer.smooth: true
        layer.mipmap: true
        layer.effect: MultiEffect {
            autoPaddingEnabled: false
            maskEnabled: true
            maskSource: artworkMask
            maskThresholdMin: 0.0
            maskSpreadAtMin: 0.12
        }

        property bool useFallback: false

        onStatusChanged: {
            if (status === Image.Error && source !== root.source && root.source.length > 0)
                useFallback = true
        }

        Connections {
            target: root
            function onSourceChanged() { artwork.useFallback = false }
        }

        Behavior on opacity {
            NumberAnimation { duration: 130 }
        }
    }
}
