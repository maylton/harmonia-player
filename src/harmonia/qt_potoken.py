from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile

from .potoken import POTOKEN_HTML, PoTokenResult

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


class QtPoTokenProvider(QObject):
    """BotGuard provider backed by an off-the-record QtWebEngine page.

    Public calls are synchronous because extraction runs in worker threads. A
    queued Qt signal moves every WebEngine operation to the GUI thread, while a
    threading.Event wakes the extractor when both visitor- and video-bound
    tokens have been minted.
    """

    requestQueued = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._profile = QWebEngineProfile(self)
        self._profile.setHttpUserAgent(_USER_AGENT)
        self._page = QWebEnginePage(self._profile, self)
        self._loaded = False
        self._closed = False
        self._initializing = False
        self._pending: list[_Request] = []
        self._active: _Request | None = None
        self._visitor_cache: dict[str, tuple[str, float]] = {}
        self._generation = 0
        self._page.loadFinished.connect(self._load_finished)
        self.requestQueued.connect(self._enqueue)
        self._reload_page()

    def get_po_token(
        self,
        video_id: str,
        visitor_data: str,
        cookie: str | None = None,
        *,
        timeout: float = 50.0,
    ) -> PoTokenResult | None:
        del cookie  # BotGuard page intentionally never receives account cookies.
        if self._closed or not video_id or not visitor_data:
            return None
        request = _Request(video_id, visitor_data)
        self.requestQueued.emit(request)
        if not request.event.wait(max(1.0, timeout)):
            LOGGER.warning("Qt PoToken request timed out")
            return None
        if request.error:
            LOGGER.warning("Qt PoToken request failed: %s", request.error)
        return request.result

    def _reload_page(self) -> None:
        if self._closed:
            return
        self._generation += 1
        self._loaded = False
        self._initializing = False
        self._visitor_cache.clear()
        self._page.setHtml(POTOKEN_HTML, QUrl("https://www.youtube.com/"))

    @Slot(bool)
    def _load_finished(self, ok: bool) -> None:
        if self._closed:
            return
        self._loaded = bool(ok)
        if not ok:
            self._fail_all("QtWebEngine não conseguiu carregar o ambiente BotGuard")
            return
        self._ensure_initialized()

    @Slot(object)
    def _enqueue(self, request: _Request) -> None:
        if self._closed:
            request.error = "PoToken provider encerrado"
            request.event.set()
            return
        self._pending.append(request)
        self._ensure_initialized()

    def _ensure_initialized(self) -> None:
        if self._closed or not self._loaded or not self._pending:
            return
        if self._active is not None:
            return
        if self._initializing:
            return
        self._page.runJavaScript(
            "JSON.stringify({ready:!!harmoniaPoState.ready,error:harmoniaPoState.error||'',"
            "expiresAt:Number(harmoniaPoState.expiresAt||0),initializing:!!harmoniaPoState.initializing})",
            self._state_checked,
        )

    def _state_checked(self, value: Any) -> None:
        if self._closed:
            return
        try:
            state = json.loads(str(value or "{}"))
        except (TypeError, json.JSONDecodeError):
            state = {}
        if state.get("ready") and float(state.get("expiresAt") or 0) > time.time() * 1000 + 30_000:
            self._start_next()
            return
        if state.get("initializing"):
            self._initializing = True
            QTimer.singleShot(80, self._poll_initialization)
            return
        self._initializing = True
        self._page.runJavaScript("harmoniaInitialize(); undefined;")
        QTimer.singleShot(80, self._poll_initialization)

    def _poll_initialization(self) -> None:
        if self._closed or not self._initializing:
            return
        self._page.runJavaScript(
            "JSON.stringify({ready:!!harmoniaPoState.ready,error:harmoniaPoState.error||'',"
            "expiresAt:Number(harmoniaPoState.expiresAt||0),initializing:!!harmoniaPoState.initializing})",
            self._initialization_polled,
        )

    def _initialization_polled(self, value: Any) -> None:
        if self._closed:
            return
        try:
            state = json.loads(str(value or "{}"))
        except (TypeError, json.JSONDecodeError):
            state = {}
        error = str(state.get("error") or "")
        if error:
            self._initializing = False
            LOGGER.warning("BotGuard initialization failed: %s", error)
            self._fail_all(error)
            # Recreate the renderer state for the next request instead of
            # permanently disabling PoTokens for this application session.
            QTimer.singleShot(250, self._reload_page)
            return
        if state.get("ready"):
            self._initializing = False
            self._start_next()
            return
        QTimer.singleShot(80, self._poll_initialization)

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

    def _mint_identifier(self, identifier: str, callback) -> None:
        request_id = uuid.uuid4().hex
        script = f"harmoniaGenerate({json.dumps(identifier)}, {json.dumps(request_id)}); undefined;"
        self._page.runJavaScript(script)
        self._poll_token(request_id, callback, 0)

    def _poll_token(self, request_id: str, callback, attempt: int) -> None:
        if self._closed or self._active is None:
            return
        expression = (
            "JSON.stringify({token:harmoniaPoState.results["
            + json.dumps(request_id)
            + "]||'',error:harmoniaPoState.resultErrors["
            + json.dumps(request_id)
            + "]||''})"
        )
        self._page.runJavaScript(
            expression,
            lambda value, rid=request_id, cb=callback, n=attempt: self._token_polled(
                rid, cb, n, value
            ),
        )

    def _token_polled(self, request_id: str, callback, attempt: int, value: Any) -> None:
        if self._closed or self._active is None:
            return
        try:
            result = json.loads(str(value or "{}"))
        except (TypeError, json.JSONDecodeError):
            result = {}
        error = str(result.get("error") or "")
        token = str(result.get("token") or "")
        if error:
            self._finish_active(None, error)
            return
        if token:
            self._page.runJavaScript(
                "delete harmoniaPoState.results["
                + json.dumps(request_id)
                + "];delete harmoniaPoState.resultErrors["
                + json.dumps(request_id)
                + "];undefined;"
            )
            callback(token)
            return
        if attempt >= 300:
            self._finish_active(None, "tempo esgotado ao gerar PoToken")
            return
        QTimer.singleShot(
            40,
            lambda rid=request_id, cb=callback, n=attempt + 1: self._poll_token(rid, cb, n),
        )

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
        QTimer.singleShot(0, self._ensure_initialized)

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

    @Slot()
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._fail_all("PoToken provider encerrado")
        self._page.setUrl(QUrl("about:blank"))
        self._page.deleteLater()
        self._profile.deleteLater()
