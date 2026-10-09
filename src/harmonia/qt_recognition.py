"""Music recognition (AudD) in the KDE frontend."""

from __future__ import annotations

from collections.abc import Callable

from .i18n import _
from .qt_integration_context import IntegrationContext, Job
from .recognition import AuddRecognitionProvider, MusicRecognizer, RecognitionTokenStore

DEFAULT_ENDPOINT = "https://api.audd.io/"


class RecognitionBridge:
    def __init__(self, context: IntegrationContext, search: Callable[[str], None]) -> None:
        self.context = context
        self.search = search
        self.tokens = RecognitionTokenStore(context.storage)

    @property
    def values(self):
        return self.context.settings.values

    @property
    def token_configured(self) -> bool:
        return bool(self.tokens.load())

    def set_provider(self, value: str) -> None:
        value = value if value in {"audd", "custom"} else "audd"
        if value != self.values.recognition_provider:
            self.values.recognition_provider = value
            self.context.save_preferences()

    def set_endpoint(self, value: str) -> None:
        value = value.strip() or DEFAULT_ENDPOINT
        if value != self.values.recognition_endpoint:
            self.values.recognition_endpoint = value
            self.context.save_preferences()

    def set_token(self, value: str) -> None:
        value = value.strip()
        if not value:
            return
        self.tokens.save(value)
        self.context.changed()
        self.context.set_status(_("Token do AudD salvo no chaveiro do sistema."))

    def recognize(self) -> None:
        token = self.tokens.load()
        if not token:
            self.context.set_status(_("Configure o token do AudD primeiro."))
            return
        endpoint = (
            self.values.recognition_endpoint
            if self.values.recognition_provider == "custom"
            else None
        )
        recognizer = MusicRecognizer(AuddRecognitionProvider(token, endpoint=endpoint))
        self.context.set_status(_("Ouvindo por 12 segundos…"))
        self.context.run(
            Job("recognition", self._recognized, None, _("Não foi possível reconhecer a música")),
            recognizer.recognize,
        )

    def _recognized(self, result) -> None:
        if result is None:
            self.context.set_status(_("Nenhuma música reconhecida."))
            return
        self.context.set_status(
            _("Encontrada: {title} — {artist}").format(title=result.title, artist=result.artist)
        )
        self.search(f"{result.artist} {result.title}")
