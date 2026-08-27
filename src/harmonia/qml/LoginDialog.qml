import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import QtWebEngine
import org.kde.kirigami as Kirigami

Controls.Popup {
    id: root

    property bool manualMode: false
    readonly property bool connectionError: backend.statusText.indexOf("Não foi possível conectar") === 0

    modal: true
    focus: true
    closePolicy: Controls.Popup.CloseOnEscape
    padding: 0
    width: parent
           ? Math.min(parent.width - Kirigami.Units.gridUnit * 2, Kirigami.Units.gridUnit * 52)
           : Kirigami.Units.gridUnit * 52
    height: parent
            ? Math.min(parent.height - Kirigami.Units.gridUnit * 2, Kirigami.Units.gridUnit * 42)
            : Kirigami.Units.gridUnit * 42
    x: parent ? (parent.width - width) / 2 : 0
    y: parent ? (parent.height - height) / 2 : 0

    function openLogin() {
        manualMode = false
        cookieInput.clear()
        auth.beginLogin()
        browser.url = auth.loginUrl
        open()
    }

    function showManualLogin() {
        auth.cancelLogin()
        browser.url = "about:blank"
        manualMode = true
    }

    function showWebLogin() {
        manualMode = false
        auth.beginLogin()
        browser.url = auth.loginUrl
    }

    onClosed: {
        auth.cancelLogin()
        browser.url = "about:blank"
        cookieInput.clear()
        manualMode = false
    }

    Connections {
        target: backend

        function onSessionChanged() {
            if (backend.loggedIn && root.opened)
                root.close()
        }
    }

    background: Rectangle {
        radius: Kirigami.Units.cornerRadius
        color: Kirigami.Theme.backgroundColor
        border.width: 1
        border.color: Kirigami.Theme.separatorColor
    }

    contentItem: ColumnLayout {
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.largeSpacing
            Layout.rightMargin: Kirigami.Units.largeSpacing
            Layout.topMargin: Kirigami.Units.smallSpacing
            Layout.bottomMargin: Kirigami.Units.smallSpacing
            spacing: Kirigami.Units.smallSpacing

            Controls.ToolButton {
                icon.name: "go-previous"
                text: "Voltar"
                display: Controls.AbstractButton.IconOnly
                onClicked: {
                    if (root.manualMode) {
                        root.showWebLogin()
                    } else if (browser.canGoBack) {
                        browser.goBack()
                    } else {
                        root.close()
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0

                Controls.Label {
                    Layout.fillWidth: true
                    text: "Conectar ao YouTube Music"
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }

                Controls.Label {
                    Layout.fillWidth: true
                    text: root.manualMode
                          ? "Conexão manual por cookie"
                          : "Login seguro na página do Google"
                    opacity: 0.62
                    elide: Text.ElideRight
                }
            }

            Controls.BusyIndicator {
                visible: backend.busy
                running: visible
                implicitWidth: Kirigami.Units.gridUnit * 1.4
                implicitHeight: implicitWidth
            }

            Controls.Button {
                text: root.manualMode ? "Login pelo Google" : "Usar cookie manualmente"
                icon.name: root.manualMode ? "internet-services" : "document-edit"
                enabled: !backend.busy
                onClicked: root.manualMode ? root.showWebLogin() : root.showManualLogin()
            }

            Controls.ToolButton {
                icon.name: "window-close"
                text: "Fechar"
                display: Controls.AbstractButton.IconOnly
                onClicked: root.close()
            }
        }

        Kirigami.Separator {
            Layout.fillWidth: true
        }

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.largeSpacing
            Layout.rightMargin: Kirigami.Units.largeSpacing
            Layout.topMargin: visible ? Kirigami.Units.smallSpacing : 0
            visible: root.connectionError
            type: Kirigami.MessageType.Error
            text: backend.statusText
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: root.manualMode ? 1 : 0

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true

                WebEngineView {
                    id: browser
                    anchors.fill: parent
                    url: "about:blank"

                    onUrlChanged: auth.navigationChanged(url.toString())
                }
            }

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true

                ColumnLayout {
                    anchors.centerIn: parent
                    width: Math.min(parent.width - Kirigami.Units.gridUnit * 4,
                                    Kirigami.Units.gridUnit * 34)
                    spacing: Kirigami.Units.largeSpacing

                    Kirigami.Icon {
                        Layout.alignment: Qt.AlignHCenter
                        source: "dialog-password"
                        implicitWidth: Kirigami.Units.gridUnit * 3
                        implicitHeight: implicitWidth
                    }

                    Controls.Label {
                        Layout.fillWidth: true
                        text: "Cole os cookies de music.youtube.com somente se o login pelo Google não funcionar. O Harmonia valida a sessão antes de salvá-la no Secret Service."
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                    }

                    Controls.TextArea {
                        id: cookieInput
                        Layout.fillWidth: true
                        Layout.preferredHeight: Kirigami.Units.gridUnit * 9
                        placeholderText: "Cookie do music.youtube.com"
                        wrapMode: TextEdit.WrapAnywhere
                        selectByMouse: true
                        enabled: !backend.busy
                    }

                    Controls.Button {
                        Layout.alignment: Qt.AlignHCenter
                        text: backend.busy ? "Validando sessão…" : "Conectar"
                        icon.name: "user-online"
                        highlighted: true
                        enabled: cookieInput.text.trim().length > 0 && !backend.busy
                        onClicked: backend.connectCookie(cookieInput.text)
                    }
                }
            }
        }

        Controls.Label {
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.largeSpacing
            Layout.rightMargin: Kirigami.Units.largeSpacing
            Layout.topMargin: Kirigami.Units.smallSpacing
            Layout.bottomMargin: Kirigami.Units.smallSpacing
            visible: !root.manualMode
            text: backend.busy
                  ? "Login concluído. Validando a sessão do YouTube Music…"
                  : "O Harmonia não lê sua senha: o formulário acima é renderizado pelo Google no Qt WebEngine."
            opacity: 0.62
            wrapMode: Text.WordWrap
        }
    }
}
