import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Dialogs as Dialogs
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Item {
    id: root

    signal connectRequested()

    Flickable {
        id: settingsFlick
        anchors.fill: parent
        contentWidth: width
        contentHeight: contentColumn.height + Kirigami.Units.gridUnit * 3
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Column {
            id: contentColumn
            width: Math.min(
                Math.max(0, settingsFlick.width - Kirigami.Units.gridUnit * 3),
                Kirigami.Units.gridUnit * 50
            )
            x: Math.max(
                Kirigami.Units.gridUnit * 1.5,
                (settingsFlick.width - width) / 2
            )
            y: Kirigami.Units.gridUnit * 1.35
            spacing: Kirigami.Units.gridUnit * 1.15

            PageHeader {
                width: parent.width
                title: "Preferências"
                subtitle: "Conta, aparência, streaming, áudio e dados — compartilhados entre GTK e KDE"
            }

            SettingsSection {
                width: parent.width
                title: "Conta"
                subtitle: "Sessão usada para biblioteca, recomendações e sincronização do YouTube Music."
                iconName: "user-identity"

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.largeSpacing

                    CoverArt {
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 3.2
                        Layout.preferredHeight: width
                        source: backend.loggedIn ? backend.accountAvatarUrl : ""
                        kind: "artist"
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2

                        Controls.Label {
                            Layout.fillWidth: true
                            text: backend.loggedIn
                                  ? (backend.accountName.length > 0
                                     ? backend.accountName
                                     : "YouTube Music conectado")
                                  : "Conta não conectada"
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }

                        Controls.Label {
                            Layout.fillWidth: true
                            text: backend.loggedIn
                                  ? (backend.accountEmail.length > 0
                                     ? backend.accountEmail
                                     : "Sessão disponível para sincronização")
                                  : "Conecte sua conta para carregar biblioteca e recomendações."
                            opacity: 0.62
                            elide: Text.ElideRight
                        }
                    }

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
                        highlighted: true
                        onClicked: root.connectRequested()
                    }
                }
            }

            SettingsSection {
                width: parent.width
                title: "Aparência"
                subtitle: "Integração visual com o Plasma e o fundo ambiente do player."
                iconName: "preferences-desktop-theme"

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.largeSpacing

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2

                        Controls.Label {
                            Layout.fillWidth: true
                            text: "Fundo ambiente desfocado"
                            font.weight: Font.DemiBold
                        }

                        Controls.Label {
                            Layout.fillWidth: true
                            text: "Usa a capa atual para colorir o fundo e tornar as superfícies mais translúcidas."
                            opacity: 0.62
                            wrapMode: Text.WordWrap
                        }
                    }

                    Controls.Switch {
                        checked: preferences.backgroundBlur
                        onToggled: preferences.setBackgroundBlur(checked)
                    }
                }

                Kirigami.InlineMessage {
                    Layout.fillWidth: true
                    type: Kirigami.MessageType.Information
                    text: "A mesma preferência é usada pelo frontend GTK. No Plasma, cores e ícones seguem automaticamente o tema KDE."
                }
            }

            SettingsSection {
                width: parent.width
                title: "Streaming"
                subtitle: "Qualidade, localização, rede e cache das capas."
                iconName: "network-connect"

                Kirigami.FormLayout {
                    Layout.fillWidth: true

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

                    RowLayout {
                        Kirigami.FormData.label: "Localização:"

                        Controls.TextField {
                            id: languageField
                            Layout.preferredWidth: Kirigami.Units.gridUnit * 10
                            text: backend.language
                            placeholderText: "pt-BR"
                            selectByMouse: true
                        }

                        Controls.TextField {
                            id: regionField
                            Layout.preferredWidth: Kirigami.Units.gridUnit * 5
                            text: backend.region
                            placeholderText: "BR"
                            maximumLength: 4
                            selectByMouse: true
                        }

                        Controls.Button {
                            text: "Salvar"
                            icon.name: "document-save"
                            onClicked: backend.setLocale(languageField.text, regionField.text)
                        }
                    }

                    Controls.TextField {
                        id: proxyField
                        Kirigami.FormData.label: "Proxy HTTP(S):"
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 18
                        text: backend.proxy
                        placeholderText: "Sem proxy"
                        selectByMouse: true
                        onEditingFinished: backend.setProxy(text)
                    }

                    RowLayout {
                        Kirigami.FormData.label: "Cache de capas:"

                        Controls.Label {
                            text: backend.artworkCacheLabel
                            opacity: 0.72
                        }

                        Controls.Button {
                            text: "Limpar cache"
                            icon.name: "edit-clear-history"
                            onClicked: backend.clearArtworkCache()
                        }
                    }
                }
            }

            SettingsSection {
                width: parent.width
                title: "Áudio"
                subtitle: "Ajustes processados pelo mesmo NativePlayer/GStreamer usado no frontend GTK."
                iconName: "audio-volume-high"

                Kirigami.FormLayout {
                    Layout.fillWidth: true

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

                        Controls.Label {
                            text: speedSlider.value.toFixed(2) + "×"
                            font.features: { "tnum": 1 }
                        }
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
                            font.features: { "tnum": 1 }
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
            }

            SettingsSection {
                width: parent.width
                title: "Dados e backup"
                subtitle: "Exporte ou restaure um pacote portátil com os dados do Harmonia."
                iconName: "document-save"

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.largeSpacing

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2

                        Controls.Label {
                            Layout.fillWidth: true
                            text: "Backup portátil"
                            font.weight: Font.DemiBold
                        }

                        Controls.Label {
                            Layout.fillWidth: true
                            text: "Use o mesmo arquivo para migrar dados entre instalações e frontends."
                            opacity: 0.62
                            wrapMode: Text.WordWrap
                        }
                    }

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
