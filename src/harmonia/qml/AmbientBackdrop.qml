import QtQuick
import QtQuick.Effects
import org.kde.kirigami as Kirigami
import "Artwork.js" as Artwork

Item {
    id: root

    property string source: ""
    property bool active: true
    property real artworkOpacity: 0.36
    property real shadeOpacity: 0.72
    property real saturation: -0.18
    property int blurMax: 48
    property real blurMultiplier: 0.5
    property int requestedSize: 1280

    visible: active && source.length > 0
    clip: true

    Image {
        id: sourceImage
        anchors.fill: parent
        source: useFallback ? root.source : Artwork.highResolutionSource(root.source, root.requestedSize)
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: true
        smooth: true
        mipmap: true
        sourceSize.width: root.requestedSize
        sourceSize.height: root.requestedSize
        opacity: 0
        layer.enabled: true

        property bool useFallback: false

        onStatusChanged: {
            if (status === Image.Error && source !== root.source && root.source.length > 0)
                useFallback = true
        }

        Connections {
            target: root
            function onSourceChanged() { sourceImage.useFallback = false }
        }
    }

    MultiEffect {
        anchors.fill: parent
        source: sourceImage
        visible: sourceImage.status === Image.Ready
        opacity: root.artworkOpacity
        autoPaddingEnabled: false
        blurEnabled: true
        blur: 1.0
        blurMax: root.blurMax
        blurMultiplier: root.blurMultiplier
        saturation: root.saturation
    }

    Rectangle {
        anchors.fill: parent
        color: Kirigami.Theme.backgroundColor
        opacity: root.shadeOpacity
    }
}
