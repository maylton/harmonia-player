from __future__ import annotations

import logging
import threading
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from .i18n import _, ngettext
from .models import (
    DownloadRecord,
    HistoryEntry,
)
from .ui import (
    action_button,
    icon_button,
    page_header,
    page_shell,
)

LOGGER = logging.getLogger(__name__)


class WindowHistoryMixin:
    def _render_downloads(self) -> None:
        old = self.stack.get_child_by_name("downloads")
        if old:
            self.stack.remove(old)
        records = self.storage.load_downloads()
        shell = page_shell("reading", spacing=20)
        scroll, content = shell.scroll, shell.content
        validate = action_button(_("Validar conta"), "emblem-ok-symbolic", role="secondary")
        validate.connect(
            "clicked",
            lambda *_: threading.Thread(
                target=self._validate_download_account, daemon=True
            ).start(),
        )
        content.append(
            page_header(
                _("Downloads"),
                ngettext(
                    "{count} item · {size} utilizado",
                    "{count} itens · {size} utilizados",
                    len(records),
                ).format(
                    count=len(records),
                    size=self._format_bytes(self.storage.download_storage_bytes()),
                ),
                actions=(validate,),
            )
        )
        if not records:
            content.append(
                Adw.StatusPage(
                    icon_name="folder-download-symbolic",
                    title=_("Nenhum download"),
                    description=_(
                        "Use o botão de download em um álbum ou playlist para ouvir offline."
                    ),
                )
            )
        else:
            group = Adw.PreferencesGroup()
            status_labels = {
                "queued": _("Na fila"),
                "downloading": _("Baixando"),
                "paused": _("Pausado"),
                "completed": _("Disponível offline"),
                "failed": _("Falha"),
            }
            for record in records:
                subtitle = status_labels.get(record.status, record.status)
                if record.total_bytes:
                    subtitle += f" · {self._format_bytes(record.downloaded_bytes)} de {self._format_bytes(record.total_bytes)}"
                if record.error:
                    subtitle += f" · {record.error}"
                row = Adw.ActionRow()
                row.add_css_class("media-row")
                row.set_use_markup(False)
                row.set_title(record.item.title)
                row.set_subtitle(subtitle)
                row.add_prefix(self._square_cover(record.item, size=48, fixed=True))
                controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
                if record.status == "downloading":
                    pause = icon_button("media-playback-pause-symbolic", _("Pausar"), size="sm")
                    pause.connect(
                        "clicked",
                        lambda *_args, item_id=record.item.id: self.downloads.pause(item_id),
                    )
                    controls.append(pause)
                elif record.status in ("paused", "failed", "queued"):
                    resume = icon_button("media-playback-start-symbolic", _("Retomar"), size="sm")
                    resume.connect(
                        "clicked", lambda *_args, item=record.item: self.downloads.start(item)
                    )
                    controls.append(resume)
                elif record.status == "completed":
                    play = icon_button(
                        "media-playback-start-symbolic", _("Reproduzir offline"), size="sm"
                    )
                    play.connect(
                        "clicked", lambda *_args, item=record.item: self.set_queue([item], 0)
                    )
                    controls.append(play)
                remove = icon_button(
                    "user-trash-symbolic", _("Excluir download"), size="sm", destructive=True
                )
                remove.connect(
                    "clicked", lambda *_args, item_id=record.item.id: self.downloads.remove(item_id)
                )
                controls.append(remove)
                row.add_suffix(controls)
                group.add(row)
            content.append(group)
        self.stack.add_named(scroll, "downloads")
        self.stack.set_visible_child_name("downloads")

    def _download_updated(self, _record: DownloadRecord | None) -> bool:
        if self.main_view == "downloads":
            self._render_downloads()
        if self.main_view == "library" and self.library_origin == "downloads":
            self._render()
        return False

    def _history_loaded(self, remote: list[HistoryEntry], error: str | None) -> bool:
        if self.main_view != "history":
            return False
        local = self.storage.load_history()
        self._history_entries = [*remote, *local]
        self._render_history(self._history_entries, loading=False)
        if error:
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=_("O histórico local foi preservado; o remoto falhou: {error}").format(
                        error=error
                    ),
                    timeout=5,
                )
            )
        return False

    def _render_history(self, entries: list[HistoryEntry], loading: bool = False) -> None:
        old = self.stack.get_child_by_name("history")
        if old:
            self.stack.remove(old)
        shell = page_shell("reading", spacing=20)
        scroll, content = shell.scroll, shell.content
        clear = action_button(_("Limpar local"), "user-trash-symbolic", role="secondary")
        clear.set_sensitive(any(entry.source == "local" for entry in entries))
        clear.connect("clicked", lambda *_: self._clear_local_history())
        content.append(
            page_header(
                _("Histórico"),
                _("Reproduções da conta e deste dispositivo"),
                actions=(clear,),
            )
        )

        privacy = Adw.ActionRow()
        privacy.set_use_markup(False)
        privacy.set_title(_("Registrar neste dispositivo"))
        privacy.set_subtitle(
            _("Quando desativado, o Harmonia não grava novas reproduções localmente.")
        )
        toggle = Gtk.Switch(active=self.storage.history_enabled(), valign=Gtk.Align.CENTER)
        toggle.connect("notify::active", self._history_privacy_changed)
        privacy.add_suffix(toggle)
        privacy.set_activatable_widget(toggle)
        privacy.add_css_class("boxed-list")
        content.append(privacy)
        if loading:
            spinner = Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER)
            content.append(spinner)

        grouped: dict[str, list[HistoryEntry]] = {}
        for entry in entries:
            group = entry.group
            if entry.source == "local" and entry.played_at:
                group = datetime.fromtimestamp(entry.played_at).strftime("%d/%m/%Y")
            grouped.setdefault(group, []).append(entry)
        if not grouped and not loading:
            empty = Adw.StatusPage(
                icon_name="document-open-recent-symbolic",
                title=_("Nenhuma reprodução"),
                description=_("As músicas tocadas aparecerão aqui."),
            )
            content.append(empty)
        for group_name, group_entries in grouped.items():
            group = Adw.PreferencesGroup(title=group_name)
            for entry in group_entries:
                row = Adw.ActionRow()
                row.add_css_class("media-row")
                row.set_use_markup(False)
                row.set_title(entry.item.title)
                row.set_subtitle(
                    entry.item.subtitle
                    or (_("YouTube Music") if entry.source == "remote" else _("Neste dispositivo"))
                )
                row.set_activatable(True)
                row.add_prefix(self._square_cover(entry.item, size=48, fixed=True))
                remove = icon_button(
                    "user-trash-symbolic", _("Remover do histórico"), size="sm", destructive=True
                )
                remove.set_sensitive(entry.source == "local" or bool(entry.feedback_token))
                remove.connect(
                    "clicked",
                    lambda *_args, selected=entry: GLib.idle_add(
                        self._remove_history_entry, selected
                    ),
                )
                row.add_suffix(remove)
                row.connect(
                    "activated", lambda _row, selected=entry.item: self.set_queue([selected], 0)
                )
                group.add(row)
            content.append(group)
        self.stack.add_named(scroll, "history")
        self.stack.set_visible_child_name("history")

    def _history_privacy_changed(self, switch: Gtk.Switch, _pspec) -> None:
        self.storage.set_history_enabled(switch.get_active())
        self.toast_overlay.add_toast(
            Adw.Toast(
                title=_("Histórico local ativado")
                if switch.get_active()
                else _("Histórico local pausado")
            )
        )

    def _clear_local_history(self) -> None:
        self.storage.clear_history()
        self._history_entries = [
            entry for entry in self._history_entries if entry.source != "local"
        ]
        self._render_history(self._history_entries)

    def _remove_history_entry(self, entry: HistoryEntry) -> None:
        if entry.source == "local" and entry.id is not None:
            self.storage.remove_history(entry.id)
            self._history_entries = [
                candidate for candidate in self._history_entries if candidate is not entry
            ]
            self._render_history(self._history_entries)
            return

        def worker() -> None:
            try:
                self.youtube.remove_history_item(entry.feedback_token or "")
                GLib.idle_add(done, None)
            except Exception as exc:
                GLib.idle_add(done, str(exc))

        def done(error: str | None) -> bool:
            if error:
                self.toast_overlay.add_toast(
                    Adw.Toast(
                        title=_("Não foi possível remover: {error}").format(error=error),
                        timeout=5,
                    )
                )
            else:
                self._history_entries = [
                    candidate for candidate in self._history_entries if candidate is not entry
                ]
                self._render_history(self._history_entries)
            return False

        threading.Thread(target=worker, daemon=True, name="remove-history").start()
