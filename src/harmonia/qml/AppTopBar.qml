import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Controls.ToolBar {
    id: root

    property bool wideLayout: true
    property int currentView: 0
    signal navigationRequested()
    signal backRequested()
    signal searchRequested(string query)
    signal connectRequested()

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
                visible: !root.wideLayout
                text: "Navegação"
                icon.name: "sidebar-show"
                display: Controls.AbstractButton.IconOnly
                onClicked: root.navigationRequested()
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: text
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
                text: backend.loggedIn ? "Conta conectada" : "Conectar conta"
                icon.name: backend.loggedIn ? "user-available" : "user-offline"
                display: Controls.AbstractButton.IconOnly
                onClicked: backend.loggedIn ? accountMenu.open() : root.connectRequested()
                Controls.ToolTip.visible: hovered
                Controls.ToolTip.text: text

                Controls.Menu {
                    id: accountMenu
                    y: parent.height

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
