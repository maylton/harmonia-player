"""Preferences > Conta: which channel of the login Harmonia acts as (brand accounts)."""

from __future__ import annotations

import logging
import threading

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..accounts import YouTubeIdentity  # noqa: E402
from ..i18n import _  # noqa: E402

LOGGER = logging.getLogger(__name__)


def identity_row(window) -> Adw.ComboRow:
    """Hidden until the login turns out to have more than one channel."""
    row = Adw.ComboRow(
        title=_("Canal do YouTube Music"),
        subtitle=_("A biblioteca, o histórico e as curtidas são os do canal escolhido"),
        visible=False,
    )

    def loaded(identities: list[YouTubeIdentity]) -> bool:
        if len(identities) < 2:
            return GLib.SOURCE_REMOVE
        labels = [
            f"{identity.name} ({identity.handle})" if identity.handle else identity.name
            for identity in identities
        ]
        row.set_model(Gtk.StringList.new(labels))
        current = next((i for i, identity in enumerate(identities) if identity.selected), 0)
        row.set_selected(current)
        row.connect("notify::selected", lambda *_: chosen(identities[row.get_selected()]))
        row.set_visible(True)
        return GLib.SOURCE_REMOVE

    def chosen(identity: YouTubeIdentity) -> None:
        window.youtube.set_identity(identity)
        window.toast_overlay.add_toast(
            Adw.Toast(title=_("Usando o canal {name}. Sincronizando…").format(name=identity.name))
        )
        window._refresh_account_avatar()
        window.sync()
        window.sync_home()
        window.sync_explore()

    def worker() -> None:
        try:
            identities = window.youtube.identities()
        except Exception:
            LOGGER.debug("Não foi possível listar os canais da conta", exc_info=True)
            return
        GLib.idle_add(loaded, identities)

    if window.storage.load_cookie():
        threading.Thread(target=worker, daemon=True, name="account-identities").start()
    return row
