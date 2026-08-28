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

    onWidthChanged: {
        if (wideLayout && compactNavigationDrawer.opened)
            compactNavigationDrawer.close()
    }

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

    Kirigami.Action {
        id: connectAction
        text: "Conectar"
        icon.name: "user-online"
        onTriggered: loginDialog.openLogin()
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
                        onNavigationRequested: compactNavigationDrawer.open()
                        onBackRequested: root.goBack()
                        onConnectRequested: loginDialog.openLogin()
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
                            onConnectRequested: loginDialog.openLogin()
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

    Controls.Drawer {
        id: compactNavigationDrawer
        parent: Controls.Overlay.overlay
        edge: Qt.LeftEdge
        modal: true
        interactive: !root.wideLayout
        padding: 0
        width: Math.min(Kirigami.Units.gridUnit * 13, root.width * 0.82)
        height: parent ? parent.height : root.height
        closePolicy: Controls.Popup.CloseOnEscape | Controls.Popup.CloseOnPressOutside

        contentItem: NavigationSidebar {
            width: compactNavigationDrawer.availableWidth
            height: compactNavigationDrawer.availableHeight
            ambientMode: preferences.backgroundBlur
            currentView: root.currentView
            currentCategory: backend.currentLibraryCategory

            onViewRequested: function(view) {
                root.currentView = view
                compactNavigationDrawer.close()
            }

            onCategoryRequested: function(category) {
                root.showLibraryCategory(category)
                compactNavigationDrawer.close()
            }

            onCreatePlaylistRequested: {
                compactNavigationDrawer.close()
                remotePlaylistDialog.open()
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

    LoginDialog {
        id: loginDialog
        parent: root.contentItem
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
