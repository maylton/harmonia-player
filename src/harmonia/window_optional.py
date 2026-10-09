"""Optional services: their state, music recognition, background work and shutdown.

Listen Together lives in window_together.py and casting in window_cast.py.
"""

from __future__ import annotations

import logging
import threading

import gi

gi.require_version("Adw", "1")
from gi.repository import Adw, GLib

from .cast import CastMediaHost
from .i18n import _
from .recognition import AuddRecognitionProvider, MusicRecognizer, RecognitionTokenStore

LOGGER = logging.getLogger(__name__)


class WindowOptionalMixin:
    def _initialize_optional_services(self) -> None:
        self.recognition_tokens = RecognitionTokenStore(self.storage)
        self.together_host = None
        self.together_client = None
        self._together_share_url = ""
        self._together_fetching = False
        self._together_revision = -1
        self._together_pending_state = None
        self._together_applying = False
        self.cast_renderer = None
        self.cast_device = None
        self._cast_playing = False
        self._cast_position_ms = 0
        self._cast_started = 0.0
        self._current_stream_url = ""
        self.cast_media = CastMediaHost()
        self._shutdown_started = False
        self._optional_tick_source = GLib.timeout_add_seconds(1, self._optional_tick)

    def _recognize_music(self) -> None:
        token = self.recognition_tokens.load()
        if not token:
            self.toast_overlay.add_toast(Adw.Toast(title=_("Configure o token do AudD primeiro")))
            return
        self.toast_overlay.add_toast(Adw.Toast(title=_("Ouvindo por 12 segundos…"), timeout=4))
        endpoint = (
            self.preferences.recognition_endpoint
            if self.preferences.recognition_provider == "custom"
            else None
        )
        recognizer = MusicRecognizer(AuddRecognitionProvider(token, endpoint=endpoint))

        def completed(result, error):
            if error:
                self.toast_overlay.add_toast(
                    Adw.Toast(
                        title=_("Não foi possível reconhecer a música: {error}").format(error=error)
                    )
                )
            elif result is None:
                self.toast_overlay.add_toast(Adw.Toast(title=_("Nenhuma música reconhecida")))
            else:
                self.toast_overlay.add_toast(
                    Adw.Toast(
                        title=_("Encontrada: {title} — {artist}").format(
                            title=result.title, artist=result.artist
                        ),
                        timeout=6,
                    )
                )
                self.search_entry.set_text(f"{result.artist} {result.title}")
                self.search(self.search_entry.get_text())
            return False

        self._optional_worker("recognition", recognizer.recognize, completed)

    def _optional_worker(self, name: str, operation, completed=None) -> None:
        def worker():
            try:
                result, error = operation(), None
            except Exception as exc:
                LOGGER.debug("Falha no recurso opcional %s", name, exc_info=True)
                result, error = None, str(exc)
            if completed:
                GLib.idle_add(completed, result, error)

        threading.Thread(target=worker, daemon=True, name=f"optional-{name}").start()

    def _close_optional_services(self, *_args) -> bool:
        self._leave_together_session(refresh=False)
        self._optional_stop()
        return False

    def _shutdown_application(self, *_args) -> bool:
        if self._shutdown_started:
            return False
        self._shutdown_started = True
        if self._optional_tick_source:
            GLib.source_remove(self._optional_tick_source)
            self._optional_tick_source = 0
        self._close_optional_services()
        self._close_social_integrations()
        self.mpris.close()
        self.player.close()
        application = self.get_application()
        if application:
            GLib.idle_add(self._quit_after_close, application)
        return False

    @staticmethod
    def _quit_after_close(application) -> bool:
        application.quit()
        return GLib.SOURCE_REMOVE
