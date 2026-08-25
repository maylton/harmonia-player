import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Rectangle {
    id: root

    property int currentView: 0
    property string currentCategory: "songs"
    signal viewRequested(int view)
    signal categoryRequested(string category)

    implicitWidth: Kirigami.Units.gridUnit * 12.8
    color: Kirigami.Theme.backgroundColor
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
                source: "audio-headphones"
            }

            Kirigami.Heading {
                Layout.fillWidth: true
                text: "Harmonia"
                level: 2
            }
        }

        Controls.Button {
            Layout.fillWidth: true
            text: "Início"
            icon.name: "go-home"
            flat: true
            checkable: true
            checked: root.currentView === 0
            onClicked: root.viewRequested(0)
        }

        Controls.Button {
            Layout.fillWidth: true
            text: "Explorar"
            icon.name: "applications-multimedia"
            flat: true
            checkable: true
            checked: root.currentView === 1
            onClicked: root.viewRequested(1)
        }

        Controls.Button {
            Layout.fillWidth: true
            text: "Biblioteca"
            icon.name: "folder-music"
            flat: true
            checkable: true
            checked: root.currentView === 2
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

        Controls.Button {
            Layout.fillWidth: true
            text: "Músicas curtidas"
            icon.name: "favorite"
            flat: true
            checkable: true
            checked: root.currentView === 2 && root.currentCategory === "songs"
            onClicked: root.categoryRequested("songs")
        }

        Controls.Button {
            Layout.fillWidth: true
            text: "Playlists"
            icon.name: "view-media-playlist"
            flat: true
            checkable: true
            checked: root.currentView === 2 && root.currentCategory === "playlists"
            onClicked: root.categoryRequested("playlists")
        }

        Controls.Button {
            Layout.fillWidth: true
            text: "Artistas"
            icon.name: "avatar-default"
            flat: true
            checkable: true
            checked: root.currentView === 2 && root.currentCategory === "artists"
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

        Controls.Button {
            Layout.fillWidth: true
            text: "Histórico"
            icon.name: "edit-clear-history"
            flat: true
            checkable: true
            checked: root.currentView === 7
            onClicked: root.viewRequested(7)
        }

        Controls.Button {
            Layout.fillWidth: true
            text: "Estatísticas"
            icon.name: "office-chart-line"
            flat: true
            checkable: true
            checked: root.currentView === 8
            onClicked: root.viewRequested(8)
        }

        Item { Layout.fillHeight: true }

        Controls.Button {
            Layout.fillWidth: true
            text: "Downloads"
            icon.name: "download"
            flat: true
            checkable: true
            checked: root.currentView === 5
            onClicked: root.viewRequested(5)
        }

        Controls.Button {
            Layout.fillWidth: true
            text: "Preferências"
            icon.name: "settings-configure"
            flat: true
            checkable: true
            checked: root.currentView === 6
            onClicked: root.viewRequested(6)
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
