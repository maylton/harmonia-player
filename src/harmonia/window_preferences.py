from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk

from .backup import BackupError, BackupManager
from .i18n import _, ngettext
from .preferences import Preferences
from .ui import (
    style_icon_button,
)

LOGGER = logging.getLogger(__name__)


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
        self.player.apply_audio_settings(
            normalization=self.preferences.normalization,
            equalizer=self.preferences.equalizer,
            speed=self.preferences.speed,
            pitch=self.preferences.pitch,
            skip_silence=self.preferences.skip_silence,
        )

    def _preference_changed(self, name: str, value, *, audio: bool = False) -> None:
        setattr(self.preferences, name, value)
        self.preferences.save(self.storage)
        if audio:
            self._apply_audio_preferences()

    def _apply_appearance_preferences(self) -> None:
        blurred = self.preferences.background_blur
        if blurred:
            self.root.add_css_class("appearance-blur")
        else:
            self.root.remove_css_class("appearance-blur")
        self.ambient_background.set_opacity(0.30 if blurred else 0)

        self.root.remove_css_class("icons-material")
        if self.preferences.icon_style != "gtk":
            self.root.add_css_class(f"icons-{self.preferences.icon_style}")
        display = Gdk.Display.get_default()
        if display:
            theme = Gtk.IconTheme.get_for_display(display)
            icons_path = str(Path(__file__).with_name("icons"))
            if icons_path not in theme.get_search_path():
                theme.add_search_path(icons_path)
            settings = Gtk.Settings.get_for_display(display)
            if settings:
                selected = {
                    "material": "HarmoniaMaterial",
                }.get(self.preferences.icon_style, self._system_icon_theme_name)
                settings.set_property("gtk-icon-theme-name", selected)
        self._refresh_custom_icons()

    def _icon_name_changed(self, image: Gtk.Image, _pspec) -> None:
        if self._icon_update_guard:
            return
        name = image.get_icon_name()
        if name:
            self._icon_sources[image] = name
            GLib.idle_add(self._apply_custom_icon, image)

    def _apply_custom_icon(self, image: Gtk.Image) -> bool:
        name = image.get_icon_name()
        if name:
            self._icon_sources[image] = name
        base_name = self._icon_sources.get(image)
        if not base_name:
            return GLib.SOURCE_REMOVE
        self._icon_update_guard = True
        try:
            # Keep the semantic icon name on GtkImage. The process-wide icon
            # theme resolves the selected pack and GTK can then recolor every
            # symbolic icon from the widget's current foreground/accent color.
            image.set_from_icon_name(base_name)
        finally:
            self._icon_update_guard = False
        return GLib.SOURCE_REMOVE

    def _refresh_custom_icons(self) -> bool:
        pending = [self.root]
        while pending:
            widget = pending.pop()
            if isinstance(widget, Gtk.Image):
                if widget not in self._icon_sources:
                    widget.connect("notify::icon-name", self._icon_name_changed)
                self._apply_custom_icon(widget)
            child = widget.get_first_child()
            while child:
                pending.append(child)
                child = child.get_next_sibling()
        return GLib.SOURCE_REMOVE

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

        page = Adw.PreferencesPage(title=_("Preferências"))
        page.add_css_class("app-preferences")

        account_group = Adw.PreferencesGroup(
            title=_("Conta"),
            description=_("Sessão protegida pelo chaveiro Secret Service do sistema."),
        )
        account = Adw.ActionRow(
            title=_("YouTube Music"),
            subtitle=_("Conectada") if self.storage.load_cookie() else _("Não conectada"),
        )
        account.add_prefix(Gtk.Image.new_from_icon_name("avatar-default-symbolic"))
        if self.storage.load_cookie():
            validate = Gtk.Button(label=_("Validar"), valign=Gtk.Align.CENTER)
            validate.add_css_class("pill")
            validate.connect("clicked", lambda *_: self._validate_settings_account(account))
            account.add_suffix(validate)
            disconnect = Gtk.Button(
                icon_name="system-log-out-symbolic",
                tooltip_text=_("Desconectar"),
                valign=Gtk.Align.CENTER,
            )
            style_icon_button(disconnect, "sm")
            disconnect.add_css_class("destructive-action")
            disconnect.connect("clicked", lambda *_: self._disconnect_from_settings())
            account.add_suffix(disconnect)
        else:
            connect = Gtk.Button(label=_("Conectar"), valign=Gtk.Align.CENTER)
            connect.add_css_class("pill")
            connect.add_css_class("suggested-action")
            connect.connect("clicked", lambda *_: self.login_dialog())
            account.add_suffix(connect)
        account_group.add(account)
        page.add(account_group)

        streaming = Adw.PreferencesGroup(
            title=_("Streaming"),
            description=_("Estas opções são aplicadas à próxima requisição ao YouTube Music."),
        )

        def combo(
            title: str, values: list[tuple[str, str]], current: str, callback
        ) -> Adw.ComboRow:
            row = Adw.ComboRow(
                title=title, model=Gtk.StringList.new([label for label, _ in values])
            )
            keys = [key for _, key in values]
            row.set_selected(keys.index(current) if current in keys else 0)
            row.connect(
                "notify::selected", lambda widget, _pspec: callback(keys[widget.get_selected()])
            )
            return row

        appearance = Adw.PreferencesGroup(
            title=_("Aparência"),
            description=_("Personalize o ambiente visual sem alterar o conteúdo."),
        )
        blur = Adw.SwitchRow(
            title=_("Fundo ambiente desfocado"),
            subtitle=_("Usa as cores da capa atual atrás da interface"),
        )
        blur.set_active(self.preferences.background_blur)
        blur.connect(
            "notify::active",
            lambda row, _pspec: self._appearance_changed("background_blur", row.get_active()),
        )
        appearance.add(blur)
        appearance.add(
            combo(
                _("Estilo dos ícones"),
                [
                    (_("GTK — padrão do sistema"), "gtk"),
                    (_("Material Expressive"), "material"),
                ],
                self.preferences.icon_style,
                lambda value: self._appearance_changed("icon_style", value),
            )
        )
        page.add(appearance)

        streaming.add(
            combo(
                _("Qualidade do áudio"),
                [(_("Alta"), "high"), (_("Média"), "medium"), (_("Econômica"), "low")],
                self.preferences.quality,
                lambda value: self._preference_changed("quality", value),
            )
        )
        streaming.add(
            combo(
                _("Idioma"),
                [
                    (_("Português (Brasil)"), "pt-BR"),
                    (_("English"), "en-US"),
                    (_("Español"), "es-ES"),
                    ("日本語", "ja-JP"),
                ],
                self.preferences.language,
                lambda value: self._preference_changed("language", value),
            )
        )
        streaming.add(
            combo(
                _("Região"),
                [
                    (_("Brasil"), "BR"),
                    (_("Estados Unidos"), "US"),
                    (_("Portugal"), "PT"),
                    (_("Japão"), "JP"),
                ],
                self.preferences.region,
                lambda value: self._preference_changed("region", value),
            )
        )
        proxy = Adw.ActionRow(
            title=_("Proxy HTTP(S)"), subtitle=_("Opcional · exemplo: http://127.0.0.1:8080")
        )
        proxy_entry = Gtk.Entry(
            text=self.preferences.proxy, placeholder_text=_("Sem proxy"), valign=Gtk.Align.CENTER
        )
        proxy_entry.set_size_request(260, -1)
        proxy_entry.connect(
            "changed", lambda entry: self._preference_changed("proxy", entry.get_text().strip())
        )
        proxy.add_suffix(proxy_entry)
        streaming.add(proxy)
        cache = Adw.ActionRow(
            title=_("Cache de capas"),
            subtitle=_("{size} armazenados").format(size=self._format_bytes(self._cache_size())),
        )
        clear_cache = Gtk.Button(label=_("Limpar"), valign=Gtk.Align.CENTER)
        clear_cache.add_css_class("pill")
        clear_cache.connect("clicked", lambda *_: self._clear_artwork_cache(cache))
        cache.add_suffix(clear_cache)
        streaming.add(cache)
        page.add(streaming)

        data = Adw.PreferencesGroup(
            title=_("Dados e backup"),
            description=_(
                "Salva biblioteca, histórico e preferências sem incluir credenciais ou áudio."
            ),
        )
        backup = Adw.ActionRow(
            title=_("Backup portátil"),
            subtitle=_("Compatível com outras instalações do Harmonia"),
        )
        export = Gtk.Button(label=_("Exportar"), valign=Gtk.Align.CENTER)
        export.add_css_class("pill")
        export.connect("clicked", lambda *_: self._export_backup_dialog())
        backup.add_suffix(export)
        restore = Gtk.Button(label=_("Restaurar"), valign=Gtk.Align.CENTER)
        restore.add_css_class("pill")
        restore.connect("clicked", lambda *_: self._restore_backup_dialog())
        backup.add_suffix(restore)
        data.add(backup)
        page.add(data)

        social = Adw.PreferencesGroup(
            title=_("Integrações sociais"),
            description=_(
                "Recursos opcionais; nenhum dado é enviado enquanto estiverem desligados."
            ),
        )
        lastfm_credentials = self.lastfm_credentials.load()
        lastfm_connected = lastfm_credentials.session is not None
        lastfm = Adw.SwitchRow(
            title=_("Scrobble no Last.fm"),
            subtitle=(
                _("Conectado como {username}").format(username=lastfm_credentials.session.username)
                if lastfm_connected
                else _("Configure uma chave de API e autorize a conta")
            ),
        )
        lastfm.set_active(self.preferences.lastfm_enabled and lastfm_connected)
        lastfm.set_sensitive(lastfm_connected)
        lastfm.connect(
            "notify::active",
            lambda row, _pspec: self._preference_changed("lastfm_enabled", row.get_active()),
        )
        social.add(lastfm)

        lastfm_key = Adw.ActionRow(
            title=_("Chave da API do Last.fm"),
            subtitle=_("Crie uma API Account gratuita no site do Last.fm"),
        )
        lastfm_key_entry = Gtk.Entry(
            text=self.preferences.lastfm_api_key,
            placeholder_text=_("API key"),
            valign=Gtk.Align.CENTER,
        )
        lastfm_key_entry.set_size_request(260, -1)
        lastfm_key_entry.connect(
            "changed",
            lambda entry: self._preference_changed("lastfm_api_key", entry.get_text().strip()),
        )
        lastfm_key.add_suffix(lastfm_key_entry)
        social.add(lastfm_key)

        lastfm_secret = Adw.ActionRow(
            title=_("Segredo da API do Last.fm"),
            subtitle=_("Armazenado no chaveiro do sistema"),
        )
        lastfm_secret_entry = Gtk.PasswordEntry(
            placeholder_text=_("Configurado") if lastfm_credentials.api_secret else _("Secret"),
            show_peek_icon=True,
            valign=Gtk.Align.CENTER,
        )
        lastfm_secret_entry.set_size_request(260, -1)
        lastfm_secret_entry.connect(
            "activate", lambda entry: self._configure_lastfm_secret(entry.get_text())
        )
        secret_focus = Gtk.EventControllerFocus()
        secret_focus.connect(
            "leave",
            lambda *_: self._configure_lastfm_secret(lastfm_secret_entry.get_text()),
        )
        lastfm_secret_entry.add_controller(secret_focus)
        lastfm_secret.add_suffix(lastfm_secret_entry)
        social.add(lastfm_secret)

        lastfm_account = Adw.ActionRow(
            title=_("Autorização do Last.fm"),
            subtitle=_("A autorização é concluída no navegador padrão"),
        )
        if lastfm_connected:
            disconnect_lastfm = Gtk.Button(label=_("Desconectar"), valign=Gtk.Align.CENTER)
            disconnect_lastfm.add_css_class("pill")
            disconnect_lastfm.add_css_class("destructive-action")
            disconnect_lastfm.connect("clicked", lambda *_: self._disconnect_lastfm())
            lastfm_account.add_suffix(disconnect_lastfm)
        else:
            authorize_lastfm = Gtk.Button(label=_("Autorizar"), valign=Gtk.Align.CENTER)
            authorize_lastfm.add_css_class("pill")
            authorize_lastfm.connect("clicked", lambda *_: self._begin_lastfm_authorization())
            lastfm_account.add_suffix(authorize_lastfm)
            finish_lastfm = Gtk.Button(label=_("Concluir"), valign=Gtk.Align.CENTER)
            finish_lastfm.add_css_class("pill")
            finish_lastfm.add_css_class("suggested-action")
            finish_lastfm.set_sensitive(bool(self._lastfm_pending_token))
            finish_lastfm.connect("clicked", lambda *_: self._finish_lastfm_authorization())
            lastfm_account.add_suffix(finish_lastfm)
        social.add(lastfm_account)

        discord = Adw.SwitchRow(
            title=_("Discord Rich Presence"),
            subtitle=_("Mostra a faixa atual usando somente o IPC local do Discord"),
        )
        discord.set_active(self.preferences.discord_enabled)
        discord.connect(
            "notify::active",
            lambda row, _pspec: self._discord_preference_changed(
                "discord_enabled", row.get_active()
            ),
        )
        social.add(discord)
        discord_id = Adw.ActionRow(
            title=_("Client ID do Discord"),
            subtitle=_("ID de uma aplicação criada no Discord Developer Portal"),
        )
        discord_id_entry = Gtk.Entry(
            text=self.preferences.discord_client_id,
            placeholder_text=_("Client ID"),
            valign=Gtk.Align.CENTER,
        )
        discord_id_entry.set_size_request(260, -1)
        discord_id_entry.connect(
            "changed",
            lambda entry: self._discord_preference_changed(
                "discord_client_id", entry.get_text().strip()
            ),
        )
        discord_id.add_suffix(discord_id_entry)
        social.add(discord_id)
        page.add(social)
        self._append_optional_preferences(page)

        audio = Adw.PreferencesGroup(
            title=_("Áudio"),
            description=_("Processamento nativo em tempo real pelo GStreamer."),
        )
        audio.add(
            combo(
                "Equalizador",
                [("Plano", "flat"), ("Graves", "bass"), ("Voz", "vocal"), ("Agudos", "treble")],
                self.preferences.equalizer,
                lambda value: self._preference_changed("equalizer", value, audio=True),
            )
        )
        normalization = Adw.SwitchRow(
            title=_("Normalização de volume"), subtitle=_("Reduz variações de volume entre faixas")
        )
        normalization.set_active(self.preferences.normalization)
        normalization.connect(
            "notify::active",
            lambda row, _pspec: self._preference_changed(
                "normalization", row.get_active(), audio=True
            ),
        )
        audio.add(normalization)
        silence = Adw.SwitchRow(
            title=_("Pular silêncio"), subtitle=_("Remove trechos silenciosos longos")
        )
        silence.set_active(self.preferences.skip_silence)
        silence.connect(
            "notify::active",
            lambda row, _pspec: self._preference_changed(
                "skip_silence", row.get_active(), audio=True
            ),
        )
        audio.add(silence)

        def scale_row(
            title: str,
            lower: float,
            upper: float,
            step: float,
            value: float,
            callback,
            digits: int = 1,
        ) -> Adw.ActionRow:
            row = Adw.ActionRow(title=title)
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lower, upper, step)
            scale.set_draw_value(True)
            scale.set_digits(digits)
            scale.set_value(value)
            scale.set_size_request(260, -1)
            scale.set_valign(Gtk.Align.CENTER)
            scale.connect("value-changed", lambda widget: callback(widget.get_value()))
            row.add_suffix(scale)
            return row

        audio.add(
            scale_row(
                "Velocidade",
                0.5,
                2.0,
                0.05,
                self.preferences.speed,
                lambda value: self._preference_changed("speed", value, audio=True),
                2,
            )
        )
        audio.add(
            scale_row(
                "Tom (semitons)",
                -12,
                12,
                1,
                self.preferences.pitch,
                lambda value: self._preference_changed("pitch", value, audio=True),
                0,
            )
        )
        timer_values = [
            ("Desligado", 0),
            ("15 minutos", 15),
            ("30 minutos", 30),
            ("1 hora", 60),
            ("1 hora e 30", 90),
        ]
        timer = Adw.ComboRow(
            title=_("Temporizador"), model=Gtk.StringList.new([label for label, _ in timer_values])
        )
        timer.connect(
            "notify::selected",
            lambda row, _pspec: self._set_sleep_timer(timer_values[row.get_selected()][1]),
        )
        audio.add(timer)
        page.add(audio)

        self.stack.add_named(page, "settings")
        self.stack.set_visible_child_name("settings")
