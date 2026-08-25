import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Dialogs as Dialogs
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Item {
    id: root

    signal connectRequested()

    Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: contentColumn.height + Kirigami.Units.gridUnit * 3
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Column {
            id: contentColumn
            x: Kirigami.Units.gridUnit * 1.5
            y: Kirigami.Units.gridUnit * 1.35
            width: Math.min(parent.width - Kirigami.Units.gridUnit * 3, Kirigami.Units.gridUnit * 46)
            spacing: Kirigami.Units.gridUnit * 1.5

            PageHeader {
                width: parent.width
                title: "Preferências"
                subtitle: "Configurações compartilhadas pelos frontends GTK e KDE"
            }

            Kirigami.Heading { text: "Conta"; level: 2 }

            Kirigami.FormLayout {
                width: parent.width

                Controls.Label {
                    Kirigami.FormData.label: "YouTube Music:"
                    text: backend.loggedIn ? "Conectada" : "Não conectada"
                }

                RowLayout {
                    Kirigami.FormData.label: "Sessão:"

                    Controls.Button {
                        visible: backend.loggedIn
                        text: "Validar"
                        icon.name: "emblem-ok"
                        onClicked: backend.validateAccount()
                    }

                    Controls.Button {
                        visible: backend.loggedIn
                        text: "Desconectar"
                        icon.name: "system-log-out"
                        onClicked: backend.disconnectAccount()
                    }

                    Controls.Button {
                        visible: !backend.loggedIn
                        text: "Conectar"
                        icon.name: "user-online"
                        onClicked: root.connectRequested()
                    }
                }
            }

            Kirigami.Separator { width: parent.width }
            Kirigami.Heading { text: "Streaming"; level: 2 }

            Kirigami.FormLayout {
                width: parent.width

                Controls.ComboBox {
                    id: qualityBox
                    Kirigami.FormData.label: "Qualidade de áudio:"
                    model: [
                        { "text": "Alta", "value": "high" },
                        { "text": "Média", "value": "medium" },
                        { "text": "Econômica", "value": "low" }
                    ]
                    textRole: "text"
                    Component.onCompleted: syncValue()
                    onActivated: backend.setQuality(model[currentIndex].value)

                    function syncValue() {
                        for (let i = 0; i < model.length; ++i) {
                            if (model[i].value === backend.quality) {
                                currentIndex = i
                                return
                            }
                        }
                    }
                }

                Controls.TextField {
                    id: languageField
                    Kirigami.FormData.label: "Idioma do YouTube Music:"
                    text: backend.language
                    placeholderText: "pt-BR"
                    selectByMouse: true
                }

                Controls.TextField {
                    id: regionField
                    Kirigami.FormData.label: "Região:"
                    text: backend.region
                    placeholderText: "BR"
                    maximumLength: 4
                    selectByMouse: true
                }

                Controls.Button {
                    text: "Salvar idioma e região"
                    icon.name: "document-save"
                    onClicked: backend.setLocale(languageField.text, regionField.text)
                }

                Controls.TextField {
                    id: proxyField
                    Kirigami.FormData.label: "Proxy HTTP(S):"
                    text: backend.proxy
                    placeholderText: "Sem proxy"
                    selectByMouse: true
                    onEditingFinished: backend.setProxy(text)
                }

                RowLayout {
                    Kirigami.FormData.label: "Cache de capas:"

                    Controls.Label { text: backend.artworkCacheLabel }

                    Controls.Button {
                        text: "Limpar"
                        icon.name: "edit-clear-history"
                        onClicked: backend.clearArtworkCache()
                    }
                }
            }

            Kirigami.Separator { width: parent.width }
            Kirigami.Heading { text: "Áudio"; level: 2 }

            Kirigami.FormLayout {
                width: parent.width

                Controls.ComboBox {
                    id: equalizerBox
                    Kirigami.FormData.label: "Equalizador:"
                    model: [
                        { "text": "Plano", "value": "flat" },
                        { "text": "Graves", "value": "bass" },
                        { "text": "Voz", "value": "vocal" },
                        { "text": "Agudos", "value": "treble" }
                    ]
                    textRole: "text"
                    Component.onCompleted: syncValue()
                    onActivated: backend.setEqualizer(model[currentIndex].value)

                    function syncValue() {
                        for (let i = 0; i < model.length; ++i) {
                            if (model[i].value === backend.equalizer) {
                                currentIndex = i
                                return
                            }
                        }
                    }
                }

                Controls.Switch {
                    Kirigami.FormData.label: "Normalização de volume:"
                    checked: backend.normalization
                    onToggled: backend.setNormalization(checked)
                }

                Controls.Switch {
                    Kirigami.FormData.label: "Pular silêncio:"
                    checked: backend.skipSilence
                    onToggled: backend.setSkipSilence(checked)
                }

                RowLayout {
                    Kirigami.FormData.label: "Velocidade:"

                    Controls.Slider {
                        id: speedSlider
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 16
                        from: 0.5
                        to: 2.0
                        stepSize: 0.05
                        value: backend.playbackSpeed
                        onMoved: backend.setPlaybackSpeed(value)
                    }

                    Controls.Label { text: speedSlider.value.toFixed(2) + "×" }
                }

                RowLayout {
                    Kirigami.FormData.label: "Tom:"

                    Controls.Slider {
                        id: pitchSlider
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 16
                        from: -12
                        to: 12
                        stepSize: 1
                        value: backend.pitch
                        onMoved: backend.setPitch(value)
                    }

                    Controls.Label {
                        text: (pitchSlider.value > 0 ? "+" : "") + Math.round(pitchSlider.value) + " st"
                    }
                }

                Controls.ComboBox {
                    Kirigami.FormData.label: "Temporizador:"
                    model: [
                        { "text": "Desligado", "value": 0 },
                        { "text": "15 minutos", "value": 15 },
                        { "text": "30 minutos", "value": 30 },
                        { "text": "1 hora", "value": 60 },
                        { "text": "1 hora e 30", "value": 90 }
                    ]
                    textRole: "text"
                    onActivated: backend.setSleepTimer(model[currentIndex].value)
                }
            }

            Kirigami.InlineMessage {
                width: parent.width
                type: Kirigami.MessageType.Information
                text: "O frontend KDE usa o mesmo NativePlayer/GStreamer do GTK. Equalizador, normalização, velocidade, tom e remoção de silêncio são aplicados pelo mesmo backend de áudio."
            }

            Kirigami.Separator { width: parent.width }
            Kirigami.Heading { text: "Dados e backup"; level: 2 }

            Kirigami.FormLayout {
                width: parent.width

                RowLayout {
                    Kirigami.FormData.label: "Backup portátil:"

                    Controls.Button {
                        text: "Exportar"
                        icon.name: "document-save"
                        onClicked: exportDialog.open()
                    }

                    Controls.Button {
                        text: "Restaurar"
                        icon.name: "document-open"
                        onClicked: restoreDialog.open()
                    }
                }
            }

            Kirigami.InlineMessage {
                width: parent.width
                type: Kirigami.MessageType.Information
                text: "No Plasma, cores e ícones seguem automaticamente o tema KDE. A opção de pacote de ícones GTK não é duplicada aqui porque é específica daquele toolkit."
            }
        }
    }

    Connections {
        target: backend

        function onPreferencesChanged() {
            qualityBox.syncValue()
            equalizerBox.syncValue()
        }
    }

    Dialogs.FileDialog {
        id: exportDialog
        title: "Exportar backup"
        fileMode: Dialogs.FileDialog.SaveFile
        defaultSuffix: "harmonia-backup"
        nameFilters: ["Backup do Harmonia (*.harmonia-backup)"]
        onAccepted: backend.exportBackup(selectedFile.toString())
    }

    Dialogs.FileDialog {
        id: restoreDialog
        title: "Restaurar backup"
        fileMode: Dialogs.FileDialog.OpenFile
        nameFilters: ["Backup do Harmonia (*.harmonia-backup)", "Todos os arquivos (*)"]
        onAccepted: backend.restoreBackup(selectedFile.toString())
    }
}
