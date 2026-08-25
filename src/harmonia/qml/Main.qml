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
                text: "Histórico"
                icon.name: "edit-clear-history"
                onTriggered: root.currentView = 7
            },
            Kirigami.Action {
                text: "Estatísticas"
                icon.name: "office-chart-line"
                onTriggered: root.currentView = 8
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
        globalToolBarStyle: Kirigami.ApplicationHeaderStyle.None

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
                    currentView: root.currentView
                    currentCategory: backend.currentLibraryCategory
                    onViewRequested: function(view) { root.currentView = view }
                    onCategoryRequested: function(category) { root.showLibraryCategory(category) }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 0

                    AppTopBar {
                        Layout.fillWidth: true
                        wideLayout: root.wideLayout
                        currentView: root.currentView
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
                        SettingsPage {}
                        HistoryPage {}
                        InsightsPage {}
                    }
                }
            }

            PlayerBar {
                Layout.fillWidth: true
                onLyricsRequested: lyricsPanel.open()
                onQueueRequested: queuePanel.open()
            }
        }
    }

    QueuePanel {
        id: queuePanel
        parent: root.contentItem
    }

    LyricsPanel {
        id: lyricsPanel
        parent: root.contentItem
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
