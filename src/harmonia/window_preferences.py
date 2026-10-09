from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk

from . import host
from .backup import BackupError, BackupManager
from .i18n import _, ngettext
from .preferences import Preferences
from .settings_page import build_settings_page
from .theming import get_theme
from .ui import set_css_class

LOGGER = logging.getLogger(__name__)
BUNDLED_ICON_THEME = "HarmoniaMaterial"
BUNDLED_ICONS_PATH = str(Path(__file__).with_name("icons"))
FALLBACK_ICON_THEMES = ("Adwaita",)
# elementary icons 8.x position some symbolic paths through <g transform>, which
# GTK 4.21+ ignores, so those icons render blank on the GNOME 50 runtime. The
# icons-compat tree holds the redrawn 9.x versions under elementary/<dir>/
# without an index.theme, so GTK merges it into the installed elementary theme
# and every theme inheriting from it (accent variants such as elementary-grape)
# while the system theme stays in charge. See tools/sync_elementary_icons.py.
ELEMENTARY_SHADOW_PATH = str(Path(__file__).with_name("icons-compat"))
ELEMENTARY_SHADOW_MIN_GTK = (4, 21)
ELEMENTARY_SHADOW_PROBE = "go-home-symbolic"


def shadow_resolves(path: str | None) -> bool:
    """Whether a looked-up icon file is not an unshadowed elementary icon."""
    if not path:
        return True
    path = host.slash_path(path)
    if path.startswith(host.slash_path(ELEMENTARY_SHADOW_PATH)):
        return True
    return "/elementary" not in path


def install_elementary_shadow(theme: Gtk.IconTheme, gtk_version: tuple[int, int]) -> bool:
    """Merge the redrawn elementary icons into the active icon theme.

    For directories present in several search paths GTK 4 keeps one file per
    icon; which path wins is an implementation detail, so the shadow is
    appended, checked with a probe icon and moved to the front if it lost.
    """
    if gtk_version < ELEMENTARY_SHADOW_MIN_GTK:
        return False
    others = [path for path in theme.get_search_path() if path != ELEMENTARY_SHADOW_PATH]
    theme.set_search_path([*others, ELEMENTARY_SHADOW_PATH])
    probe = theme.lookup_icon(
        ELEMENTARY_SHADOW_PROBE, None, 16, 1, Gtk.TextDirection.LTR, Gtk.IconLookupFlags(0)
    )
    resolved = probe.get_file().get_path() if probe.get_file() else None
    if not shadow_resolves(resolved):
        theme.set_search_path([ELEMENTARY_SHADOW_PATH, *others])
    return True


def add_bundled_icon_path(theme: Gtk.IconTheme) -> None:
    if BUNDLED_ICONS_PATH not in theme.get_search_path():
        theme.add_search_path(BUNDLED_ICONS_PATH)


def icon_theme_installed(theme: Gtk.IconTheme, name: str) -> bool:
    """Return whether GTK can load the named theme from its search path."""
    if not name:
        return False
    return any((Path(base) / name / "index.theme").is_file() for base in theme.get_search_path())


