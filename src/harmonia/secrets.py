"""Session storage backed by the desktop keyring.

Linux uses the Secret Service through libsecret; Windows uses the Credential
Manager through an object that mimics the same libsecret calls.
"""

from __future__ import annotations

import logging
import os
import threading

from . import host

LOGGER = logging.getLogger(__name__)


def keyring_backend(schema_name: str, attribute_names: tuple[str, ...]):
    """Return the (api, schema) pair used by the password_*_sync calls."""
    if host.IS_WINDOWS:
        from .wincred import CredentialManager

        return CredentialManager(), schema_name
    import gi

    gi.require_version("Secret", "1")
    from gi.repository import Secret

    schema = Secret.Schema.new(
        schema_name,
        Secret.SchemaFlags.NONE,
        {name: Secret.SchemaAttributeType.STRING for name in attribute_names},
    )
    return Secret, schema


class SessionSecret:
    SCHEMA = "io.github.harmonia.Harmonia.Session"
    ATTRIBUTE_NAMES: tuple[str, ...] = ("application",)
    label = "Sessão do YouTube Music — Harmonia"

    def __init__(self) -> None:
        self.available = False
        self._secret = None
        self._schema = None
        if os.environ.get("HARMONIA_DISABLE_SECRET_SERVICE") == "1":
            return
        try:
            self._secret, self._schema = keyring_backend(self.SCHEMA, self.ATTRIBUTE_NAMES)
            self.available = True
        except (ImportError, ValueError, OSError):
            LOGGER.debug(
                "Secret Service indisponível (%s); usando armazenamento local", self.SCHEMA
            )

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
                    self.label,
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

    SCHEMA = "io.github.harmonia.Harmonia.Credential"
    ATTRIBUTE_NAMES = ("application", "service")

    def __init__(self, service: str, label: str) -> None:
        self.service = service
        self.label = label
        super().__init__()

    @property
    def attributes(self) -> dict[str, str]:
        return {"application": "harmonia", "service": self.service}
