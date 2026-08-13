from __future__ import annotations

import logging
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from .i18n import _
from .models import (
    SearchGroup,
    SearchResults,
)
from .ui import (
    action_button,
    page_header,
    page_shell,
)

LOGGER = logging.getLogger(__name__)


class WindowSearchMixin:
    def _search_text_changed(self, entry: Gtk.SearchEntry) -> None:
        if self._suggestion_timeout:
            GLib.source_remove(self._suggestion_timeout)
            self._suggestion_timeout = 0
        query = entry.get_text().strip()
        self._suggestion_request += 1
        request_id = self._suggestion_request
        if len(query) < 2:
            self.search_suggestions.popdown()
            return

        def begin() -> bool:
            self._suggestion_timeout = 0

            def worker() -> None:
                try:
                    values = self.youtube.suggestions(query)
                    GLib.idle_add(self._show_search_suggestions, request_id, query, values)
                except Exception:
                    GLib.idle_add(self._show_search_suggestions, request_id, query, [])

            threading.Thread(target=worker, daemon=True, name="search-suggestions").start()
            return False

        self._suggestion_timeout = GLib.timeout_add(280, begin)

    def _show_search_suggestions(
        self,
        request_id: int,
        query: str,
        suggestions: list[str],
    ) -> bool:
        if request_id != self._suggestion_request or query != self.search_entry.get_text().strip():
            return False
        if not suggestions or not self.search_entry.has_focus():
            self.search_suggestions.popdown()
            return False
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.add_css_class("search-suggestion-list")
        for value in suggestions[:8]:
            button = Gtk.Button(label=value, icon_name="system-search-symbolic")
            button.add_css_class("flat")
            button.set_halign(Gtk.Align.FILL)
            button.connect(
                "clicked", lambda _button, selected=value: self._choose_search_suggestion(selected)
            )
            box.append(button)
        self.search_suggestions.set_child(box)
        self.search_suggestions.popup()
        return False

    def _choose_search_suggestion(self, value: str) -> None:
        self.search_entry.set_text(value)
        self.search_suggestions.popdown()
        self.search(value)

    def search(self, query: str) -> None:
        query = query.strip()
        if not query:
            return
        self.search_suggestions.popdown()
        self._search_request += 1
        request_id = self._search_request
        status = Adw.StatusPage(
            icon_name="system-search-symbolic", title=_("Buscando…"), description=query
        )
        old = self.stack.get_child_by_name("search")
        if old:
            self.stack.remove(old)
        self.stack.add_named(status, "search")
        self.stack.set_visible_child_name("search")
        self.back.set_visible(True)

        def worker():
            try:
                results = self.youtube.universal_search(query)
                GLib.idle_add(self._show_search, request_id, results, None)
            except Exception as exc:
                GLib.idle_add(self._show_search, request_id, None, str(exc))

        threading.Thread(target=worker, daemon=True, name="universal-search").start()

    def _show_search(
        self,
        request_id: int,
        results: SearchResults | None,
        error: str | None,
    ) -> bool:
        if request_id != self._search_request:
            return False
        old = self.stack.get_child_by_name("search")
        if old:
            self.stack.remove(old)
        query = results.query if results else self.search_entry.get_text().strip()
        if error:
            page = Adw.StatusPage(
                icon_name="dialog-error-symbolic", title=_("A busca falhou"), description=error
            )
        elif not results or not results.groups:
            detail = ""
            if results and results.errors:
                detail = _(" Algumas categorias não puderam ser consultadas.")
            page = Adw.StatusPage(
                icon_name="system-search-symbolic",
                title=_("Nenhum resultado"),
                description=_("Nada encontrado para “{query}”").format(query=query),
            )
            if detail:
                page.set_description(page.get_description() + detail)
        else:
            self.search_results = results
            shell = page_shell("reading", spacing=22)
            page, box = shell.scroll, shell.content
            box.append(page_header(_("Resultados para “{query}”").format(query=query)))
            if results.errors:
                warning = Gtk.Label(
                    label=_(
                        "Algumas categorias não puderam ser carregadas; os resultados disponíveis foram preservados."
                    ),
                    xalign=0,
                    wrap=True,
                )
                warning.add_css_class("search-partial-warning")
                box.append(warning)
            for search_group in results.groups:
                box.append(self._search_group_widget(results, search_group))
        self.stack.add_named(page, "search")
        self.stack.set_visible_child_name("search")
        return False

    def _search_group_widget(self, results: SearchResults, search_group: SearchGroup) -> Gtk.Widget:
        group = Adw.PreferencesGroup(title=search_group.title)
        playable = [item for item in search_group.items if item.kind in ("songs", "videos")]
        for item in search_group.items:
            row = Adw.ActionRow()
            row.add_css_class("media-row")
            row.set_use_markup(False)
            row.set_title(item.title)
            row.set_subtitle(item.subtitle)
            row.set_activatable(True)
            row.add_prefix(self._square_cover(item, size=48, fixed=True))
            icon = (
                "media-playback-start-symbolic"
                if item.kind in ("songs", "videos")
                else "go-next-symbolic"
            )
            row.add_suffix(Gtk.Image.new_from_icon_name(icon))
            if item.kind in ("songs", "videos"):
                row.connect(
                    "activated",
                    lambda _row, selected=item, source=playable: self.set_queue(
                        source, source.index(selected)
                    ),
                )
            else:
                row.connect("activated", lambda _row, selected=item: self.open_item(selected))
            group.add(row)
        if search_group.continuation:
            more = action_button(
                _("Carregar mais {category}").format(category=search_group.title.lower()),
                role="secondary",
            )
            more.set_halign(Gtk.Align.CENTER)
            more.connect(
                "clicked",
                lambda button, selected=search_group: self._load_more_search(
                    results, selected, button
                ),
            )
            group.add(more)
        return group

    def _load_more_search(
        self,
        results: SearchResults,
        group: SearchGroup,
        button: Gtk.Button,
    ) -> None:
        button.set_sensitive(False)
        request_id = self._search_request

        def worker() -> None:
            try:
                incoming = self.youtube.search_more(results.query, group)
                GLib.idle_add(
                    self._search_more_done, request_id, results, group.key, incoming, None
                )
            except Exception as exc:
                GLib.idle_add(
                    self._search_more_done, request_id, results, group.key, None, str(exc)
                )

        threading.Thread(target=worker, daemon=True, name="search-continuation").start()

    def _search_more_done(
        self,
        request_id: int,
        results: SearchResults,
        key: str,
        incoming: SearchGroup | None,
        error: str | None,
    ) -> bool:
        if request_id != self._search_request:
            return False
        group = results.group(key)
        if error or group is None or incoming is None:
            self.toast_overlay.add_toast(
                Adw.Toast(
                    title=_("Não foi possível carregar mais resultados: {error}").format(
                        error=error
                    )
                )
            )
            self._show_search(request_id, results, None)
            return False
        known = {item.id for item in group.items}
        group.items.extend(item for item in incoming.items if item.id not in known)
        group.continuation = incoming.continuation
        self._show_search(request_id, results, None)
        return False
