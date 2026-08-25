import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root

    width: 1180
    height: 760
    minimumWidth: 720
    minimumHeight: 520
    visible: true
    title: "Harmonia"

    property int currentView: 0
    property int previousView: 0
    readonly property bool wideLayout: width >= 900

    function showDetail(fromView) {
        previousView = fromView
        currentView = 4
    }

    function showLibraryCategory(category) {
        backend.setLibraryCategory(category)
        currentView = 2
    }

    function goBack() {
        if (currentView === 4) {
            currentView = previousView
            return
        }
        if (currentView === 1 && backend.exploreCanGoBack) {
            backend.resetExplore()
            return
        }
        currentView = 0
    }

    globalDrawer: Kirigami.GlobalDrawer {
        title: "Harmonia"
        titleIcon: "audio-headphones"
        isMenu: true
        actions: [
            Kirigami.Action {
                text: "Início"
                icon.name: "go-home"
                onTriggered: root.currentView = 0
            },
            Kirigami.Action {
                text: "Explorar"
                icon.name: "applications-multimedia"
                onTriggered: root.currentView = 1
            },
            Kirigami.Action {
                text: "Biblioteca"
                icon.name: "folder-music"
                onTriggered: root.currentView = 2
            },
            Kirigami.Action {
                text: "Músicas curtidas"
                icon.name: "favorite"
                onTriggered: root.showLibraryCategory("songs")
            },
            Kirigami.Action {
                text: "Playlists"
                icon.name: "view-media-playlist"
                onTriggered: root.showLibraryCategory("playlists")
            },
            Kirigami.Action {
                text: "Artistas"
                icon.name: "avatar-default"
                onTriggered: root.showLibraryCategory("artists")
            },
            Kirigami.Action {
                text: "Downloads"
                icon.name: "download"
                onTriggered: root.currentView = 5
            },
            Kirigami.Action {
                text: "Preferências"
                icon.name: "settings-configure"
                onTriggered: root.currentView = 6
            }
        ]
    }

    Kirigami.Action {
        id: connectAction
        text: "Conectar"
        icon.name: "user-online"
        onTriggered: cookieDialog.open()
    }

    pageStack.initialPage: Kirigami.Page {
        padding: 0

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

                Rectangle {
                    id: sidebar
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 13.2
                    Layout.fillHeight: true
                    visible: root.wideLayout
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
                            onClicked: root.currentView = 0
                        }

                        Controls.Button {
                            Layout.fillWidth: true
                            text: "Explorar"
                            icon.name: "applications-multimedia"
                            flat: true
                            checkable: true
                            checked: root.currentView === 1
                            onClicked: root.currentView = 1
                        }

                        Controls.Button {
                            Layout.fillWidth: true
                            text: "Biblioteca"
                            icon.name: "folder-music"
                            flat: true
                            checkable: true
                            checked: root.currentView === 2
                            onClicked: root.currentView = 2
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
                            checked: root.currentView === 2 && backend.currentLibraryCategory === "songs"
                            onClicked: root.showLibraryCategory("songs")
                        }

                        Controls.Button {
                            Layout.fillWidth: true
                            text: "Playlists"
                            icon.name: "view-media-playlist"
                            flat: true
                            checkable: true
                            checked: root.currentView === 2 && backend.currentLibraryCategory === "playlists"
                            onClicked: root.showLibraryCategory("playlists")
                        }

                        Controls.Button {
                            Layout.fillWidth: true
                            text: "Artistas"
                            icon.name: "avatar-default"
                            flat: true
                            checkable: true
                            checked: root.currentView === 2 && backend.currentLibraryCategory === "artists"
                            onClicked: root.showLibraryCategory("artists")
                        }

                        Item { Layout.fillHeight: true }

                        Controls.Button {
                            Layout.fillWidth: true
                            text: "Downloads"
                            icon.name: "download"
                            flat: true
                            checkable: true
                            checked: root.currentView === 5
                            onClicked: root.currentView = 5
                        }

                        Controls.Button {
                            Layout.fillWidth: true
                            text: "Preferências"
                            icon.name: "settings-configure"
                            flat: true
                            checkable: true
                            checked: root.currentView === 6
                            onClicked: root.currentView = 6
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

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 0

                    Controls.ToolBar {
                        Layout.fillWidth: true

                        contentItem: RowLayout {
                            spacing: Kirigami.Units.smallSpacing

                            Controls.ToolButton {
                                visible: !root.wideLayout
                                text: "Navegação"
                                icon.name: "sidebar-show"
                                display: Controls.AbstractButton.IconOnly
                                onClicked: root.globalDrawer.open()
                                Controls.ToolTip.visible: hovered
                                Controls.ToolTip.text: text
                            }

                            Controls.ToolButton {
                                visible: root.currentView === 4
                                text: "Voltar"
                                icon.name: "go-previous"
                                display: Controls.AbstractButton.IconOnly
                                onClicked: root.goBack()
                                Controls.ToolTip.visible: hovered
                                Controls.ToolTip.text: text
                            }

                            Controls.TextField {
                                id: searchField
                                Layout.fillWidth: true
                                Layout.maximumWidth: Kirigami.Units.gridUnit * 31
                                placeholderText: "Pesquisar músicas, álbuns, artistas…"
                                selectByMouse: true

                                onAccepted: {
                                    root.currentView = 3
                                    backend.search(text)
                                }
                            }

                            Item { Layout.fillWidth: true }

                            Controls.ToolButton {
                                text: "Sincronizar"
                                icon.name: "view-refresh"
                                display: Controls.AbstractButton.IconOnly
                                enabled: backend.loggedIn && !backend.busy
                                onClicked: backend.syncAll()
                                Controls.ToolTip.visible: hovered
                                Controls.ToolTip.text: text
                            }

                            Controls.ToolButton {
                                text: backend.loggedIn ? "Conta conectada" : "Conectar conta"
                                icon.name: backend.loggedIn ? "user-available" : "user-offline"
                                display: Controls.AbstractButton.IconOnly
                                onClicked: backend.loggedIn ? accountMenu.open() : cookieDialog.open()
                                Controls.ToolTip.visible: hovered
                                Controls.ToolTip.text: text

                                Controls.Menu {
                                    id: accountMenu
                                    y: parent.height

                                    Controls.MenuItem {
                                        text: "Desconectar conta"
                                        icon.name: "system-log-out"
                                        onTriggered: backend.disconnectAccount()
                                    }
                                }
                            }
                        }
                    }

                    Kirigami.InlineMessage {
                        Layout.fillWidth: true
                        Layout.leftMargin: Kirigami.Units.largeSpacing
                        Layout.rightMargin: Kirigami.Units.largeSpacing
                        Layout.topMargin: visible ? Kirigami.Units.smallSpacing : 0
                        visible: backend.statusText.length > 0 || !backend.loggedIn
                        text: backend.statusText.length > 0
                              ? backend.statusText
                              : "Conecte sua conta do YouTube Music para sincronizar."
                        type: backend.statusText.indexOf("Não foi possível") >= 0
                              || backend.statusText.indexOf("Erro") >= 0
                              || backend.statusText.indexOf("Falha") >= 0
                              ? Kirigami.MessageType.Error
                              : Kirigami.MessageType.Information
                        actions: !backend.loggedIn ? [connectAction] : []
                    }

                    Controls.ProgressBar {
                        Layout.fillWidth: true
                        visible: backend.busy
                        indeterminate: true
                    }

                    StackLayout {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        currentIndex: root.currentView

                        HomePage {
                            onDetailRequested: root.showDetail(0)
                        }

                        ExplorePage {
                            onDetailRequested: root.showDetail(1)
                        }

                        LibraryPage {
                            onDetailRequested: root.showDetail(2)
                        }

                        Item {
                            ListView {
                                id: searchList
                                anchors.fill: parent
                                anchors.margins: Kirigami.Units.gridUnit * 1.2
                                clip: true
                                spacing: Kirigami.Units.smallSpacing
                                model: backend.searchItems

                                delegate: Controls.ItemDelegate {
                                    required property int index
                                    required property var modelData

                                    width: searchList.width
                                    height: Kirigami.Units.gridUnit * 4

                                    onClicked: {
                                        backend.openSearchItem(index)
                                        if (modelData.kind !== "songs" && modelData.kind !== "videos")
                                            root.showDetail(3)
                                    }

                                    contentItem: RowLayout {
                                        spacing: Kirigami.Units.largeSpacing

                                        Rectangle {
                                            Layout.preferredWidth: Kirigami.Units.gridUnit * 3
                                            Layout.preferredHeight: width
                                            radius: modelData.kind === "artists"
                                                  ? width / 2
                                                  : Kirigami.Units.cornerRadius
                                            clip: true
                                            color: Kirigami.Theme.alternateBackgroundColor

                                            Image {
                                                anchors.fill: parent
                                                source: modelData.thumbnail
                                                fillMode: Image.PreserveAspectCrop
                                                asynchronous: true
                                            }
                                        }

                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 0

                                            Controls.Label {
                                                Layout.fillWidth: true
                                                text: modelData.title
                                                font.weight: Font.DemiBold
                                                elide: Text.ElideRight
                                            }

                                            Controls.Label {
                                                Layout.fillWidth: true
                                                text: modelData.subtitle
                                                opacity: 0.68
                                                elide: Text.ElideRight
                                            }
                                        }

                                        Controls.Label {
                                            text: modelData.kind
                                            opacity: 0.55
                                        }

                                        Kirigami.Icon {
                                            source: modelData.kind === "songs" || modelData.kind === "videos"
                                                  ? "media-playback-start"
                                                  : "go-next"
                                        }
                                    }
                                }

                                Kirigami.PlaceholderMessage {
                                    anchors.centerIn: parent
                                    width: Math.min(parent.width, Kirigami.Units.gridUnit * 28)
                                    visible: backend.searchItems.length === 0 && !backend.busy
                                    text: "Pesquise músicas, vídeos, álbuns, artistas e playlists"
                                    icon.name: "edit-find"
                                }
                            }
                        }

                        DetailPage {
                            onBackRequested: root.goBack()
                        }

                        DownloadsPage {}

                        SettingsPage {}
                    }
                }
            }

            PlayerBar {
                Layout.fillWidth: true
            }
        }
    }

    Controls.Dialog {
        id: cookieDialog
        parent: root.contentItem
        title: "Conectar ao YouTube Music"
        modal: true
        width: Math.min(root.width - Kirigami.Units.gridUnit * 4, Kirigami.Units.gridUnit * 34)
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        standardButtons: Controls.Dialog.Ok | Controls.Dialog.Cancel

        onAccepted: {
            backend.connectCookie(cookieInput.text)
            cookieInput.clear()
        }

        contentItem: ColumnLayout {
            spacing: Kirigami.Units.largeSpacing

            Controls.Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: "A sessão existente do Harmonia é reutilizada quando disponível. Para uma instalação nova, você também pode conectar manualmente colando o cookie do music.youtube.com."
            }

            Controls.TextArea {
                id: cookieInput
                Layout.fillWidth: true
                Layout.preferredHeight: Kirigami.Units.gridUnit * 8
                placeholderText: "Cookie do music.youtube.com"
                wrapMode: TextEdit.WrapAnywhere
            }
        }
    }
}
