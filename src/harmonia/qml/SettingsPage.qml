import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Item {
    id: root

    Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: contentColumn.height + Kirigami.Units.gridUnit * 3
        clip: true

        Column {
            id: contentColumn
            x: Kirigami.Units.gridUnit * 1.5
            y: Kirigami.Units.gridUnit * 1.35
            width: Math.min(parent.width - Kirigami.Units.gridUnit * 3, Kirigami.Units.gridUnit * 42)
            spacing: Kirigami.Units.gridUnit * 1.4

            PageHeader {
                width: parent.width
                title: "Preferências"
                subtitle: "Configurações compartilhadas pelos frontends GTK e KDE"
            }

            Kirigami.FormLayout {
                width: parent.width

                Controls.ComboBox {
                    id: qualityBox
                    Kirigami.FormData.label: "Qualidade de áudio:"
                    model: [
                        { "text": "Baixa", "value": "low" },
                        { "text": "Média", "value": "medium" },
                        { "text": "Alta", "value": "high" }
                    ]
                    textRole: "text"

                    Component.onCompleted: {
                        for (let i = 0; i < model.length; ++i) {
                            if (model[i].value === backend.quality) {
                                currentIndex = i
                                break
                            }
                        }
                    }

                    onActivated: backend.setQuality(model[currentIndex].value)
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
            }

            Kirigami.InlineMessage {
                width: parent.width
                visible: true
                type: Kirigami.MessageType.Information
                text: "Equalizador, normalização, velocidade, pitch e remoção de silêncio continuam disponíveis no frontend GTK. Eles serão portados quando o backend de áudio Qt atingir paridade com o GStreamer."
            }
        }
    }
}