class WindowPreferencesMixin:
    def _validate_download_account(self) -> None:
        try:
            self.downloads.validate_account()
        except Exception:
            LOGGER.debug("Não foi possível validar a conta dos downloads", exc_info=True)

    def _periodic_download_validation(self) -> bool:
        if self.storage.load_cookie():
            threading.Thread(
                target=self._validate_download_account,
                daemon=True,
                name="download-account-periodic",
            ).start()
        return GLib.SOURCE_CONTINUE

    @staticmethod
    def _format_bytes(value: int) -> str:
        size = float(max(0, value))
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.1f} {unit}"
            size /= 1024
        return "0 B"

    def show_downloads(self) -> None:
        self.main_view = "downloads"
        self.back.set_visible(False)
        self._set_active_nav("downloads")
        self._render_downloads()

    def _apply_audio_preferences(self) -> None:
        if not hasattr(self, "player"):
            return
        self.player.set_crossfade(self.preferences.crossfade)
        self.player.apply_audio_settings(
            normalization=self.preferences.normalization,
            normalization_level=self.preferences.normalization_level,
            equalizer=self.preferences.equalizer,
            speed=self.preferences.speed,
            pitch=self.preferences.pitch,
            skip_silence=self.preferences.skip_silence,
            speed_pitch_linked=self.preferences.speed_pitch_linked,
        )

    def _preference_changed(self, name: str, value, *, audio: bool = False) -> None:
        setattr(self.preferences, name, value)
        self.preferences.save(self.storage)
        if audio:
            self._apply_audio_preferences()

    def _apply_appearance_preferences(self) -> None:
        application = self.get_application() if hasattr(self, "get_application") else None
        controller = getattr(application, "theme_controller", None)
        translucent = False
        if controller:
            theme_args = (
                self.preferences.theme,
                self.preferences.theme_variant,
                self.preferences.accent,
            )
            # The colour scheme comes first: the window material is tinted for it.
            controller.apply(*theme_args)
            translucent = self._apply_window_backdrop()
            controller.apply(*theme_args, translucent=translucent)
        blurred = self.preferences.background_blur
        set_css_class(self.root, "appearance-blur", blurred)
        self.ambient_background.set_opacity(0.30 if blurred else 0)
        self._apply_expanded_material(translucent)

        for style in Preferences.ICON_STYLES:
            self.root.remove_css_class(f"icons-{style}")
        if self.preferences.icon_style != "gtk":
            self.root.add_css_class(f"icons-{self.preferences.icon_style}")
        self._apply_icon_theme()

    def _apply_window_backdrop(self) -> bool:
        """Put the chosen material behind the windows; True if the theme may go translucent."""
        if not host.WINDOW_BACKDROPS:
            return False
        if getattr(self, "_window_backdrops", None) is None:
            from .gtk_backdrop import window_backdrops

            self._window_backdrops = window_backdrops()
            # The player bar's queue and lyrics popovers float over the window
            # like Fluent flyouts, so they get the material as well.
            for name in ("queue_popover", "lyrics_popover"):
                popover = getattr(self, name, None)
                if popover is not None:
                    self._window_backdrops.attach_popover(popover)
        supported = get_theme(self.preferences.theme).backdrop
        kind = self.preferences.backdrop if supported else "none"
        if getattr(self, "_backdrop_row", None) is not None:
            self._backdrop_row.set_sensitive(supported)
        if getattr(self, "_expanded_cover_row", None) is not None:
            self._expanded_cover_row.set_sensitive(kind != "none")
        if kind != "none" and not self.get_realized():
            # The window first applies its preferences before it has a native
            # window, so the material (and the translucent palette that goes
            # with it) can only be set once it is realized.
            if not getattr(self, "_backdrop_realize_handler", 0):
                self._backdrop_realize_handler = self.connect_after(
                    "realize", lambda *_: GLib.idle_add(self._reapply_appearance)
                )
            return False
        return self._window_backdrops.set_kind(kind, self)

    def _apply_expanded_material(self, translucent: bool) -> None:
        """Show the window material behind the expanded player instead of the cover.

        Only with a material on and Preferences > "Capa desfocada no player
        expandido" off. The expanded player covers the window, so it slides in
        opaque and turns transparent once revealed, when the pages underneath
        are hidden and only the material shows through.
        """
        surface = getattr(self, "expanded_surface", None)
        if not host.WINDOW_BACKDROPS or surface is None:
            return
        self._expanded_translucent = translucent
        material = translucent and not self.preferences.expanded_cover
        for widget in (
            self.expanded_backdrop_base,
            self.expanded_backdrop,
            self.expanded_backdrop_shade,
        ):
            widget.set_visible(not material)
        set_css_class(surface, "expanded-material", material)
        # The expanded player keeps its dark design: in light mode a dark veil
        # over the material keeps its white text readable.
        style = Adw.StyleManager.get_default()
        set_css_class(surface, "expanded-material-light", material and not style.get_dark())
        if not getattr(self, "_expanded_material_handlers", False):
            self._expanded_material_handlers = True
            for signal in ("notify::reveal-child", "notify::child-revealed"):
                self.expanded_revealer.connect(signal, lambda *_: self._update_expanded_reveal())
            style.connect(
                "notify::dark",
                lambda *_: self._apply_expanded_material(self._expanded_translucent),
            )
        self._update_expanded_reveal()

    def _update_expanded_reveal(self) -> None:
        surface = self.expanded_surface
        revealed = (
            surface.has_css_class("expanded-material")
            and self.expanded_revealer.get_reveal_child()
            and self.expanded_revealer.get_child_revealed()
        )
        if revealed:
            surface.add_css_class("expanded-revealed")
        else:
            # Back to opaque at once, before the player slides away.
            surface.remove_css_class("expanded-revealed")
        self.root.set_opacity(0 if revealed else 1)
        blurred = self.preferences.background_blur
        self.ambient_background.set_opacity(0 if revealed or not blurred else 0.30)

    def _reapply_appearance(self) -> bool:
        self._apply_appearance_preferences()
        return GLib.SOURCE_REMOVE

    def _apply_icon_theme(self) -> None:
        """Select the icon theme without pinning the system one.

        In "gtk" mode Harmonia follows the desktop's theme live. When that theme
        is not installed where GTK can see it (for example the elementary theme
        inside the GNOME Flatpak runtime), GTK would otherwise render
        "image-missing", so a theme that is actually present is used instead.
        GTK refreshes every GtkImage by itself when the theme changes.
        """
        display = Gdk.Display.get_default()
        if not display:
            return
        theme = Gtk.IconTheme.get_for_display(display)
        add_bundled_icon_path(theme)
        settings = Gtk.Settings.get_for_display(display)
        if not settings:
            return
        if not self._icon_settings_handler:
            self._icon_settings_handler = settings.connect(
                "notify::gtk-icon-theme-name", lambda *_: self._ensure_icon_theme_available()
            )
        bundled = Preferences.ICON_STYLES.get(self.preferences.icon_style)
        if bundled:
            settings.set_property("gtk-icon-theme-name", bundled)
            return
        if host.SYSTEM_ICON_THEME:
            settings.set_property("gtk-icon-theme-name", host.SYSTEM_ICON_THEME)
            return
        settings.reset_property("gtk-icon-theme-name")
        self._ensure_icon_theme_available()

    def _ensure_icon_theme_available(self) -> None:
        display = Gdk.Display.get_default()
        settings = Gtk.Settings.get_for_display(display) if display else None
        if not settings or self.preferences.icon_style != "gtk":
            return
        theme = Gtk.IconTheme.get_for_display(display)
        current = settings.get_property("gtk-icon-theme-name") or ""
        if icon_theme_installed(theme, current):
            install_elementary_shadow(theme, (Gtk.get_major_version(), Gtk.get_minor_version()))
            return
        fallback = next(
            (name for name in FALLBACK_ICON_THEMES if icon_theme_installed(theme, name)),
            BUNDLED_ICON_THEME,
        )
        LOGGER.info("Tema de ícones %r indisponível; usando %r", current, fallback)
        settings.set_property("gtk-icon-theme-name", fallback)

    def _appearance_changed(self, name: str, value) -> None:
        self._preference_changed(name, value)
        self._apply_appearance_preferences()

    def _cache_size(self) -> int:
        return sum(
            path.stat().st_size for path in self.storage.artwork_dir.iterdir() if path.is_file()
        )

    def _clear_artwork_cache(self, row: Adw.ActionRow) -> None:
        removed = self.storage.clear_cache()
        row.set_subtitle(_("0 B armazenados"))
        self.toast_overlay.add_toast(
            Adw.Toast(
                title=_("Cache limpo · {size} removidos").format(size=self._format_bytes(removed))
            )
        )

    def _set_sleep_timer(self, minutes: int) -> None:
        if self._sleep_timer_source:
            GLib.source_remove(self._sleep_timer_source)
            self._sleep_timer_source = 0
        self._sleep_timer_deadline = 0.0
        if minutes:
            self._sleep_timer_deadline = time.time() + minutes * 60
            self._sleep_timer_source = GLib.timeout_add_seconds(
                minutes * 60, self._sleep_timer_elapsed
            )
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=ngettext(
                        "Temporizador definido para {count} minuto",
                        "Temporizador definido para {count} minutos",
                        minutes,
                    ).format(count=minutes)
                )
            )

    def _sleep_timer_elapsed(self) -> bool:
        self._sleep_timer_source = 0
        self._sleep_timer_deadline = 0.0
        self._pause()
        self.toast_overlay.add_toast(Adw.Toast(title=_("Reprodução pausada pelo temporizador")))
        return GLib.SOURCE_REMOVE

    def _validate_settings_account(self, row: Adw.ActionRow) -> None:
        row.set_subtitle(_("Validando sessão…"))

        def worker() -> None:
            try:
                valid = self.youtube.validate_account()
                error = None
            except Exception as exc:
                valid, error = False, str(exc)
            GLib.idle_add(self._account_validation_done, row, valid, error)

        threading.Thread(target=worker, daemon=True, name="settings-account-validation").start()

    def _account_validation_done(self, row: Adw.ActionRow, valid: bool, error: str | None) -> bool:
        row.set_subtitle(_("Conectada e válida") if valid else _("Sessão inválida ou expirada"))
        self.toast_overlay.add_toast(
            Adw.Toast(
                title=_("Conta validada")
                if valid
                else _("Não foi possível validar a conta{detail}").format(
                    detail=f": {error}" if error else ""
                ),
                timeout=5,
            )
        )
        return GLib.SOURCE_REMOVE

    def _disconnect_from_settings(self) -> None:
        self.youtube.disconnect()
        self._clear_account_avatar()
        self.toast_overlay.add_toast(Adw.Toast(title=_("Conta desconectada")))
        self.show_settings()

    def _export_backup_dialog(self) -> None:
        dialog = Gtk.FileDialog(
            title=_("Exportar backup"),
            initial_name=f"harmonia-backup-{time.strftime('%Y-%m-%d')}.harmonia-backup",
        )

        def selected(file_dialog: Gtk.FileDialog, result) -> None:
            try:
                file = file_dialog.save_finish(result)
                path = file.get_path()
                if path:
                    BackupManager(self.storage).export_to(Path(path))
                    self.toast_overlay.add_toast(Adw.Toast(title=_("Backup exportado")))
            except (GLib.Error, OSError, BackupError) as exc:
                if not isinstance(exc, GLib.Error):
                    self.toast_overlay.add_toast(
                        Adw.Toast(
                            title=_("Não foi possível exportar o backup: {error}").format(
                                error=exc
                            ),
                            timeout=6,
                        )
                    )

        dialog.save(self, None, selected)

    def _restore_backup_dialog(self) -> None:
        dialog = Gtk.FileDialog(title=_("Restaurar backup"))

        def selected(file_dialog: Gtk.FileDialog, result) -> None:
            try:
                file = file_dialog.open_finish(result)
                path = file.get_path()
                if path:
                    self._confirm_restore_backup(Path(path))
            except GLib.Error:
                return

        dialog.open(self, None, selected)

    def _confirm_restore_backup(self, path: Path) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Restaurar este backup?"),
            body=_(
                "A biblioteca, o histórico e as preferências locais atuais serão substituídos. "
                "A sessão da conta e os arquivos de áudio não serão alterados."
            ),
        )
        dialog.add_response("cancel", _("Cancelar"))
        dialog.add_response("restore", _("Restaurar"))
        dialog.set_response_appearance("restore", Adw.ResponseAppearance.DESTRUCTIVE)

        def response(_dialog, name: str) -> None:
            if name != "restore":
                return
            try:
                BackupManager(self.storage).restore_from(path)
                self.preferences = Preferences.load(self.storage)
                self.sections = self.storage.load_library()
                self.home_sections = self.storage.load_home()
                self.explore_data = self.storage.load_explore()
                self._apply_audio_preferences()
                self._apply_appearance_preferences()
                self._configure_discord_presence()
                self.toast_overlay.add_toast(Adw.Toast(title=_("Backup restaurado")))
                self.show_settings()
            except (OSError, BackupError) as exc:
                self.toast_overlay.add_toast(
                    Adw.Toast(
                        title=_("Não foi possível restaurar o backup: {error}").format(error=exc),
                        timeout=6,
                    )
                )

        dialog.connect("response", response)
        dialog.present(self)

    def show_settings(self) -> None:
        self.main_view = "settings"
        self.back.set_visible(False)
        self._set_active_nav("settings")
        old = self.stack.get_child_by_name("settings")
        if old:
            self.stack.remove(old)

        page = build_settings_page(self)

        self.stack.add_named(page, "settings")
        self.stack.set_visible_child_name("settings")
