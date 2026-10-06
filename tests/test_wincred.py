import uuid
from types import SimpleNamespace

import pytest

from harmonia import host, secrets, wincred


class MemoryCredentials(wincred.CredentialManager):
    """CredentialManager with the advapi32 calls replaced by a dictionary."""

    def __init__(self):
        function = SimpleNamespace
        super().__init__(
            SimpleNamespace(
                CredReadW=function(),
                CredWriteW=function(),
                CredDeleteW=function(),
                CredFree=function(),
            )
        )
        self.items: dict[str, tuple[str, bytes]] = {}

    def _read(self, target):
        return self.items[target][1] if target in self.items else None

    def _write(self, target, comment, blob):
        assert len(blob) <= wincred.CRED_MAX_BLOB_SIZE
        self.items[target] = (comment, blob)

    def _delete(self, target):
        return self.items.pop(target, None) is not None


def test_target_names_isolate_each_service():
    assert wincred.target_name(
        "io.github.harmonia.Harmonia.Session", {"application": "harmonia"}
    ) == ("io.github.harmonia.Harmonia.Session")
    assert (
        wincred.target_name(
            "io.github.harmonia.Harmonia.Credential",
            {"application": "harmonia", "service": "lastfm"},
        )
        == "io.github.harmonia.Harmonia.Credential/lastfm"
    )


def test_long_values_are_split_and_stale_chunks_removed():
    store = MemoryCredentials()
    attributes = {"application": "harmonia"}
    cookie = "SAPISID=" + "x" * 6000 + "; ação"

    assert store.password_store_sync("schema", attributes, None, "Sessão", cookie, None)
    assert sorted(store.items) == ["schema", "schema#1", "schema#2"]
    assert store.password_lookup_sync("schema", attributes, None) == cookie

    assert store.password_store_sync("schema", attributes, None, "Sessão", "SAPISID=short", None)
    assert sorted(store.items) == ["schema"]
    assert store.password_lookup_sync("schema", attributes, None) == "SAPISID=short"

    assert store.password_clear_sync("schema", attributes, None) is True
    assert store.items == {}
    assert store.password_lookup_sync("schema", attributes, None) is None


def test_windows_secrets_use_the_credential_manager(monkeypatch):
    memory = MemoryCredentials()
    monkeypatch.setattr(host, "IS_WINDOWS", True)
    monkeypatch.setattr(wincred, "CredentialManager", lambda: memory)
    monkeypatch.delenv("HARMONIA_DISABLE_SECRET_SERVICE", raising=False)

    session = secrets.SessionSecret()
    lastfm = secrets.NamedSecret("lastfm", "Conta Last.fm — Harmonia")
    assert session.available and lastfm.available
    assert session.store("SAPISID=abc")
    assert lastfm.store('{"session_key": "k"}')

    assert session.lookup() == "SAPISID=abc"
    assert memory.items["io.github.harmonia.Harmonia.Credential/lastfm"][0] == (
        "Conta Last.fm — Harmonia"
    )
    assert session.clear()
    assert session.lookup() == ""
    assert lastfm.lookup() == '{"session_key": "k"}'


@pytest.mark.skipif(not host.IS_WINDOWS, reason="usa o Gerenciador de Credenciais real")
def test_real_credential_manager_roundtrip():
    store = wincred.CredentialManager()
    schema = f"io.github.harmonia.Harmonia.Test.{uuid.uuid4().hex}"
    attributes = {"application": "harmonia"}
    value = "SAPISID=" + "y" * 5000
    try:
        assert store.password_store_sync(schema, attributes, None, "Teste", value, None)
        assert store.password_lookup_sync(schema, attributes, None) == value
    finally:
        store.password_clear_sync(schema, attributes, None)
    assert store.password_lookup_sync(schema, attributes, None) is None
