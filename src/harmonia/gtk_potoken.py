from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

import gi

gi.require_version("WebKit", "6.0")
from gi.repository import GLib, WebKit  # noqa: E402

from .potoken import POTOKEN_HTML, PoTokenResult, install_potoken_provider  # noqa: E402

LOGGER = logging.getLogger(__name__)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@dataclass(slots=True)
class _Request:
    video_id: str
    visitor_data: str
    event: threading.Event = field(default_factory=threading.Event)
    result: PoTokenResult | None = None
    error: str = ""


JavaScriptCallback = Callable[[str | None, str], None]
TokenCallback = Callable[[str], None]


class GtkPoTokenProvider:
    """BotGuard provider backed by an ephemeral WebKitGTK page.

    Stream extraction runs in worker threads, while WebKit must stay on GTK's
    main thread. ``get_po_token`` therefore queues a request through GLib and
    waits on a threading event until both visitor- and video-bound tokens are
    minted by the hidden page.
    """

    def __init__(self) -> None:
        self._session = WebKit.NetworkSession.new_ephemeral()
        self._webview = WebKit.WebView(network_session=self._session)
        settings = self._webview.get_settings()
        settings.set_enable_javascript(True)
        if hasattr(settings, "set_user_agent"):
            settings.set_user_agent(_USER_AGENT)

        self._loaded = False
        self._closed = False
        self._initializing = False
        self._pending: list[_Request] = []
        self._active: _Request | None = None
        self._visitor_cache: dict[str, tuple[str, float]] = {}
        self._webview.connect("load-changed", self._load_changed)
        self._reload_page()

    def get_po_token(
        self,
        video_id: str,
        visitor_data: str,
        cookie: str | None = None,
        *,
        timeout: float = 50.0,
    ) -> PoTokenResult | None:
        del cookie  # The BotGuard page intentionally never receives account cookies.
        if self._closed or not video_id or not visitor_data:
            return None
        request = _Request(video_id, visitor_data)
        GLib.idle_add(self._enqueue, request)
        if not request.event.wait(max(1.0, timeout)):
            LOGGER.warning("GTK PoToken request timed out")
            return None
        if request.error:
            LOGGER.warning("GTK PoToken request failed: %s", request.error)
        return request.result

    def _reload_page(self) -> None:
        if self._closed:
            return
        self._loaded = False
        self._initializing = False
        self._visitor_cache.clear()
        self._webview.load_html(POTOKEN_HTML, "https://www.youtube.com/")

    def _load_changed(self, _view, event) -> None:
        if self._closed or event != WebKit.LoadEvent.FINISHED:
            return
        self._loaded = True
        self._ensure_initialized()

    def _enqueue(self, request: _Request) -> bool:
        if self._closed:
            request.error = "PoToken provider encerrado"
            request.event.set()
            return GLib.SOURCE_REMOVE
        self._pending.append(request)
        self._ensure_initialized()
        return GLib.SOURCE_REMOVE

    def _evaluate(self, script: str, callback: JavaScriptCallback) -> None:
        if self._closed:
            callback(None, "PoToken provider encerrado")
            return

        def completed(view, result, _user_data=None) -> None:
            try:
                value = view.evaluate_javascript_finish(result)
                text = value.to_string() if value is not None else ""
            except Exception as exc:
                callback(None, str(exc))
                return
            callback(text, "")

        self._webview.evaluate_javascript(
            script,
            -1,
            None,
            None,
            None,
            completed,
            None,
        )

    @staticmethod
    def _decode_state(value: str | None) -> dict[str, Any]:
        try:
            state = json.loads(value or "{}")
        except (TypeError, json.JSONDecodeError):
            return {}
        return state if isinstance(state, dict) else {}

    def _ensure_initialized(self) -> None:
        if self._closed or not self._loaded or not self._pending:
            return
        if self._active is not None or self._initializing:
            return
        self._evaluate(
            "JSON.stringify({ready:!!harmoniaPoState.ready,error:harmoniaPoState.error||'',"
            "expiresAt:Number(harmoniaPoState.expiresAt||0),"
            "initializing:!!harmoniaPoState.initializing})",
            self._state_checked,
        )

    def _state_checked(self, value: str | None, error: str) -> None:
        if self._closed:
            return
        if error:
            self._fail_all(error)
            return
        state = self._decode_state(value)
        if state.get("ready") and float(state.get("expiresAt") or 0) > time.time() * 1000 + 30_000:
            self._start_next()
            return
        if state.get("initializing"):
            self._initializing = True
            GLib.timeout_add(80, self._poll_initialization)
            return
        self._initializing = True
        self._evaluate("harmoniaInitialize(); undefined;", self._initialization_started)

    def _initialization_started(self, _value: str | None, error: str) -> None:
        if self._closed:
            return
        if error:
            self._initializing = False
            self._fail_all(error)
            return
        GLib.timeout_add(80, self._poll_initialization)

    def _poll_initialization(self) -> bool:
        if self._closed or not self._initializing:
            return GLib.SOURCE_REMOVE
        self._evaluate(
            "JSON.stringify({ready:!!harmoniaPoState.ready,error:harmoniaPoState.error||'',"
            "expiresAt:Number(harmoniaPoState.expiresAt||0),"
            "initializing:!!harmoniaPoState.initializing})",
            self._initialization_polled,
        )
        return GLib.SOURCE_REMOVE

    def _initialization_polled(self, value: str | None, evaluate_error: str) -> None:
        if self._closed:
            return
        if evaluate_error:
            self._initializing = False
            self._fail_all(evaluate_error)
            return
        state = self._decode_state(value)
        error = str(state.get("error") or "")
        if error:
            self._initializing = False
            LOGGER.warning("GTK BotGuard initialization failed: %s", error)
            self._fail_all(error)
            GLib.timeout_add(250, self._reload_after_failure)
            return
        if state.get("ready"):
            self._initializing = False
            self._start_next()
            return
        GLib.timeout_add(80, self._poll_initialization)

    def _reload_after_failure(self) -> bool:
        self._reload_page()
        return GLib.SOURCE_REMOVE

    def _start_next(self) -> None:
        if self._closed or self._active is not None or not self._pending:
            return
        self._active = self._pending.pop(0)
        request = self._active
        cached = self._visitor_cache.get(request.visitor_data)
        if cached and cached[1] > time.time() + 30:
            self._mint_video(cached[0])
            return
        self._mint_identifier(request.visitor_data, self._visitor_minted)

    def _mint_identifier(self, identifier: str, callback: TokenCallback) -> None:
        request_id = uuid.uuid4().hex
        script = f"harmoniaGenerate({json.dumps(identifier)}, {json.dumps(request_id)}); undefined;"

        def started(_value: str | None, error: str) -> None:
            if error:
                self._finish_active(None, error)
                return
            self._poll_token(request_id, callback, 0)

        self._evaluate(script, started)

    def _poll_token(self, request_id: str, callback: TokenCallback, attempt: int) -> None:
        if self._closed or self._active is None:
            return
        expression = (
            "JSON.stringify({token:harmoniaPoState.results["
            + json.dumps(request_id)
            + "]||'',error:harmoniaPoState.resultErrors["
            + json.dumps(request_id)
            + "]||''})"
        )

        def completed(value: str | None, evaluate_error: str) -> None:
            self._token_polled(request_id, callback, attempt, value, evaluate_error)

        self._evaluate(expression, completed)

    def _token_polled(
        self,
        request_id: str,
        callback: TokenCallback,
        attempt: int,
        value: str | None,
        evaluate_error: str,
    ) -> None:
        if self._closed or self._active is None:
            return
        if evaluate_error:
            self._finish_active(None, evaluate_error)
            return
        result = self._decode_state(value)
        error = str(result.get("error") or "")
        token = str(result.get("token") or "")
        if error:
            self._finish_active(None, error)
            return
        if token:
            cleanup = (
                "delete harmoniaPoState.results["
                + json.dumps(request_id)
                + "];delete harmoniaPoState.resultErrors["
                + json.dumps(request_id)
                + "];undefined;"
            )
            self._evaluate(cleanup, lambda _value, _error: None)
            callback(token)
            return
        if attempt >= 300:
            self._finish_active(None, "tempo esgotado ao gerar PoToken")
            return
        GLib.timeout_add(40, self._poll_token_once, request_id, callback, attempt + 1)

    def _poll_token_once(self, request_id: str, callback: TokenCallback, attempt: int) -> bool:
        self._poll_token(request_id, callback, attempt)
        return GLib.SOURCE_REMOVE

    def _visitor_minted(self, token: str) -> None:
        request = self._active
        if request is None:
            return
        self._visitor_cache[request.visitor_data] = (token, time.time() + 300)
        self._mint_video(token)

    def _mint_video(self, visitor_token: str) -> None:
        request = self._active
        if request is None:
            return

        def done(video_token: str) -> None:
            current = self._active
            if current is None:
                return
            self._finish_active(
                PoTokenResult(visitor_token, video_token, current.visitor_data),
                "",
            )

        self._mint_identifier(request.video_id, done)

    def _finish_active(self, result: PoTokenResult | None, error: str) -> None:
        request = self._active
        self._active = None
        if request is not None:
            request.result = result
            request.error = error
            request.event.set()
        GLib.idle_add(self._ensure_next)

    def _ensure_next(self) -> bool:
        self._ensure_initialized()
        return GLib.SOURCE_REMOVE

    def _fail_all(self, error: str) -> None:
        if self._active is not None:
            current = self._active
            self._active = None
            current.error = error
            current.event.set()
        pending, self._pending = self._pending, []
        for request in pending:
            request.error = error
            request.event.set()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._fail_all("PoToken provider encerrado")
        self._webview.stop_loading()
        self._webview = None
        self._session = None


def install_gtk_potoken(window_class) -> None:
    """Attach the WebKit PoToken provider to the GTK application lifecycle."""
    if getattr(window_class, "_harmonia_potoken_installed", False):
        return
    window_class._harmonia_potoken_installed = True

    original_init = window_class.__init__
    original_shutdown = window_class._shutdown_application

    def wrapped_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        provider = GtkPoTokenProvider()
        self._gtk_potoken_provider = provider
        install_potoken_provider(provider)

    def wrapped_shutdown(self, *args, **kwargs):
        result = original_shutdown(self, *args, **kwargs)
        if getattr(self, "_gtk_potoken_provider", None) is not None:
            install_potoken_provider(None)
            self._gtk_potoken_provider = None
        return result

    window_class.__init__ = wrapped_init
    window_class._shutdown_application = wrapped_shutdown
