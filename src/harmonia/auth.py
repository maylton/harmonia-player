from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
from gi.repository import Adw, Gtk, WebKit

from .i18n import _
from .login import LOGIN_URL, MUSIC_ORIGIN, session_cookie_header


class LoginWindow(Adw.Window):
    """Embedded Google login that extracts the resulting YouTube Music session."""

    def __init__(self, parent: Gtk.Window, data_dir: Path, on_success, on_manual):
        super().__init__(
            title=_("Conectar ao YouTube Music"),
            default_width=860,
            default_height=680,
            modal=True,
            transient_for=parent,
        )
        self.on_success = on_success
        self.completing = False
        data_dir.mkdir(parents=True, exist_ok=True)
        session = WebKit.NetworkSession.new(str(data_dir / "data"), str(data_dir / "cache"))
        self.cookies = session.get_cookie_manager()
        self.webview = WebKit.WebView(network_session=session)
        settings = self.webview.get_settings()
        settings.set_enable_javascript(True)
        settings.set_enable_page_cache(True)

        toolbar = Adw.HeaderBar()
        back = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text=_("Voltar"))
        back.connect(
            "clicked",
            lambda *_: self.webview.go_back() if self.webview.can_go_back() else self.close(),
        )
        toolbar.pack_start(back)
        manual = Gtk.Button(label=_("Usar cookie manualmente"))
        manual.connect("clicked", lambda *_: (self.close(), on_manual()))
        toolbar.pack_end(manual)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(toolbar)
        box.append(self.webview)
        self.webview.set_vexpand(True)
        self.set_content(box)
        self.webview.connect("load-changed", self._load_changed)
        self.webview.load_uri(LOGIN_URL)

    def _load_changed(self, view, event):
        if event != WebKit.LoadEvent.FINISHED or self.completing:
            return
        uri = view.get_uri() or ""
        if uri.startswith(MUSIC_ORIGIN):
            self.cookies.get_cookies(MUSIC_ORIGIN, None, self._cookies_ready)

    def _cookies_ready(self, manager, result):
        try:
            cookies = manager.get_cookies_finish(result)
            raw = session_cookie_header(
                (cookie.get_name(), cookie.get_value()) for cookie in cookies
            )
        except Exception:
            return
        if raw is None:
            return
        self.completing = True
        self.on_success(raw)
        self.close()
