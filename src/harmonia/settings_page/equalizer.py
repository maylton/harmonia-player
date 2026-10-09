"""Preferences > Áudio: the equalizer, with presets and imported AutoEQ profiles."""

from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from ..autoeq import parse_profile, profile_name  # noqa: E402
from ..equalizer import profile_key, profile_of  # noqa: E402
from ..i18n import _  # noqa: E402
from .rows import pill_button  # noqa: E402


def presets() -> list[tuple[str, str]]:
    return [
        (_("Plano"), "flat"),
        (_("Graves"), "bass"),
        (_("Voz"), "vocal"),
        (_("Agudos"), "treble"),
    ]


class EqualizerRows:
    """The equalizer choice and the AutoEQ profile actions; ``rows`` go in the group."""

    def __init__(self, window) -> None:
        self.window = window
        self.keys: list[str] = []
        self._updating = False
        self.choice = Adw.ComboRow(title=_("Equalizador"))
        self.choice.connect("notify::selected", lambda *_: self._selected())
        self.profiles = Adw.ActionRow(
            title=_("Perfis do AutoEQ"),
            subtitle=_("Correção para o seu fone: importe o ParametricEQ ou o GraphicEQ dele"),
        )
        self.profiles.add_suffix(pill_button(_("Importar…"), self._choose_file))
        self.remove = pill_button(_("Remover"), self._remove_current)
        self.profiles.add_suffix(self.remove)
        self.rows = (self.choice, self.profiles)
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the choices from the stored profiles and select the current one."""
        names = self.window.storage.eq_profiles()
        choices = [*presets(), *((name, profile_key(name)) for name in names)]
        self.keys = [key for _label, key in choices]
        current = self.window.preferences.equalizer
        self._updating = True
        self.choice.set_model(Gtk.StringList.new([label for label, _key in choices]))
        self.choice.set_selected(self.keys.index(current) if current in self.keys else 0)
        self._updating = False
        self.remove.set_sensitive(profile_of(current) is not None)

    def _selected(self) -> None:
        index = self.choice.get_selected()
        if self._updating or not 0 <= index < len(self.keys):
            return
        self.window._preference_changed("equalizer", self.keys[index], audio=True)
        self.remove.set_sensitive(profile_of(self.keys[index]) is not None)

    def _choose_file(self) -> None:
        text_files = Gtk.FileFilter(name=_("Perfis do AutoEQ (.txt)"))
        text_files.add_pattern("*.txt")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(text_files)
        dialog = Gtk.FileDialog(title=_("Importar perfil do AutoEQ"), filters=filters)
        dialog.open(self.window, None, self._file_chosen)

    def _file_chosen(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return  # cancelled
        try:
            _ok, contents, _etag = file.load_contents(None)
            gains = parse_profile(contents.decode("utf-8", "replace"))
        except (GLib.Error, ValueError):
            self._toast(_("Este arquivo não é um perfil do AutoEQ"))
            return
        name = profile_name(file.get_basename() or "")
        self.window.storage.save_eq_profile(name, gains)
        self.window._preference_changed("equalizer", profile_key(name), audio=True)
        self.refresh()
        self._toast(_("Perfil “{name}” importado").format(name=name))

    def _remove_current(self) -> None:
        name = profile_of(self.window.preferences.equalizer)
        if name is None:
            return
        self.window.storage.delete_eq_profile(name)
        self.window._preference_changed("equalizer", "flat", audio=True)
        self.refresh()
        self._toast(_("Perfil “{name}” removido").format(name=name))

    def _toast(self, title: str) -> None:
        self.window.toast_overlay.add_toast(Adw.Toast(title=title, timeout=3))
