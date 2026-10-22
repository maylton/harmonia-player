"""Preferences > Biblioteca: how changes to the library and playlists behave, and lyrics."""

from __future__ import annotations

import gi

gi.require_version("Adw", "1")
from gi.repository import Adw  # noqa: E402

from .. import romaji  # noqa: E402
from ..i18n import _  # noqa: E402
from .rows import combo_row, switch_row  # noqa: E402


def library_group(window) -> Adw.PreferencesGroup:
    preferences = window.preferences
    group = Adw.PreferencesGroup(title=_("Biblioteca"))
    group.add(
        combo_row(
            _("Ao salvar numa playlist"),
            [(_("Adicionar no fim"), "end"), (_("Adicionar no início"), "start")],
            preferences.playlist_add_position,
            lambda value: window._preference_changed("playlist_add_position", value),
        )
    )
    available = romaji.available()
    row = switch_row(
        _("Romaji nas letras em japonês"),
        _("Mostra a leitura em letras latinas abaixo de cada verso")
        if available
        else _("Requer o fugashi e o dicionário unidic-lite"),
        preferences.romanize_lyrics and available,
        window._romanize_lyrics_changed,
    )
    row.set_sensitive(available)
    group.add(row)
    return group
