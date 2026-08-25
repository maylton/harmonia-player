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
    readonly property bool statusIsError: backend.statusText.indexOf("Não foi possível") >= 0
                                          || backend.statusText.indexOf("Erro") >= 0
                                          || backend.statusText.indexOf("Falha") >= 0

    pageStack.globalToolBar.style: Kirigami.ApplicationHeaderStyle.None

    function showDetail(fromView) {
        previousView = fromView
        currentView = 4
    }

    function showLibraryCategory(category) {
        backend.setLibraryOrigin("youtube")
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
        handleVisible: false
        actions: [
            Kirigami.Action {
                text: "Início"
                icon.name: "go-home"
                onTriggered: root.currentView = 0
            },
            Kirigami.Action {
                text: "Explorar"
                icon.name: "find-location"
                onTriggered: root.currentView = 1
            },
            Kirigami.Action {
                text: "Biblioteca"
                icon.name: "folder-music"
                onTriggered: root.currentView = 2
            },
            Kirigami.Action {
                text: "Músicas curtidas"
                icon.name: "starred"
                onTriggered: root.showLibraryCategory("songs")
            },
            Kirigami.Action {
                text: "Playlists"
                icon.name: "view-list"
                onTriggered: root.showLibraryCategory("playlists")
            },
            Kirigami.Action {
                text: "Artistas"
                icon.name: "user-identity"
                onTriggered: root.showLibraryCategory("artists")
            },
            Kirigami.Action {
                text: "Histórico"
                icon.name: "document-open-recent"
                onTriggered: root.currentView = 7
            },
            Kirigami.Action {
                text: "Estatísticas"
                icon.name: "office-chart-line"
                onTriggered: root.currentView = 8
            },
            Kirigami.Action {
                text: "Downloads"
                icon.name: "folder-download"
                onTriggered: root.currentView = 5
            },
            Kirigami.Action {
                text: "Preferências"
                icon.name: "preferences-system"
                onTriggered: root.currentView = 6
            },
            Kirigami.Action {
                text: "Nova playlist"
                icon.name: "list-add"
                onTriggered: remotePlaylistDialog.open()
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
        globalToolBarStyle: Kirigami.ApplicationHeaderStyle.None

        background: Rectangle {
            color: Kirigami.Theme.backgroundColor
        }

        AmbientBackdrop {
            anchors.fill: parent
            source: backend.currentArtwork
            active: preferences.backgroundBlur
            artworkOpacity: 0.30
            shadeOpacity: 0.68
            saturation: -0.12
            blurMax: 64
            blurMultiplier: 0.75
            requestedSize: 1280
        }

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

                NavigationSidebar {
                    Layout.preferredWidth: implicitWidth
                    Layout.fillHeight: true
                    visible: root.wideLayout
                    ambientMode: preferences.backgroundBlur
                    currentView: root.currentView
                    currentCategory: backend.currentLibraryCategory
                    onViewRequested: function(view) { root.currentView = view }
                    onCategoryRequested: function(category) { root.showLibraryCategory(category) }
                    onCreatePlaylistRequested: remotePlaylistDialog.open()
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 0

                    AppTopBar {
                        Layout.fillWidth: true
                        wideLayout: root.wideLayout
                        currentView: root.currentView
                        ambientMode: preferences.backgroundBlur
                        onNavigationRequested: root.globalDrawer.open()
                        onBackRequested: root.goBack()
                        onConnectRequested: cookieDialog.open()
                        onSearchRequested: function(query) {
                            root.currentView = 3
                            backend.search(query)
                        }
                    }

                    Kirigami.InlineMessage {
                        Layout.fillWidth: true
                        Layout.leftMargin: Kirigami.Units.largeSpacing
                        Layout.rightMargin: Kirigami.Units.largeSpacing
                        Layout.topMargin: visible ? Kirigami.Units.smallSpacing : 0
                        visible: !backend.loggedIn || root.statusIsError
                        text: !backend.loggedIn
                              ? "Conecte sua conta do YouTube Music para sincronizar."
                              : backend.statusText
                        type: root.statusIsError
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

                        SearchPage {
                            onDetailRequested: root.showDetail(3)
                        }

                        DetailPage {
                            onBackRequested: root.goBack()
                        }

                        DownloadsPage {}

                        SettingsPage {
                            onConnectRequested: cookieDialog.open()
                        }

                        HistoryPage {}
                        InsightsPage {}
                    }
                }
            }

            PlayerBar {
                Layout.fillWidth: true
                ambientMode: preferences.backgroundBlur
                onLyricsRequested: lyricsPanel.open()
                onQueueRequested: queuePanel.open()
                onExpandedRequested: expandedPlayer.open()
            }
        }
    }

    QueuePanel {
        id: queuePanel
        parent: Controls.Overlay.overlay
    }

    LyricsPanel {
        id: lyricsPanel
        parent: Controls.Overlay.overlay
    }

    ExpandedPlayer {
        id: expandedPlayer
        parent: Controls.Overlay.overlay
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

    Controls.Dialog {
        id: remotePlaylistDialog
        parent: root.contentItem
        title: "Nova playlist"
        modal: true
        standardButtons: Controls.Dialog.Ok | Controls.Dialog.Cancel

        onAccepted: {
            backend.createRemotePlaylist(remotePlaylistName.text)
            remotePlaylistName.clear()
        }

        contentItem: ColumnLayout {
            spacing: Kirigami.Units.largeSpacing

            Controls.Label {
                Layout.fillWidth: true
                text: "A playlist será criada como privada na sua conta do YouTube Music."
                wrapMode: Text.WordWrap
            }

            Controls.TextField {
                id: remotePlaylistName
                Layout.fillWidth: true
                placeholderText: "Nome da playlist"
                selectByMouse: true
            }
        }
    }
}
