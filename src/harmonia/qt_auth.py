from __future__ import annotations

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtWebEngineQuick import QQuickWebEngineProfile

LOGIN_URL = (
    "https://accounts.google.com/ServiceLogin?"
    "continue=https%3A%2F%2Fmusic.youtube.com"
)
_REQUIRED_SESSION_COOKIES = {"SAPISID", "__Secure-3PAPISID"}


class QtAuthController(QObject):
    """Capture a YouTube Music session from the Qt WebEngine login view."""

    cookieReady = Signal(str)
    activeChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._active = False
        self._current_url = ""
        self._cookies: dict[str, str] = {}
        self._completion_pending = False

        # WebEngineView instances without an explicit profile use this same
        # default profile. It is off-the-record, which is desirable here: the
        # browser session only exists long enough to extract the YouTube cookie;
        # Harmonia persists that cookie through its existing Secret Service
        # storage instead of keeping a second browser credential store.
        self._profile = QQuickWebEngineProfile.defaultProfile()
        self._cookie_store = self._profile.cookieStore()
        self._cookie_store.cookieAdded.connect(self._cookie_added)
        self._cookie_store.cookieRemoved.connect(self._cookie_removed)

    @Property(str, constant=True)
    def loginUrl(self) -> str:
        return LOGIN_URL

    @Property(bool, notify=activeChanged)
    def active(self) -> bool:
        return self._active

    @Slot()
    def beginLogin(self) -> None:
        self._cookies.clear()
        self._current_url = ""
        self._completion_pending = False
        if not self._active:
            self._active = True
            self.activeChanged.emit()

        # Seed the in-memory jar in case WebEngine already has a valid Google /
        # YouTube session from an earlier attempt in the same application run.
        self._cookie_store.loadAllCookies()

    @Slot()
    def cancelLogin(self) -> None:
        self._current_url = ""
        self._completion_pending = False
        if self._active:
            self._active = False
            self.activeChanged.emit()

    @Slot(str)
    def navigationChanged(self, url: str) -> None:
        if not self._active:
            return
        self._current_url = (url or "").strip()
        if self._is_youtube_music_url(self._current_url):
            # loadAllCookies() re-emits the complete cookie jar through
            # cookieAdded. A short single-shot lets the final navigation's
            # cookies arrive before we serialize them for the shared backend.
            self._cookie_store.loadAllCookies()
            self._schedule_completion(350)

    def _cookie_added(self, cookie) -> None:
        if not self._active or not self._is_youtube_cookie(cookie):
            return
        name = bytes(cookie.name()).decode("utf-8", errors="replace")
        value = bytes(cookie.value()).decode("utf-8", errors="replace")
        if not name:
            return
        self._cookies[name] = value
        if self._is_youtube_music_url(self._current_url) and name in _REQUIRED_SESSION_COOKIES:
            self._schedule_completion(120)

    def _cookie_removed(self, cookie) -> None:
        if not self._is_youtube_cookie(cookie):
            return
        name = bytes(cookie.name()).decode("utf-8", errors="replace")
        self._cookies.pop(name, None)

    def _schedule_completion(self, delay_ms: int) -> None:
        if self._completion_pending:
            return
        self._completion_pending = True
        QTimer.singleShot(delay_ms, self._complete_if_ready)

    def _complete_if_ready(self) -> None:
        self._completion_pending = False
        if not self._active or not self._is_youtube_music_url(self._current_url):
            return
        if not _REQUIRED_SESSION_COOKIES.intersection(self._cookies):
            return

        raw_cookie = "; ".join(
            f"{name}={value}" for name, value in sorted(self._cookies.items()) if value
        )
        if not raw_cookie:
            return

        self._active = False
        self.activeChanged.emit()
        self.cookieReady.emit(raw_cookie)

    @staticmethod
    def _is_youtube_music_url(url: str) -> bool:
        lowered = url.lower()
        return lowered.startswith("https://music.youtube.com")

    @staticmethod
    def _is_youtube_cookie(cookie) -> bool:
        domain = str(cookie.domain() or "").lstrip(".").lower()
        return domain == "youtube.com" or domain.endswith(".youtube.com")
