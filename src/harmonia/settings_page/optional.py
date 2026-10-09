"""Preferences > Listen Together, music recognition and casting."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from ..i18n import _  # noqa: E402


def _pill(label: str, callback, *, suggested: bool = False) -> Gtk.Button:
    button = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
    button.add_css_class("pill")
    if suggested:
        button.add_css_class("suggested-action")
    button.connect("clicked", lambda *_: callback())
    return button


def together_group(window) -> Adw.PreferencesGroup:
    group = Adw.PreferencesGroup(
        title=_("Listen Together"),
        description=_("Sincroniza fila e reprodução entre dispositivos na mesma rede local."),
    )
    status = Adw.ActionRow(title=_("Sessão compartilhada"), subtitle=window._together_status())
    if window.together_host or window.together_client:
        status.add_suffix(_pill(_("Sair"), window._leave_together_session))
    else:
        status.add_suffix(_pill(_("Criar sessão"), window._create_together_session, suggested=True))
    group.add(status)
    join = Adw.ActionRow(
        title=_("Entrar com link"),
        subtitle=_("Cole o link harmonia:// enviado pelo anfitrião"),
    )
    join_entry = Gtk.Entry(placeholder_text="harmonia://listen-together…", valign=Gtk.Align.CENTER)
    join_entry.set_size_request(310, -1)
    join.add_suffix(join_entry)
    join.add_suffix(
        _pill(_("Entrar"), lambda: window._join_together_session(join_entry.get_text()))
    )
    group.add(join)
    if window._together_share_url:
        share = Adw.ActionRow(title=_("Link da sessão"), subtitle=window._together_share_url)
        share.add_suffix(
            _pill(
                _("Copiar"),
                lambda: Gdk.Display.get_default().get_clipboard().set(window._together_share_url),
            )
        )
        group.add(share)
    return group


def recognition_group(window) -> Adw.PreferencesGroup:
    preferences = window.preferences
    group = Adw.PreferencesGroup(
        title=_("Reconhecimento de música"),
        description=_("Captura temporariamente 12 segundos do microfone e apaga a amostra."),
    )
    provider = Adw.ComboRow(
        title=_("Provedor"),
        model=Gtk.StringList.new(["AudD", _("API compatível com AudD")]),
    )
    provider.set_selected(1 if preferences.recognition_provider == "custom" else 0)
    provider.connect(
        "notify::selected",
        lambda row, _pspec: window._preference_changed(
            "recognition_provider", "custom" if row.get_selected() == 1 else "audd"
        ),
    )
    group.add(provider)
    endpoint = Adw.ActionRow(
        title=_("Endpoint do provedor"),
        subtitle=_("Usado somente no modo de API compatível"),
    )
    endpoint_entry = Gtk.Entry(
        text=preferences.recognition_endpoint,
        placeholder_text="https://api.audd.io/",
        valign=Gtk.Align.CENTER,
    )
    endpoint_entry.set_size_request(310, -1)
    endpoint_entry.connect(
        "changed",
        lambda entry: window._preference_changed("recognition_endpoint", entry.get_text().strip()),
    )
    endpoint.add_suffix(endpoint_entry)
    group.add(endpoint)
    group.add(_recognition_token_row(window))
    return group


def _recognition_token_row(window) -> Adw.ActionRow:
    """The AudD token, saved to the keyring, and the button that listens."""
    tokens = window.recognition_tokens
    row = Adw.ActionRow(
        title=_("Token da API AudD"), subtitle=_("Armazenado no chaveiro do sistema")
    )
    entry = Gtk.PasswordEntry(
        placeholder_text=_("Configurado") if tokens.load() else _("Token"),
        show_peek_icon=True,
        valign=Gtk.Align.CENTER,
    )
    entry.set_size_request(260, -1)
    entry.connect("activate", lambda field: tokens.save(field.get_text()))
    focus = Gtk.EventControllerFocus()
    focus.connect("leave", lambda *_: tokens.save(entry.get_text()))
    entry.add_controller(focus)
    row.add_suffix(entry)
    row.add_suffix(_pill(_("Reconhecer agora"), window._recognize_music, suggested=True))
    return row


def cast_group(window) -> Adw.PreferencesGroup:
    group = Adw.PreferencesGroup(
        title=_("Transmitir para dispositivo"),
        description=_("Descobre Media Renderers UPnP/DLNA na rede local."),
    )
    cast = Adw.ActionRow(
        title=_("Dispositivo de reprodução"),
        subtitle=window.cast_device.name if window.cast_device else _("Este computador"),
    )
    if window.cast_renderer:
        cast.add_suffix(_pill(_("Desconectar"), window._disconnect_cast))
    cast.add_suffix(_pill(_("Procurar"), lambda: window._scan_cast_devices(cast)))
    group.add(cast)
    return group
