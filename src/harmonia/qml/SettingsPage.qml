import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Dialogs as Dialogs
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Item {
    id: root

    property url pendingRestoreUrl: ""

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
                title: i18n.tr("Preferências")
                subtitle: i18n.tr("Conta, aparência, streaming, áudio, integrações e dados — compartilhados entre GTK e KDE")
            }

            SettingsSection {
                width: parent.width
                title: i18n.tr("Conta")
                subtitle: i18n.tr("Sessão usada para biblioteca, recomendações e sincronização do YouTube Music.")
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
                                     : i18n.tr("YouTube Music conectado"))
                                  : i18n.tr("Conta não conectada")
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }

                        Controls.Label {
                            Layout.fillWidth: true
                            text: backend.loggedIn
                                  ? (backend.accountEmail.length > 0
                                     ? backend.accountEmail
                                     : i18n.tr("Sessão disponível para sincronização"))
                                  : i18n.tr("Conecte sua conta para carregar biblioteca e recomendações.")
                            opacity: 0.62
                            elide: Text.ElideRight
                        }
                    }

                    Controls.Button {
                        visible: backend.loggedIn
                        text: i18n.tr("Validar")
                        icon.name: "emblem-ok"
                        onClicked: backend.validateAccount()
                    }

                    Controls.Button {
                        visible: backend.loggedIn
                        text: i18n.tr("Desconectar")
                        icon.name: "system-log-out"
                        onClicked: backend.disconnectAccount()
                    }

                    Controls.Button {
                        visible: !backend.loggedIn
                        text: i18n.tr("Conectar")
                        icon.name: "user-online"
                        highlighted: true
                        onClicked: root.connectRequested()
                    }
                }
            }

            SettingsSection {
                width: parent.width
                title: i18n.tr("Aparência")
                subtitle: i18n.tr("Integração visual com o Plasma e o fundo ambiente do player.")
                iconName: "preferences-desktop-theme"

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.largeSpacing

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2

                        Controls.Label {
                            Layout.fillWidth: true
                            text: i18n.tr("Fundo ambiente desfocado")
                            font.weight: Font.DemiBold
                        }

                        Controls.Label {
                            Layout.fillWidth: true
                            text: i18n.tr("Usa a capa atual para colorir o fundo e tornar as superfícies mais translúcidas.")
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
                    text: i18n.tr("No Plasma, cores e ícones seguem automaticamente o tema KDE.")
                }
            }

            SettingsSection {
                width: parent.width
                title: i18n.tr("Streaming")
                subtitle: i18n.tr("Qualidade, localização, rede e cache das capas.")
                iconName: "network-connect"

                Kirigami.FormLayout {
                    Layout.fillWidth: true

                    Controls.ComboBox {
                        id: qualityBox
                        Kirigami.FormData.label: i18n.tr("Qualidade de áudio:")
                        model: [
                            { "text": i18n.tr("Alta"), "value": "high" },
                            { "text": i18n.tr("Média"), "value": "medium" },
                            { "text": i18n.tr("Econômica"), "value": "low" }
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
                        Kirigami.FormData.label: i18n.tr("Localização:")

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
                            text: i18n.tr("Salvar")
                            icon.name: "document-save"
                            onClicked: backend.setLocale(languageField.text, regionField.text)
                        }
                    }

                    Controls.TextField {
                        id: proxyField
                        Kirigami.FormData.label: i18n.tr("Proxy HTTP(S):")
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 18
                        text: backend.proxy
                        placeholderText: i18n.tr("Sem proxy")
                        selectByMouse: true
                        onEditingFinished: backend.setProxy(text)
                    }

                    RowLayout {
                        Kirigami.FormData.label: i18n.tr("Cache de capas:")

                        Controls.Label {
                            text: backend.artworkCacheLabel
                            opacity: 0.72
                        }

                        Controls.Button {
                            text: i18n.tr("Limpar cache")
                            icon.name: "edit-clear-history"
                            onClicked: backend.clearArtworkCache()
                        }
                    }
                }
            }

            SettingsSection {
                width: parent.width
                title: i18n.tr("Áudio")
                subtitle: i18n.tr("Ajustes processados pelo mesmo NativePlayer/GStreamer usado no frontend GTK.")
                iconName: "audio-volume-high"

                Kirigami.FormLayout {
                    Layout.fillWidth: true

                    Controls.ComboBox {
                        id: equalizerBox
                        Kirigami.FormData.label: i18n.tr("Equalizador:")
                        model: [
                            { "text": i18n.tr("Plano"), "value": "flat" },
                            { "text": i18n.tr("Graves"), "value": "bass" },
                            { "text": i18n.tr("Voz"), "value": "vocal" },
                            { "text": i18n.tr("Agudos"), "value": "treble" }
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
                        Kirigami.FormData.label: i18n.tr("Normalização de volume:")
                        checked: backend.normalization
                        onToggled: backend.setNormalization(checked)
                    }

                    Controls.Switch {
                        Kirigami.FormData.label: i18n.tr("Pular silêncio:")
                        checked: backend.skipSilence
                        onToggled: backend.setSkipSilence(checked)
                    }

                    RowLayout {
                        Kirigami.FormData.label: i18n.tr("Velocidade:")

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
                        Kirigami.FormData.label: i18n.tr("Tom:")

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
                        Kirigami.FormData.label: i18n.tr("Temporizador:")
                        model: [
                            { "text": i18n.tr("Desligado"), "value": 0 },
                            { "text": i18n.tr("15 minutos"), "value": 15 },
                            { "text": i18n.tr("30 minutos"), "value": 30 },
                            { "text": i18n.tr("1 hora"), "value": 60 },
                            { "text": i18n.tr("1 hora e 30"), "value": 90 }
                        ]
                        textRole: "text"
                        onActivated: backend.setSleepTimer(model[currentIndex].value)
                    }
                }
            }

            IntegrationsSettings {
                width: parent.width
            }

            SettingsSection {
                width: parent.width
                title: i18n.tr("Dados e backup")
                subtitle: i18n.tr("Exporte ou restaure um pacote portátil com os dados do Harmonia.")
                iconName: "document-save"

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.largeSpacing

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2

                        Controls.Label {
                            Layout.fillWidth: true
                            text: i18n.tr("Backup portátil")
                            font.weight: Font.DemiBold
                        }

                        Controls.Label {
                            Layout.fillWidth: true
                            text: i18n.tr("Use o mesmo arquivo para migrar dados entre instalações e frontends.")
                            opacity: 0.62
                            wrapMode: Text.WordWrap
                        }
                    }

                    Controls.Button {
                        text: i18n.tr("Exportar")
                        icon.name: "document-save"
                        onClicked: exportDialog.open()
                    }

                    Controls.Button {
                        text: i18n.tr("Restaurar")
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
        title: i18n.tr("Exportar backup")
        fileMode: Dialogs.FileDialog.SaveFile
        defaultSuffix: "harmonia-backup"
        nameFilters: [i18n.tr("Backup do Harmonia (*.harmonia-backup)")]
        onAccepted: backend.exportBackup(selectedFile.toString())
    }

    Dialogs.FileDialog {
        id: restoreDialog
        title: i18n.tr("Restaurar backup")
        fileMode: Dialogs.FileDialog.OpenFile
        nameFilters: [i18n.tr("Backup do Harmonia (*.harmonia-backup)"), i18n.tr("Todos os arquivos (*)")]
        onAccepted: {
            root.pendingRestoreUrl = selectedFile
            restoreConfirmDialog.open()
        }
    }

    Controls.Dialog {
        id: restoreConfirmDialog
        parent: Controls.Overlay.overlay
        anchors.centerIn: parent
        modal: true
        title: i18n.tr("Restaurar backup?")
        standardButtons: Controls.Dialog.Ok | Controls.Dialog.Cancel

        contentItem: Controls.Label {
            text: i18n.tr("A restauração substitui os dados atuais do Harmonia pelos dados do backup selecionado.")
            wrapMode: Text.WordWrap
            Layout.preferredWidth: Kirigami.Units.gridUnit * 24
        }

        onAccepted: {
            backend.restoreBackup(root.pendingRestoreUrl.toString())
            root.pendingRestoreUrl = ""
        }
        onRejected: root.pendingRestoreUrl = ""
    }
}
