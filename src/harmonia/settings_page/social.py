"""Preferences > Integrações sociais: Last.fm scrobbling and Discord Rich Presence."""

from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk  # noqa: E402

from ..i18n import _  # noqa: E402
from .rows import ENTRY_WIDTH, entry_row, pill_button, switch_row  # noqa: E402


def social_group(window) -> Adw.PreferencesGroup:
    group = Adw.PreferencesGroup(
        title=_("Integrações sociais"),
        description=_("Recursos opcionais; nenhum dado é enviado enquanto estiverem desligados."),
    )
    _add_lastfm_rows(window, group)
    _add_discord_rows(window, group)
    return group


def _add_lastfm_rows(window, group: Adw.PreferencesGroup) -> None:
    preferences = window.preferences
    credentials = window.lastfm_credentials.load()
    connected = credentials.session is not None
    scrobble = switch_row(
        _("Scrobble no Last.fm"),
        (
            _("Conectado como {username}").format(username=credentials.session.username)
            if connected
            else _("Configure uma chave de API e autorize a conta")
        ),
        preferences.lastfm_enabled and connected,
        lambda active: window._preference_changed("lastfm_enabled", active),
    )
    scrobble.set_sensitive(connected)
    group.add(scrobble)
    group.add(
        entry_row(
            _("Chave da API do Last.fm"),
            _("Crie uma API Account gratuita no site do Last.fm"),
            preferences.lastfm_api_key,
            _("API key"),
            lambda text: window._preference_changed("lastfm_api_key", text),
        )
    )
    group.add(_lastfm_secret_row(window, bool(credentials.api_secret)))

    authorization = Adw.ActionRow(
        title=_("Autorização do Last.fm"),
        subtitle=_("A autorização é concluída no navegador padrão"),
    )
    if connected:
        authorization.add_suffix(
            pill_button(_("Desconectar"), window._disconnect_lastfm, "destructive-action")
        )
    else:
        authorization.add_suffix(pill_button(_("Autorizar"), window._begin_lastfm_authorization))
        finish = pill_button(_("Concluir"), window._finish_lastfm_authorization, "suggested-action")
        finish.set_sensitive(bool(window._lastfm_pending_token))
        authorization.add_suffix(finish)
    group.add(authorization)


def _lastfm_secret_row(window, configured: bool) -> Adw.ActionRow:
    """The API secret goes to the keyring when the entry is confirmed or left."""
    row = Adw.ActionRow(
        title=_("Segredo da API do Last.fm"),
        subtitle=_("Armazenado no chaveiro do sistema"),
    )
    entry = Gtk.PasswordEntry(
        placeholder_text=_("Configurado") if configured else _("Secret"),
        show_peek_icon=True,
        valign=Gtk.Align.CENTER,
    )
    entry.set_size_request(ENTRY_WIDTH, -1)
    entry.connect("activate", lambda widget: window._configure_lastfm_secret(widget.get_text()))
    focus = Gtk.EventControllerFocus()
    focus.connect("leave", lambda *_: window._configure_lastfm_secret(entry.get_text()))
    entry.add_controller(focus)
    row.add_suffix(entry)
    return row


def _add_discord_rows(window, group: Adw.PreferencesGroup) -> None:
    preferences = window.preferences
    group.add(
        switch_row(
            _("Discord Rich Presence"),
            _("Mostra a faixa atual usando somente o IPC local do Discord"),
            preferences.discord_enabled,
            lambda active: window._discord_preference_changed("discord_enabled", active),
        )
    )
    group.add(
        entry_row(
            _("Client ID do Discord"),
            _("ID de uma aplicação criada no Discord Developer Portal"),
            preferences.discord_client_id,
            _("Client ID"),
            lambda text: window._discord_preference_changed("discord_client_id", text),
        )
    )
