"""Session storage backed by the desktop Secret Service."""

from __future__ import annotations

import logging
import os
import threading

LOGGER = logging.getLogger(__name__)


class SessionSecret:
    def __init__(self) -> None:
        self.available = False
        self._secret = None
        self._schema = None
        if os.environ.get("HARMONIA_DISABLE_SECRET_SERVICE") == "1":
            return
        try:
            import gi

            gi.require_version("Secret", "1")
            from gi.repository import Secret

            self._secret = Secret
            self._schema = Secret.Schema.new(
                "io.github.harmonia.Harmonia.Session",
                Secret.SchemaFlags.NONE,
                {"application": Secret.SchemaAttributeType.STRING},
            )
            self.available = True
        except (ImportError, ValueError):
            LOGGER.debug("Secret Service indisponível; usando armazenamento local restrito")

    @property
    def attributes(self) -> dict[str, str]:
        return {"application": "harmonia"}

    def _bounded(self, operation, default):
        """Run libsecret without ever blocking GTK startup indefinitely."""
        completed = threading.Event()
        result = {"value": default}

        def worker() -> None:
            try:
                result["value"] = operation()
            except Exception:
                result["value"] = default
            finally:
                completed.set()

        threading.Thread(target=worker, daemon=True, name="harmonia-secret-service").start()
        if not completed.wait(2.0):
            # A locked or unhealthy keyring must not hold the application window.
            self.available = False
            return default
        return result["value"]

    def lookup(self) -> str:
        if not self.available:
            return ""
        return self._bounded(
            lambda: self._secret.password_lookup_sync(self._schema, self.attributes, None) or "", ""
        )

    def store(self, value: str) -> bool:
        if not self.available or not value:
            return False
        return bool(
            self._bounded(
                lambda: self._secret.password_store_sync(
                    self._schema,
                    self.attributes,
                    self._secret.COLLECTION_DEFAULT,
                    "Sessão do YouTube Music — Harmonia",
                    value,
                    None,
                ),
                False,
            )
        )

    def clear(self) -> bool:
        if not self.available:
            return False
        return bool(
            self._bounded(
                lambda: self._secret.password_clear_sync(self._schema, self.attributes, None),
                False,
            )
        )


class NamedSecret(SessionSecret):
    """A Secret Service entry isolated by service name."""

    def __init__(self, service: str, label: str) -> None:
        self.service = service
        self.label = label
        self.available = False
        self._secret = None
        self._schema = None
        if os.environ.get("HARMONIA_DISABLE_SECRET_SERVICE") == "1":
            return
        try:
            import gi

            gi.require_version("Secret", "1")
            from gi.repository import Secret

            self._secret = Secret
            self._schema = Secret.Schema.new(
                "io.github.harmonia.Harmonia.Credential",
                Secret.SchemaFlags.NONE,
                {
                    "application": Secret.SchemaAttributeType.STRING,
                    "service": Secret.SchemaAttributeType.STRING,
                },
            )
            self.available = True
        except (ImportError, ValueError):
            LOGGER.debug("Secret Service indisponível para %s", service)

    @property
    def attributes(self) -> dict[str, str]:
        return {"application": "harmonia", "service": self.service}

    def store(self, value: str) -> bool:
        if not self.available or not value:
            return False
        return bool(
            self._bounded(
                lambda: self._secret.password_store_sync(
                    self._schema,
                    self.attributes,
                    self._secret.COLLECTION_DEFAULT,
                    self.label,
                    value,
                    None,
                ),
                False,
            )
        )
