from __future__ import annotations

import importlib
import logging
import threading
import urllib.request
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from . import host
from .i18n import _, ngettext
from .models import (
    ExploreData,
)

LOGGER = logging.getLogger(__name__)


class WindowAccountMixin:
    def login_dialog(self) -> None:
        if not host.INTEGRATED_LOGIN:
            self.manual_login_dialog()
            return
        try:
            login = importlib.import_module(f".{host.LOGIN_MODULE}", __package__)
            login.LoginWindow(
                self,
                self.storage.web_data_dir,
                self._integrated_login_done,
                self.manual_login_dialog,
            ).present()
        except (ImportError, ValueError, OSError) as exc:
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=_("Navegador integrado indisponível: {error}").format(error=exc),
                    timeout=5,
                )
            )
            self.manual_login_dialog()

    def _integrated_login_done(self, cookie: str) -> None:
        self.youtube.save_session(cookie)
        self._load_account_avatar("")
        self._refresh_account_avatar()
        self.sections = {}
        self.home_sections = []
        self.explore_data = ExploreData([], [], [])
        self._render()
        self.toast_overlay.add_toast(Adw.Toast(title=_("Conta conectada. Sincronizando…")))
        self.sync()
        self.sync_home()
        self.sync_explore()

    def manual_login_dialog(self) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Conectar ao YouTube Music"),
            body=_(
                "No navegador, abra music.youtube.com já conectado, copie o cabeçalho Cookie de uma requisição nas ferramentas de desenvolvedor e cole abaixo. A senha nunca é solicitada."
            ),
        )
        entry = Gtk.PasswordEntry(
            show_peek_icon=True, placeholder_text=_("SAPISID=…; __Secure-3PAPISID=…")
        )
        entry.set_text(self.storage.load_cookie())
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", _("Cancelar"))
        if self.storage.load_cookie():
            dialog.add_response("disconnect", _("Desconectar"))
            dialog.set_response_appearance("disconnect", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.add_response("connect", _("Conectar"))
        dialog.set_response_appearance("connect", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("connect")

        def response(_dialog, name):
            if name == "disconnect":
                self.youtube.disconnect()
                self._clear_account_avatar()
                self.sections = {}
                self.home_sections = []
                self.explore_data = ExploreData([], [], [])
                self._render()
            elif name == "connect":
                value = entry.get_text().strip()
                if not self.youtube.connect(value):
                    self.toast_overlay.add_toast(
                        Adw.Toast(title=_("Cookie inválido: SAPISID não encontrado"))
                    )
                    return
                self._load_account_avatar("")
                self._refresh_account_avatar()
                self._render()
                self.sync()
                self.sync_home()
                self.sync_explore()

        dialog.connect("response", response)
        dialog.present(self)

    def sync(self) -> None:
        cookie = self.storage.load_cookie()
        if not cookie:
            self.login_dialog()
            return
        self.toast_overlay.add_toast(Adw.Toast(title=_("Sincronizando biblioteca…"), timeout=2))

        def worker():
            try:
                sections = self.youtube.sync_library()
                GLib.idle_add(self._sync_done, sections, None)
            except Exception as exc:
                GLib.idle_add(self._sync_done, None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def sync_home(self) -> None:
        cookie = self.storage.load_cookie()
        if not cookie:
            return

        def worker():
            try:
                sections = self.youtube.sync_home()
                GLib.idle_add(self._home_sync_done, sections, None)
            except Exception as exc:
                GLib.idle_add(self._home_sync_done, None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def sync_explore(self) -> None:
        cookie = self.storage.load_cookie()
        if not cookie:
            return

        def worker():
            try:
                data = self.youtube.sync_explore()
                GLib.idle_add(self._explore_sync_done, data, None)
            except Exception as exc:
                GLib.idle_add(self._explore_sync_done, None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _home_sync_done(self, sections, error):
        if error:
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=_("Não foi possível atualizar o início: {error}").format(error=error),
                    timeout=5,
                )
            )
            return False
        self.home_sections = sections
        if self.main_view == "home" and not self.back.get_visible():
            self._render_home()
            self.stack.set_visible_child_name("home")
        return False

    def _explore_sync_done(self, data, error):
        if error:
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=_("Não foi possível atualizar o Explorar: {error}").format(error=error),
                    timeout=5,
                )
            )
            return False
        self.explore_data = data
        if self.main_view == "explore" and not self.back.get_visible():
            self.show_explore()
        return False

    def _sync_done(self, sections, error):
        if error:
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=_("Não foi possível sincronizar: {error}").format(error=error), timeout=6
                )
            )
            return False
        self.sections = sections
        self._refresh_current_like_from_library()
        self._render()
        if self.main_view == "home" and not self.back.get_visible():
            self._render_home()
            self.stack.set_visible_child_name("home")
        elif self.main_view == "explore" and not self.back.get_visible():
            self.show_explore()
        total = sum(map(len, sections.values()))
        self.toast_overlay.add_toast(
            Adw.Toast(
                title=ngettext(
                    "Biblioteca atualizada · {count} item",
                    "Biblioteca atualizada · {count} itens",
                    total,
                ).format(count=total)
            )
        )
        return False

    def _show_account_avatar_file(self, path: Path, request_id: int) -> bool:
        if request_id != self._account_avatar_request or not path.exists():
            return GLib.SOURCE_REMOVE
        self.account_avatar_picture.set_filename(str(path))
        self.account_avatar_picture.set_opacity(1)
        self.account_avatar_fallback.set_opacity(0)
        return GLib.SOURCE_REMOVE

    def _load_account_avatar(self, url: str) -> None:
        self._account_avatar_request += 1
        request_id = self._account_avatar_request
        if not url:
            self.account_avatar_picture.set_opacity(0)
            self.account_avatar_picture.set_filename(None)
            self.account_avatar_fallback.set_opacity(1)
            self.account_button.set_tooltip_text(_("Conta"))
            return
        target = self.storage.artwork_path(url)
        if target.exists():
            self._show_account_avatar_file(target, request_id)
            return

        def worker() -> None:
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(request, timeout=15) as response:
                    data = response.read(2 * 1024 * 1024)
                target.write_bytes(data)
                GLib.idle_add(self._show_account_avatar_file, target, request_id)
            except Exception:
                LOGGER.debug("Não foi possível baixar o avatar da conta", exc_info=True)

        threading.Thread(target=worker, daemon=True, name="account-avatar-image").start()

    def _refresh_account_avatar(self) -> None:
        if not self.storage.load_cookie():
            self._clear_account_avatar()
            return

        def worker() -> None:
            try:
                profile = self.youtube.account_profile()
                GLib.idle_add(self._account_profile_loaded, profile)
            except Exception:
                LOGGER.debug(
                    "Não foi possível atualizar o perfil; mantendo o avatar em cache",
                    exc_info=True,
                )

        threading.Thread(target=worker, daemon=True, name="account-profile").start()

    def _account_profile_loaded(self, profile) -> bool:
        avatar = profile.thumbnail or ""
        self.storage.set_setting("account_avatar_url", avatar)
        self.account_button.set_tooltip_text(_("Conta — {name}").format(name=profile.name))
        self._load_account_avatar(avatar)
        return GLib.SOURCE_REMOVE

    def _clear_account_avatar(self) -> None:
        self.storage.set_setting("account_avatar_url", "")
        self._load_account_avatar("")
