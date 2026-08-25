import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root

    width: 1180
    height: 760
    minimumWidth: 760
    minimumHeight: 520
    visible: true
    title: "Harmonia"

    property int currentView: 0 // 0 home, 1 library, 2 search

    function formatTime(ms) {
        if (!ms || ms < 0)
            return "0:00"
        const total = Math.floor(ms / 1000)
        const minutes = Math.floor(total / 60)
        const seconds = total % 60
        return minutes + ":" + (seconds < 10 ? "0" : "") + seconds
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
                text: "Biblioteca"
                icon.name: "folder-music"
                onTriggered: root.currentView = 1
            },
            Kirigami.Action {
                text: "Pesquisar"
                icon.name: "edit-find"
                onTriggered: {
                    root.currentView = 2
                    searchField.forceActiveFocus()
                }
            },
            Kirigami.Action {
                text: "Sincronizar"
                icon.name: "view-refresh"
                enabled: backend.loggedIn && !backend.busy
                onTriggered: backend.syncAll()
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
        title: root.currentView === 0 ? "Início" : root.currentView === 1 ? "Biblioteca" : "Pesquisar"
        padding: 0

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            Controls.ToolBar {
                Layout.fillWidth: true
                contentItem: RowLayout {
                    spacing: Kirigami.Units.smallSpacing

                    Controls.ToolButton {
                        text: "Navegação"
                        icon.name: "sidebar-show"
                        display: Controls.AbstractButton.IconOnly
                        onClicked: root.globalDrawer.open()
                        Controls.ToolTip.visible: hovered
                        Controls.ToolTip.text: text
                    }

                    Controls.TextField {
                        id: searchField
                        Layout.fillWidth: true
                        Layout.maximumWidth: 520
                        placeholderText: "Pesquisar músicas, álbuns, artistas…"
                        selectByMouse: true
                        onAccepted: {
                            root.currentView = 2
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
                type: backend.statusText.indexOf("Não foi possível") >= 0 || backend.statusText.indexOf("Erro") >= 0
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

                Item {
                    Flickable {
                        id: homeFlick
                        anchors.fill: parent
                        contentWidth: width
                        contentHeight: homeColumn.height + Kirigami.Units.largeSpacing * 2
                        clip: true

                        Column {
                            id: homeColumn
                            x: Kirigami.Units.largeSpacing
                            y: Kirigami.Units.largeSpacing
                            width: Math.max(0, homeFlick.width - Kirigami.Units.largeSpacing * 2)
                            height: childrenRect.height
                            spacing: Kirigami.Units.largeSpacing

                            Repeater {
                                model: backend.homeSections
                                delegate: Column {
                                    required property int index
                                    required property var modelData
                                    property int sectionIndex: index
                                    property var sectionData: modelData

                                    width: homeColumn.width
                                    height: sectionTitle.implicitHeight + Kirigami.Units.smallSpacing + sectionList.height
                                    spacing: Kirigami.Units.smallSpacing

                                    Kirigami.Heading {
                                        id: sectionTitle
                                        width: parent.width
                                        text: sectionData.title
                                        level: 2
                                    }

                                    ListView {
                                        id: sectionList
                                        width: parent.width
                                        height: Kirigami.Units.gridUnit * 12
                                        orientation: ListView.Horizontal
                                        spacing: Kirigami.Units.largeSpacing
                                        clip: true
                                        model: sectionData.items

                                        delegate: Controls.ItemDelegate {
                                            required property int index
                                            required property var modelData
                                            width: Kirigami.Units.gridUnit * 9
                                            height: ListView.view.height
                                            padding: 0
                                            onClicked: backend.playHomeItem(sectionIndex, index)

                                            contentItem: Column {
                                                spacing: Kirigami.Units.smallSpacing
                                                Rectangle {
                                                    width: parent.width
                                                    height: width
                                                    radius: Kirigami.Units.cornerRadius
                                                    clip: true
                                                    color: Kirigami.Theme.alternateBackgroundColor
                                                    Image {
                                                        anchors.fill: parent
                                                        source: modelData.thumbnail
                                                        fillMode: Image.PreserveAspectCrop
                                                        asynchronous: true
                                                        cache: true
                                                    }
                                                    Kirigami.Icon {
                                                        anchors.centerIn: parent
                                                        width: Kirigami.Units.iconSizes.large
                                                        height: width
                                                        source: "audio-x-generic"
                                                        visible: !modelData.thumbnail
                                                    }
                                                }
                                                Controls.Label {
                                                    width: parent.width
                                                    text: modelData.title
                                                    font.weight: Font.DemiBold
                                                    elide: Text.ElideRight
                                                }
                                                Controls.Label {
                                                    width: parent.width
                                                    text: modelData.subtitle
                                                    opacity: 0.7
                                                    elide: Text.ElideRight
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            Kirigami.PlaceholderMessage {
                                width: homeColumn.width
                                visible: backend.homeSections.length === 0
                                text: backend.loggedIn ? "Sincronize para carregar seu Início" : "Conecte sua conta para começar"
                                icon.name: "audio-headphones"
                            }
                        }
                    }
                }

                Item {
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: Kirigami.Units.smallSpacing

                        RowLayout {
                            Layout.fillWidth: true
                            Layout.margins: Kirigami.Units.largeSpacing
                            Kirigami.Heading { text: "Biblioteca"; level: 1 }
                            Item { Layout.fillWidth: true }
                            Controls.ComboBox {
                                model: backend.libraryCategories
                                textRole: "label"
                                valueRole: "key"
                                onActivated: backend.setLibraryCategory(currentValue)
                            }
                        }

                        GridView {
                            id: libraryGrid
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.leftMargin: Kirigami.Units.largeSpacing
                            Layout.rightMargin: Kirigami.Units.largeSpacing
                            clip: true
                            cellWidth: Kirigami.Units.gridUnit * 10
                            cellHeight: Kirigami.Units.gridUnit * 12
                            model: backend.libraryItems

                            delegate: Controls.ItemDelegate {
                                required property int index
                                required property var modelData
                                width: libraryGrid.cellWidth - Kirigami.Units.smallSpacing
                                height: libraryGrid.cellHeight - Kirigami.Units.smallSpacing
                                padding: Kirigami.Units.smallSpacing
                                onClicked: backend.playLibraryItem(index)

                                contentItem: Column {
                                    spacing: Kirigami.Units.smallSpacing
                                    Rectangle {
                                        width: parent.width
                                        height: width
                                        radius: Kirigami.Units.cornerRadius
                                        clip: true
                                        color: Kirigami.Theme.alternateBackgroundColor
                                        Image {
                                            anchors.fill: parent
                                            source: modelData.thumbnail
                                            fillMode: Image.PreserveAspectCrop
                                            asynchronous: true
                                        }
                                        Kirigami.Icon {
                                            anchors.centerIn: parent
                                            width: Kirigami.Units.iconSizes.large
                                            height: width
                                            source: "audio-x-generic"
                                            visible: !modelData.thumbnail
                                        }
                                    }
                                    Controls.Label {
                                        width: parent.width
                                        text: modelData.title
                                        font.weight: Font.DemiBold
                                        elide: Text.ElideRight
                                    }
                                    Controls.Label {
                                        width: parent.width
                                        text: modelData.subtitle
                                        opacity: 0.7
                                        elide: Text.ElideRight
                                    }
                                }
                            }
                        }
                    }
                }

                Item {
                    ListView {
                        id: searchList
                        anchors.fill: parent
                        anchors.margins: Kirigami.Units.largeSpacing
                        clip: true
                        spacing: Kirigami.Units.smallSpacing
                        model: backend.searchItems

                        delegate: Controls.ItemDelegate {
                            required property int index
                            required property var modelData
                            width: searchList.width
                            height: Kirigami.Units.gridUnit * 4
                            onClicked: backend.playSearchItem(index)

                            contentItem: RowLayout {
                                spacing: Kirigami.Units.largeSpacing
                                Rectangle {
                                    Layout.preferredWidth: Kirigami.Units.gridUnit * 3
                                    Layout.preferredHeight: width
                                    radius: Kirigami.Units.cornerRadius
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
                                        opacity: 0.7
                                        elide: Text.ElideRight
                                    }
                                }
                                Kirigami.Icon { source: "media-playback-start" }
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
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: Kirigami.Units.gridUnit * 6
                color: Kirigami.Theme.backgroundColor
                border.width: 1
                border.color: Kirigami.Theme.separatorColor

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: Kirigami.Units.largeSpacing
                    spacing: Kirigami.Units.largeSpacing

                    Rectangle {
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 4
                        Layout.preferredHeight: width
                        radius: Kirigami.Units.cornerRadius
                        clip: true
                        color: Kirigami.Theme.alternateBackgroundColor
                        Image {
                            anchors.fill: parent
                            source: backend.currentArtwork
                            fillMode: Image.PreserveAspectCrop
                            asynchronous: true
                        }
                        Kirigami.Icon {
                            anchors.centerIn: parent
                            width: Kirigami.Units.iconSizes.medium
                            height: width
                            source: "audio-x-generic"
                            visible: !backend.currentArtwork
                        }
                    }

                    ColumnLayout {
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 13
                        Layout.maximumWidth: Kirigami.Units.gridUnit * 18
                        spacing: 0
                        Controls.Label {
                            Layout.fillWidth: true
                            text: backend.currentTitle
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }
                        Controls.Label {
                            Layout.fillWidth: true
                            text: backend.currentArtist
                            opacity: 0.7
                            elide: Text.ElideRight
                        }
                    }

                    Controls.ToolButton {
                        icon.name: "media-skip-backward"
                        enabled: backend.canPrevious || backend.position > 5000
                        onClicked: backend.previous()
                    }
                    Controls.ToolButton {
                        icon.name: backend.playing ? "media-playback-pause" : "media-playback-start"
                        onClicked: backend.togglePlayback()
                    }
                    Controls.ToolButton {
                        icon.name: "media-skip-forward"
                        enabled: backend.canNext
                        onClicked: backend.next()
                    }

                    Controls.Label { text: root.formatTime(backend.position) }
                    Controls.Slider {
                        id: positionSlider
                        Layout.fillWidth: true
                        from: 0
                        to: Math.max(1, backend.duration)
                        value: backend.position
                        enabled: backend.duration > 0
                        onPressedChanged: if (!pressed) backend.seek(Math.round(value))
                    }
                    Controls.Label { text: root.formatTime(backend.duration) }
                    Kirigami.Icon {
                        source: backend.volume === 0 ? "audio-volume-muted" : "audio-volume-high"
                    }
                    Controls.Slider {
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 7
                        from: 0
                        to: 100
                        value: backend.volume
                        onMoved: backend.setVolume(Math.round(value))
                    }
                }
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
