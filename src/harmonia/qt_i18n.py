from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Slot

from .i18n import _, ngettext

LOGGER = logging.getLogger(__name__)


class QtI18n(QObject):
    """gettext for QML, exposed as the ``i18n`` context property.

    QML shares the GTK catalogs in po/: tools/update_translations.py extracts
    the i18n.tr(), trf(), ntr() and ntrf() calls from the .qml files. Placeholders
    use Python's str.format syntax, like the rest of the application:

        i18n.tr("Início")
        i18n.trf("Carregando {title}…", { title: item.title })
        i18n.ntr("{count} faixa", "{count} faixas", tracks.length)
        i18n.ntrf("{count} item · {size}", "{count} itens · {size}", n, { size: label })
    """

    @Slot(str, result=str)
    def tr(self, text: str) -> str:
        return _(text)

    @Slot(str, "QVariantMap", result=str)
    def trf(self, text: str, values: dict) -> str:
        return _format(_(text), values)

    @Slot(str, str, int, result=str)
    def ntr(self, singular: str, plural: str, count: int) -> str:
        return _format(ngettext(singular, plural, count), {"count": count})

    @Slot(str, str, int, "QVariantMap", result=str)
    def ntrf(self, singular: str, plural: str, count: int, values: dict) -> str:
        return _format(ngettext(singular, plural, count), {"count": count, **values})


def _format(template: str, values: dict) -> str:
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError):
        # A translation with a broken placeholder must not blank the label.
        LOGGER.warning("Tradução com marcadores inválidos: %r", template)
        return template
