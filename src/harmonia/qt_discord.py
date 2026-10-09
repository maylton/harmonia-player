"""Discord Rich Presence in the KDE frontend."""

from __future__ import annotations

import logging

from .qt_integration_context import IntegrationContext, Job
from .social import DiscordPresence

LOGGER = logging.getLogger(__name__)


class DiscordBridge:
    def __init__(self, context: IntegrationContext) -> None:
        self.context = context
        self.presence: DiscordPresence | None = None
        self._config: tuple[bool, str] | None = None

    @property
    def values(self):
        return self.context.settings.values

    def set_enabled(self, enabled: bool) -> bool:
        """True when the setting changed."""
        enabled = bool(enabled)
        if enabled == self.values.discord_enabled:
            return False
        self.values.discord_enabled = enabled
        self.context.save_preferences()
        self.configure()
        return True

    def set_client_id(self, value: str) -> bool:
        value = value.strip()
        if value == self.values.discord_client_id:
            return False
        self.values.discord_client_id = value
        self.context.save_preferences()
        self.configure()
        return True

    def configure(self) -> None:
        """Open or close the presence to match the preferences."""
        config = (bool(self.values.discord_enabled), self.values.discord_client_id.strip())
        if config == self._config:
            return
        self._config = config
        self.close()
        self.presence = DiscordPresence(config[1]) if config[0] and config[1] else None

    def update(self, item, playing: bool, started_at: int) -> None:
        presence = self.presence
        if presence is not None and item is not None:
            self.context.run(
                Job("discord-presence"), lambda: presence.update(item, playing, started_at)
            )

    def clear(self) -> None:
        if self.presence is not None:
            self.context.run(Job("discord-clear"), self.presence.clear)

    def close(self) -> None:
        presence, self.presence = self.presence, None
        if presence is None:
            return
        try:
            presence.clear()
            presence.close()
        except OSError:
            LOGGER.debug("Não foi possível encerrar o Discord Rich Presence", exc_info=True)
