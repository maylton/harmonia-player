"""Preferences > Biblioteca: how changes to the library and playlists behave."""

from __future__ import annotations

import gi

gi.require_version("Adw", "1")
from gi.repository import Adw  # noqa: E402

from ..i18n import _  # noqa: E402
from .rows import combo_row  # noqa: E402


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
    return group
