"""New versions for the GTK window: the banner over the pages and the state
Preferences > Sobre o Harmonia shows (updates.py does the work).

Once a day, when Preferences allow it, the newest stable release is looked
up; a newer one is downloaded at once, and installed only from the banner's
or Preferences' button.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gtk

from . import __version__, host, updates
from .i18n import _
from .ui import deliver_to_main

LOGGER = logging.getLogger(__name__)
CHECKED_SETTING = "updates_checked_at"
FIRST_CHECK_DELAY = 10  # seconds after start, out of the way of the first sync
# Methods whose update Harmonia installs itself.
SELF_UPDATING = ("windows", "source", "source-system", "deb", "rpm")


class UpdateController:
    """The update's state: "idle", "checking", "current", "downloading",
    "ready", "installing", "installed", "manual" (only a page or a command
    to offer) or "failed"."""

    def __init__(self, window) -> None:
        self.window = window
        self.method = updates.install_method()
        self.state = "idle"
        self.release: updates.Release | None = None
        self.file = None
        self.error = ""
        self._listeners: list[Callable[[], None]] = []
        self.banner = Adw.Banner(revealed=False)
        self.banner.connect("button-clicked", lambda *_: self.act())
        window.root.insert_child_after(self.banner, window.header)

    def start(self) -> None:
        GLib.timeout_add_seconds(FIRST_CHECK_DELAY, self._scheduled_check)
        # A window left open for days still hears of new versions.
        GLib.timeout_add_seconds(updates.CHECK_INTERVAL, self._scheduled_check)

    def listen(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    def unlisten(self, callback: Callable[[], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _scheduled_check(self) -> bool:
        storage = self.window.storage
        try:
            last = float(storage.get_setting(CHECKED_SETTING, "0"))
        except ValueError:
            last = 0.0
        due = time.time() - last >= updates.CHECK_INTERVAL - 60
        if self.window.preferences.check_updates and due and self.state in ("idle", "current"):
            self.check()
        return GLib.SOURCE_CONTINUE

    # --- Finding and downloading ------------------------------------------

    def check(self) -> None:
        if self.state in ("checking", "downloading", "installing"):
            return
        self._set("checking")
        threading.Thread(target=self._find, daemon=True, name="update-check").start()

    def _find(self) -> None:
        try:
            release = updates.latest_release()
        except Exception as exc:
            LOGGER.info("Não foi possível procurar atualizações: %s", exc)
            deliver_to_main(self._failed, _("Não foi possível falar com o GitHub"))
            return
        deliver_to_main(self._found, release)

    def _found(self, release: updates.Release) -> bool:
        self.window.storage.set_setting(CHECKED_SETTING, str(int(time.time())))
        self.release = release
        if not updates.is_newer(release.version):
            self._set("current")
            return GLib.SOURCE_REMOVE
        name = updates.asset_name(release, self.method)
        if self.method not in SELF_UPDATING or name is None:
            self._set("manual")
            return GLib.SOURCE_REMOVE
        self._set("downloading")
        folder = host.cache_dir() / "updates"
        threading.Thread(
            target=self._download, args=(release, name, folder), daemon=True, name="update-download"
        ).start()
        return GLib.SOURCE_REMOVE

    def _download(self, release, name, folder) -> None:
        try:
            file = updates.download(release, name, folder)
        except Exception as exc:
            LOGGER.warning("Não foi possível baixar a atualização: %s", exc)
            deliver_to_main(self._failed, _("Não foi possível baixar a versão {version}").format(
                version=release.version))  # fmt: skip
            return
        deliver_to_main(self._downloaded, file)

    def _downloaded(self, file) -> bool:
        self.file = file
        self._set("ready")
        return GLib.SOURCE_REMOVE

    def _failed(self, message: str) -> bool:
        self.error = message
        self._set("failed")
        return GLib.SOURCE_REMOVE

    # --- Installing --------------------------------------------------------

    def act(self) -> None:
        """The banner's and Preferences' button: what the state offers."""
        if self.state == "ready" or (self.state == "failed" and self.file is not None):
            self.install()
        elif self.state == "installed":
            self.restart()
        elif self.state == "manual":
            self.open_page()
        else:
            self.check()

    def install(self) -> None:
        if self.file is None or self.release is None:
            return
        command = updates.install_command(self.method, self.file, self.release.version)
        if self.method == "windows":
            # The installer closes Harmonia and starts it again when it is done.
            updates.start_detached(command)
            self.window.get_application().quit()
            return
        self._set("installing")
        threading.Thread(
            target=self._install, args=(command,), daemon=True, name="update-install"
        ).start()

    def _install(self, command: list[str]) -> None:
        try:
            result = updates.run_install(command)
        except OSError as exc:
            deliver_to_main(self._failed, str(exc))
            return
        if result.returncode != 0:
            lines = (result.stderr or result.stdout).strip().splitlines()
            LOGGER.warning("A atualização falhou:\n%s\n%s", result.stdout, result.stderr)
            reason = lines[-1] if lines else _("o instalador terminou com erro")
            deliver_to_main(self._failed, _("A atualização falhou: {reason}").format(reason=reason))
            return
        deliver_to_main(self._set, "installed")

    def restart(self) -> None:
        updates.start_detached(updates.restart_command())
        self.window.get_application().quit()

    def open_page(self) -> None:
        page = self.release.page if self.release else updates.RELEASES_URL
        Gtk.UriLauncher(uri=page).launch(self.window, None, None, None)

    # --- What the window shows ---------------------------------------------

    def _set(self, state: str) -> bool:
        self.state = state
        self._show_banner()
        for listener in list(self._listeners):
            listener()
        return GLib.SOURCE_REMOVE

    def _show_banner(self) -> None:
        version = self.release.version if self.release else ""
        offers = {
            "ready": (
                _("O Harmonia {version} está pronto para instalar"),
                _("Instalar e reiniciar"),
            ),
            "installed": (_("O Harmonia {version} foi instalado"), _("Reiniciar")),
            "manual": (_("O Harmonia {version} está disponível"), _("Ver a versão")),
            "failed": (_("Não foi possível atualizar o Harmonia"), _("Tentar de novo")),
        }
        offer = offers.get(self.state)
        if self.state == "failed" and self.release is None:
            offer = None  # GitHub out of reach: Preferences say so, the banner stays out
        if offer is not None:
            self.banner.set_title(offer[0].format(version=version))
            self.banner.set_button_label(offer[1])
        self.banner.set_revealed(offer is not None)

    def status(self) -> str:
        """One line for Preferences."""
        version = self.release.version if self.release else ""
        if self.state == "manual" and self.method == "flatpak" and self.release:
            name = updates.asset_name(self.release, "flatpak") or "Harmonia.flatpak"
            return _("Versão {version} disponível: baixe {name} na página e rode {command}").format(
                version=version, name=name, command=updates.flatpak_command(name)
            )
        return {
            "idle": _("Você usa a versão {current}").format(current=__version__),
            "checking": _("Procurando atualizações…"),
            "current": _("Você tem a versão mais recente"),
            "downloading": _("Baixando a versão {version}…").format(version=version),
            "ready": _("A versão {version} está pronta para instalar").format(version=version),
            "installing": _("Instalando a versão {version}…").format(version=version),
            "installed": _("A versão {version} foi instalada; reinicie o Harmonia").format(
                version=version
            ),
            "manual": _("A versão {version} está disponível na página do GitHub").format(
                version=version
            ),
            "failed": self.error,
        }[self.state]

    def button_label(self) -> str:
        if self.state == "failed" and self.file is not None:
            return _("Tentar de novo")
        return {
            "ready": _("Instalar e reiniciar"),
            "installed": _("Reiniciar"),
            "manual": _("Ver a versão"),
        }.get(self.state, _("Procurar agora"))

    def busy(self) -> bool:
        return self.state in ("checking", "downloading", "installing")
