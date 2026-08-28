import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Controls.ToolBar {
    id: root

    property bool wideLayout: true
    property int currentView: 0
    property bool ambientMode: false
    signal navigationRequested()
    signal backRequested()
    signal searchRequested(string query)
    signal connectRequested()

    background: Rectangle {
        color: root.ambientMode
               ? Qt.rgba(
                     Kirigami.Theme.backgroundColor.r,
                     Kirigami.Theme.backgroundColor.g,
                     Kirigami.Theme.backgroundColor.b,
                     0.84
                 )
               : Kirigami.Theme.backgroundColor

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: Kirigami.Theme.disabledTextColor
            opacity: 0.20
        }
    }

    contentItem: Item {
        implicitHeight: Math.max(
            searchField.implicitHeight,
            leftHeaderActions.implicitHeight,
            rightHeaderActions.implicitHeight
        ) + Kirigami.Units.smallSpacing * 2

        RowLayout {
            id: leftHeaderActions
            anchors.left: parent.left
            anchors.leftMargin: Kirigami.Units.smallSpacing
            anchors.verticalCenter: parent.verticalCenter
            spacing: Kirigami.Units.smallSpacing

            Controls.ToolButton {
                id: navigationButton
                visible: !root.wideLayout
                text: "Navegação"
                display: Controls.AbstractButton.IconOnly
                onClicked: root.navigationRequested()
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: text

                contentItem: Kirigami.Icon {
                    implicitWidth: Kirigami.Units.iconSizes.smallMedium
                    implicitHeight: implicitWidth
                    source: "application-menu"
                    fallback: "view-list"
                    isMask: false
                }
            }

            Controls.ToolButton {
                visible: root.currentView === 4
                text: "Voltar"
                icon.name: "go-previous"
                display: Controls.AbstractButton.IconOnly
                onClicked: root.backRequested()
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: text
            }
        }

        Controls.TextField {
            id: searchField
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(
                Kirigami.Units.gridUnit * 12,
                Math.min(
                    Kirigami.Units.gridUnit * 22,
                    parent.width
                        - leftHeaderActions.implicitWidth
                        - rightHeaderActions.implicitWidth
                        - Kirigami.Units.gridUnit * 4
                )
            )
            placeholderText: "Pesquisar músicas, álbuns, artistas…"
            selectByMouse: true

            onAccepted: {
                suggestionTimer.stop()
                backend.clearSearchSuggestions()
                root.searchRequested(text)
            }

            onTextEdited: {
                suggestionTimer.stop()
                if (text.trim().length < 2) {
                    backend.clearSearchSuggestions()
                    return
                }
                suggestionTimer.restart()
            }

            onActiveFocusChanged: {
                if (!activeFocus)
                    closeSuggestionsTimer.restart()
            }
        }

        Timer {
            id: suggestionTimer
            interval: 280
            repeat: false
            onTriggered: backend.requestSearchSuggestions(searchField.text)
        }

        Timer {
            id: closeSuggestionsTimer
            interval: 120
            repeat: false
            onTriggered: if (!searchField.activeFocus) backend.clearSearchSuggestions()
        }

        Controls.Popup {
            id: suggestionsPopup
            parent: root
            x: searchField.mapToItem(root, 0, 0).x
            y: searchField.mapToItem(root, 0, searchField.height).y + Kirigami.Units.smallSpacing
            width: searchField.width
            padding: Kirigami.Units.smallSpacing
            closePolicy: Controls.Popup.CloseOnEscape | Controls.Popup.CloseOnPressOutside
            visible: backend.searchSuggestions.length > 0 && searchField.activeFocus

            contentItem: Column {
                width: suggestionsPopup.availableWidth

                Repeater {
                    model: backend.searchSuggestions

                    delegate: Controls.ItemDelegate {
                        required property string modelData
                        width: parent.width
                        text: modelData
                        icon.name: "edit-find"

                        onClicked: {
                            searchField.text = modelData
                            backend.clearSearchSuggestions()
                            root.searchRequested(modelData)
                        }
                    }
                }
            }
        }

        RowLayout {
            id: rightHeaderActions
            anchors.right: parent.right
            anchors.rightMargin: Kirigami.Units.smallSpacing
            anchors.verticalCenter: parent.verticalCenter
            spacing: Kirigami.Units.smallSpacing

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
                id: accountButton
                text: backend.loggedIn
                      ? (backend.accountName.length > 0
                         ? "Conta — " + backend.accountName
                         : "Conta conectada")
                      : "Conectar conta"
                display: Controls.AbstractButton.IconOnly
                padding: Kirigami.Units.smallSpacing
                onClicked: backend.loggedIn ? accountMenu.open() : root.connectRequested()
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: text

                contentItem: Item {
                    implicitWidth: Kirigami.Units.iconSizes.medium
                    implicitHeight: implicitWidth

                    CoverArt {
                        anchors.fill: parent
                        source: backend.loggedIn ? backend.accountAvatarUrl : ""
                        kind: "artist"
                        cornerRadius: width / 2
                    }

                    Kirigami.Icon {
                        anchors.centerIn: parent
                        width: Kirigami.Units.iconSizes.smallMedium
                        height: width
                        source: backend.loggedIn ? "user-available" : "user-offline"
                        isMask: true
                        color: Kirigami.Theme.textColor
                        visible: !backend.loggedIn || backend.accountAvatarUrl.length === 0
                    }
                }

                Controls.Menu {
                    id: accountMenu
                    y: parent.height

                    Controls.MenuItem {
                        enabled: backend.accountName.length > 0
                        text: backend.accountName.length > 0 ? backend.accountName : "Conta conectada"
                        icon.name: "user-identity"
                    }

                    Controls.MenuSeparator {}

                    Controls.MenuItem {
                        text: "Validar conta"
                        icon.name: "emblem-ok"
                        onTriggered: backend.validateAccount()
                    }

                    Controls.MenuItem {
                        text: "Desconectar conta"
                        icon.name: "system-log-out"
                        onTriggered: backend.disconnectAccount()
                    }
                }
            }
        }
    }
}
