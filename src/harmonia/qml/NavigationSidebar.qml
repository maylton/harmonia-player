import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Rectangle {
    id: root

    property int currentView: 0
    property string currentCategory: "songs"
    property bool ambientMode: false
    signal viewRequested(int view)
    signal categoryRequested(string category)
    signal createPlaylistRequested()

    implicitWidth: Kirigami.Units.gridUnit * 12.8
    color: ambientMode
           ? Qt.rgba(
                 Kirigami.Theme.backgroundColor.r,
                 Kirigami.Theme.backgroundColor.g,
                 Kirigami.Theme.backgroundColor.b,
                 0.86
             )
           : Kirigami.Theme.backgroundColor
    border.width: 0

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Kirigami.Units.largeSpacing
        spacing: Kirigami.Units.smallSpacing

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.smallSpacing
            Layout.bottomMargin: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.largeSpacing

            Kirigami.Icon {
                Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                Layout.preferredHeight: width
                source: "io.github.harmonia.Harmonia"
                isMask: false
            }

            Kirigami.Heading {
                Layout.fillWidth: true
                text: "Harmonia"
                level: 2
            }
        }

        SidebarButton {
            Layout.fillWidth: true
            text: "Início"
            iconName: "go-home"
            selected: root.currentView === 0
            onClicked: root.viewRequested(0)
        }

        SidebarButton {
            Layout.fillWidth: true
            text: "Explorar"
            iconName: "find-location"
            fallbackIcon: "edit-find"
            selected: root.currentView === 1
            onClicked: root.viewRequested(1)
        }

        SidebarButton {
            Layout.fillWidth: true
            text: "Biblioteca"
            iconName: "folder-music"
            fallbackIcon: "folder"
            selected: root.currentView === 2
            onClicked: root.viewRequested(2)
        }

        Controls.Label {
            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.largeSpacing
            Layout.leftMargin: Kirigami.Units.smallSpacing
            text: "SUAS MÚSICAS"
            opacity: 0.58
            font.weight: Font.DemiBold
        }

        SidebarButton {
            Layout.fillWidth: true
            text: "Músicas curtidas"
            iconName: "love-symbolic"
            fallbackIcon: "emblem-favorite-symbolic"
            iconSize: Kirigami.Units.iconSizes.smallMedium
            monochromeIcon: true
            selected: root.currentView === 2 && root.currentCategory === "songs"
            onClicked: root.categoryRequested("songs")
        }

        SidebarButton {
            Layout.fillWidth: true
            text: "Playlists"
            iconName: "view-list"
            fallbackIcon: "view-media-playlist"
            selected: root.currentView === 2 && root.currentCategory === "playlists"
            onClicked: root.categoryRequested("playlists")
        }

        SidebarButton {
            Layout.fillWidth: true
            text: "Artistas"
            iconName: "user-identity"
            fallbackIcon: "avatar-default"
            selected: root.currentView === 2 && root.currentCategory === "artists"
            onClicked: root.categoryRequested("artists")
        }

        Controls.Label {
            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.largeSpacing
            Layout.leftMargin: Kirigami.Units.smallSpacing
            text: "ATIVIDADE"
            opacity: 0.58
            font.weight: Font.DemiBold
        }

        SidebarButton {
            Layout.fillWidth: true
            text: "Histórico"
            iconName: "document-open-recent"
            fallbackIcon: "view-history"
            selected: root.currentView === 7
            onClicked: root.viewRequested(7)
        }

        SidebarButton {
            Layout.fillWidth: true
            text: "Estatísticas"
            iconName: "office-chart-line"
            fallbackIcon: "view-statistics"
            selected: root.currentView === 8
            onClicked: root.viewRequested(8)
        }

        Item { Layout.fillHeight: true }

        SidebarButton {
            Layout.fillWidth: true
            text: "Downloads"
            iconName: "folder-download"
            fallbackIcon: "download"
            selected: root.currentView === 5
            onClicked: root.viewRequested(5)
        }

        SidebarButton {
            Layout.fillWidth: true
            text: "Preferências"
            iconName: "settings-configure"
            fallbackIcon: "configure-symbolic"
            selected: root.currentView === 6
            onClicked: root.viewRequested(6)
        }

        SidebarButton {
            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.smallSpacing
            text: "Nova playlist"
            iconName: "list-add"
            onClicked: root.createPlaylistRequested()
        }
    }

    Rectangle {
        anchors.right: parent.right
        width: 1
        height: parent.height
        color: Kirigami.Theme.disabledTextColor
        opacity: 0.22
    }
}
