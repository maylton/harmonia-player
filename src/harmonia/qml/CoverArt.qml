import QtQuick
import QtQuick.Shapes
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
        border.pixelAligned: false
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
        visible: false

        // ShapePath.fillItem receives an Image's raw source texture by default,
        // which excludes Image.fillMode. Turning the Image into a layered texture
        // provider makes the Shape consume the rendered PreserveAspectCrop result
        // while keeping the CurveRenderer's high-quality antialiased outline.
        layer.enabled: true
        layer.smooth: true
        layer.mipmap: true

        property bool useFallback: false

        onStatusChanged: {
            if (status === Image.Error && source !== root.source && root.source.length > 0)
                useFallback = true
        }

        Connections {
            target: root
            function onSourceChanged() { artwork.useFallback = false }
        }
    }

    Shape {
        id: artworkShape
        anchors.fill: parent
        visible: artwork.status === Image.Ready
        opacity: visible ? 1 : 0
        asynchronous: true
        preferredRendererType: Shape.CurveRenderer

        ShapePath {
            strokeWidth: -1
            fillColor: "transparent"
            fillItem: artwork
            startX: root.maskRadius
            startY: 0

            PathLine {
                x: root.width - root.maskRadius
                y: 0
            }
            PathArc {
                x: root.width
                y: root.maskRadius
                radiusX: root.maskRadius
                radiusY: root.maskRadius
                direction: PathArc.Clockwise
            }
            PathLine {
                x: root.width
                y: root.height - root.maskRadius
            }
            PathArc {
                x: root.width - root.maskRadius
                y: root.height
                radiusX: root.maskRadius
                radiusY: root.maskRadius
                direction: PathArc.Clockwise
            }
            PathLine {
                x: root.maskRadius
                y: root.height
            }
            PathArc {
                x: 0
                y: root.height - root.maskRadius
                radiusX: root.maskRadius
                radiusY: root.maskRadius
                direction: PathArc.Clockwise
            }
            PathLine {
                x: 0
                y: root.maskRadius
            }
            PathArc {
                x: root.maskRadius
                y: 0
                radiusX: root.maskRadius
                radiusY: root.maskRadius
                direction: PathArc.Clockwise
            }
        }

        Behavior on opacity {
            NumberAnimation { duration: 130 }
        }
    }
}
