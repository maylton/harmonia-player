"""Preferences > Streaming and Dados e backup."""

from __future__ import annotations

import gi

gi.require_version("Adw", "1")
from gi.repository import Adw  # noqa: E402

from ..i18n import _  # noqa: E402
from .rows import combo_row, entry_row, pill_button  # noqa: E402


def streaming_group(window) -> Adw.PreferencesGroup:
    preferences = window.preferences
    changed = window._preference_changed
    group = Adw.PreferencesGroup(
        title=_("Streaming"),
        description=_("Estas opções são aplicadas à próxima requisição ao YouTube Music."),
    )
    group.add(
        combo_row(
            _("Qualidade do áudio"),
            [(_("Alta"), "high"), (_("Média"), "medium"), (_("Econômica"), "low")],
            preferences.quality,
            lambda value: changed("quality", value),
        )
    )
    group.add(
        combo_row(
            _("Idioma"),
            [
                (_("Português (Brasil)"), "pt-BR"),
                (_("English"), "en-US"),
                (_("Español"), "es-ES"),
                ("日本語", "ja-JP"),
            ],
            preferences.language,
            lambda value: changed("language", value),
        )
    )
    group.add(
        combo_row(
            _("Região"),
            [
                (_("Brasil"), "BR"),
                (_("Estados Unidos"), "US"),
                (_("Portugal"), "PT"),
                (_("Japão"), "JP"),
            ],
            preferences.region,
            lambda value: changed("region", value),
        )
    )
    group.add(
        entry_row(
            _("Proxy HTTP(S)"),
            _("Opcional · exemplo: http://127.0.0.1:8080"),
            preferences.proxy,
            _("Sem proxy"),
            lambda text: changed("proxy", text),
        )
    )
    cache = Adw.ActionRow(
        title=_("Cache de capas"),
        subtitle=_("{size} armazenados").format(size=window._format_bytes(window._cache_size())),
    )
    cache.add_suffix(pill_button(_("Limpar"), lambda: window._clear_artwork_cache(cache)))
    group.add(cache)
    return group


def backup_group(window) -> Adw.PreferencesGroup:
    group = Adw.PreferencesGroup(
        title=_("Dados e backup"),
        description=_(
            "Salva biblioteca, histórico e preferências sem incluir credenciais ou áudio."
        ),
    )
    backup = Adw.ActionRow(
        title=_("Backup portátil"),
        subtitle=_("Compatível com outras instalações do Harmonia"),
    )
    backup.add_suffix(pill_button(_("Exportar"), window._export_backup_dialog))
    backup.add_suffix(pill_button(_("Restaurar"), window._restore_backup_dialog))
    group.add(backup)
    return group
