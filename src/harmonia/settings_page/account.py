"""Preferences > Conta: the YouTube Music session."""

from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import host  # noqa: E402
from ..i18n import _  # noqa: E402
from ..ui import style_icon_button  # noqa: E402
from .rows import pill_button  # noqa: E402


def account_group(window) -> Adw.PreferencesGroup:
    group = Adw.PreferencesGroup(
        title=_("Conta"),
        description=(
            _("Sessão protegida pelo Gerenciador de Credenciais do Windows.")
            if host.IS_WINDOWS
            else _("Sessão protegida pelo chaveiro Secret Service do sistema.")
        ),
    )
    connected = bool(window.storage.load_cookie())
    account = Adw.ActionRow(
        title=_("YouTube Music"),
        subtitle=_("Conectada") if connected else _("Não conectada"),
    )
    account.add_prefix(Gtk.Image.new_from_icon_name("avatar-default-symbolic"))
    if connected:
        account.add_suffix(
            pill_button(_("Validar"), lambda: window._validate_settings_account(account))
        )
        disconnect = Gtk.Button(
            icon_name="system-log-out-symbolic",
            tooltip_text=_("Desconectar"),
            valign=Gtk.Align.CENTER,
        )
        style_icon_button(disconnect, "sm")
        disconnect.add_css_class("destructive-action")
        disconnect.connect("clicked", lambda *_: window._disconnect_from_settings())
        account.add_suffix(disconnect)
    else:
        account.add_suffix(pill_button(_("Conectar"), window.login_dialog, "suggested-action"))
    group.add(account)
    return group
