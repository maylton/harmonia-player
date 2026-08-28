import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: root

    property int castIndex: castBox.currentIndex

    spacing: Kirigami.Units.gridUnit * 1.15

    SettingsSection {
        Layout.fillWidth: true
        title: "Integrações sociais"
        subtitle: "Last.fm e Discord são opcionais e reutilizam as mesmas configurações do frontend GTK."
        iconName: "preferences-web-browser-identification"

        Kirigami.FormLayout {
            Layout.fillWidth: true

            Controls.Switch {
                Kirigami.FormData.label: "Scrobble no Last.fm:"
                enabled: integrations.lastFmConnected
                checked: integrations.lastFmEnabled && integrations.lastFmConnected
                onToggled: integrations.setLastFmEnabled(checked)
            }

            Controls.Label {
                Kirigami.FormData.label: "Conta Last.fm:"
                text: integrations.lastFmConnected
                      ? "Conectado como " + integrations.lastFmUsername
                      : "Não conectada"
                opacity: 0.72
            }

            Controls.TextField {
                id: lastFmKey
                Kirigami.FormData.label: "API key:"
                Layout.preferredWidth: Kirigami.Units.gridUnit * 20
                text: integrations.lastFmApiKey
                placeholderText: "Last.fm API key"
                selectByMouse: true
                onEditingFinished: integrations.setLastFmApiKey(text)
            }

            RowLayout {
                Kirigami.FormData.label: "API secret:"

                Controls.TextField {
                    id: lastFmSecret
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 16
                    placeholderText: integrations.lastFmSecretConfigured ? "Configurado" : "Secret"
                    echoMode: TextInput.Password
                    selectByMouse: true
                }

                Controls.Button {
                    text: "Salvar"
                    icon.name: "document-save"
                    enabled: lastFmSecret.text.trim().length > 0
                    onClicked: {
                        integrations.setLastFmSecret(lastFmSecret.text)
                        lastFmSecret.clear()
                    }
                }
            }

            RowLayout {
                Kirigami.FormData.label: "Autorização:"

                Controls.Button {
                    visible: !integrations.lastFmConnected
                    text: "Autorizar"
                    icon.name: "internet-web-browser"
                    onClicked: integrations.beginLastFmAuthorization()
                }

                Controls.Button {
                    visible: !integrations.lastFmConnected
                    text: "Concluir"
                    highlighted: true
                    enabled: integrations.lastFmAuthorizationPending
                    onClicked: integrations.finishLastFmAuthorization()
                }

                Controls.Button {
                    visible: integrations.lastFmConnected
                    text: "Desconectar"
                    icon.name: "system-log-out"
                    onClicked: integrations.disconnectLastFm()
                }
            }

            Controls.Switch {
                Kirigami.FormData.label: "Discord Rich Presence:"
                checked: integrations.discordEnabled
                onToggled: integrations.setDiscordEnabled(checked)
            }

            Controls.TextField {
                Kirigami.FormData.label: "Discord Client ID:"
                Layout.preferredWidth: Kirigami.Units.gridUnit * 20
                text: integrations.discordClientId
                placeholderText: "Client ID da aplicação Discord"
                selectByMouse: true
                onEditingFinished: integrations.setDiscordClientId(text)
            }
        }

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            type: Kirigami.MessageType.Information
            text: "O Rich Presence usa somente o socket IPC local do Discord; o Last.fm usa o chaveiro do sistema para o segredo e a sessão."
        }
    }

    SettingsSection {
        Layout.fillWidth: true
        title: "Listen Together"
        subtitle: "Sincroniza fila, faixa, posição e play/pause entre dispositivos na mesma rede local."
        iconName: "network-connect"

        Kirigami.FormLayout {
            Layout.fillWidth: true

            Controls.Label {
                Kirigami.FormData.label: "Sessão:"
                text: integrations.togetherStatus
                opacity: 0.72
            }

            RowLayout {
                Kirigami.FormData.label: "Hospedar:"

                Controls.Button {
                    visible: !integrations.togetherActive
                    text: "Criar sessão"
                    highlighted: true
                    icon.name: "list-add"
                    onClicked: integrations.createTogetherSession()
                }

                Controls.Button {
                    visible: integrations.togetherActive
                    text: "Sair"
                    icon.name: "system-log-out"
                    onClicked: integrations.leaveTogetherSession()
                }
            }

            RowLayout {
                visible: integrations.togetherShareUrl.length > 0
                Kirigami.FormData.label: "Link da sessão:"
                spacing: Kirigami.Units.smallSpacing

                Controls.TextField {
                    id: sessionLinkField
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 23
                    text: integrations.togetherShareUrl
                    readOnly: true
                    selectByMouse: true
                }

                Controls.Button {
                    text: "Copiar"
                    icon.name: "edit-copy"
                    onClicked: {
                        sessionLinkField.selectAll()
                        sessionLinkField.copy()
                        sessionLinkField.deselect()
                    }
                }
            }

            RowLayout {
                visible: !integrations.togetherActive
                Kirigami.FormData.label: "Entrar com link:"

                Controls.TextField {
                    id: togetherLink
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 23
                    placeholderText: "harmonia://listen-together…"
                    selectByMouse: true
                }

                Controls.Button {
                    text: "Entrar"
                    enabled: togetherLink.text.trim().length > 0
                    onClicked: integrations.joinTogetherSession(togetherLink.text)
                }
            }
        }
    }

    SettingsSection {
        Layout.fillWidth: true
        title: "Reconhecimento de música"
        subtitle: "Captura temporariamente 12 segundos do microfone e apaga a amostra depois da consulta."
        iconName: "audio-input-microphone"

        Kirigami.FormLayout {
            Layout.fillWidth: true

            Controls.ComboBox {
                id: providerBox
                Kirigami.FormData.label: "Provedor:"
                model: [
                    { "text": "AudD", "value": "audd" },
                    { "text": "API compatível com AudD", "value": "custom" }
                ]
                textRole: "text"
                Component.onCompleted: syncValue()
                onActivated: integrations.setRecognitionProvider(model[currentIndex].value)

                function syncValue() {
                    currentIndex = integrations.recognitionProvider === "custom" ? 1 : 0
                }
            }

            Controls.TextField {
                Kirigami.FormData.label: "Endpoint:"
                Layout.preferredWidth: Kirigami.Units.gridUnit * 22
                enabled: integrations.recognitionProvider === "custom"
                text: integrations.recognitionEndpoint
                placeholderText: "https://api.audd.io/"
                selectByMouse: true
                onEditingFinished: integrations.setRecognitionEndpoint(text)
            }

            RowLayout {
                Kirigami.FormData.label: "Token da API:"

                Controls.TextField {
                    id: recognitionToken
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 16
                    placeholderText: integrations.recognitionTokenConfigured ? "Configurado" : "Token"
                    echoMode: TextInput.Password
                    selectByMouse: true
                }

                Controls.Button {
                    text: "Salvar"
                    enabled: recognitionToken.text.trim().length > 0
                    onClicked: {
                        integrations.setRecognitionToken(recognitionToken.text)
                        recognitionToken.clear()
                    }
                }

                Controls.Button {
                    text: "Reconhecer agora"
                    highlighted: true
                    icon.name: "audio-input-microphone"
                    enabled: integrations.recognitionTokenConfigured
                    onClicked: integrations.recognizeMusic()
                }
            }
        }
    }

    SettingsSection {
        Layout.fillWidth: true
        title: "Transmitir para dispositivo"
        subtitle: "Procura Media Renderers UPnP/DLNA na rede e transfere a reprodução atual."
        iconName: "video-display"

        Kirigami.FormLayout {
            Layout.fillWidth: true

            Controls.Label {
                visible: integrations.castConnected
                Kirigami.FormData.label: "Reproduzindo em:"
                text: integrations.castDeviceName
                font.weight: Font.DemiBold
            }

            RowLayout {
                Kirigami.FormData.label: "Dispositivos:"

                Controls.ComboBox {
                    id: castBox
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 18
                    model: integrations.castDevices
                    textRole: "name"
                    enabled: !integrations.castConnected && count > 0
                }

                Controls.Button {
                    text: "Procurar"
                    icon.name: "view-refresh"
                    enabled: !integrations.castConnected
                    onClicked: integrations.scanCastDevices()
                }

                Controls.Button {
                    visible: !integrations.castConnected
                    text: "Conectar"
                    highlighted: true
                    enabled: castBox.currentIndex >= 0 && castBox.count > 0 && backend.currentId.length > 0
                    onClicked: integrations.connectCastDevice(castBox.currentIndex)
                }

                Controls.Button {
                    visible: integrations.castConnected
                    text: "Desconectar"
                    icon.name: "network-disconnect"
                    onClicked: integrations.disconnectCast()
                }
            }
        }

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: backend.currentId.length === 0
            type: Kirigami.MessageType.Information
            text: "Comece a reproduzir uma faixa antes de conectar a um dispositivo."
        }
    }

    Connections {
        target: integrations

        function onChanged() {
            providerBox.syncValue()
        }
    }
}
