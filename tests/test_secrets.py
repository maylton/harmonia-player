from harmonia.secrets import NamedSecret, SessionSecret


class FakeSecretAPI:
    COLLECTION_DEFAULT = "default"

    def __init__(self):
        self.value = ""

    def password_lookup_sync(self, _schema, _attributes, _cancellable):
        return self.value

    def password_store_sync(self, _schema, _attributes, _collection, _label, value, _cancellable):
        self.value = value
        return True

    def password_clear_sync(self, _schema, _attributes, _cancellable):
        self.value = ""
        return True


def test_secret_service_wrapper_store_lookup_and_clear():
    secret = SessionSecret.__new__(SessionSecret)
    secret.available = True
    secret._schema = object()
    secret._secret = FakeSecretAPI()
    assert secret.store("SAPISID=secret") is True
    assert secret.lookup() == "SAPISID=secret"
    assert secret.clear() is True
    assert secret.lookup() == ""


def test_named_secret_uses_isolated_attributes_and_label():
    secret = NamedSecret.__new__(NamedSecret)
    secret.available = True
    secret._schema = object()
    secret._secret = FakeSecretAPI()
    secret.service = "lastfm"
    secret.label = "Last.fm"

    assert secret.attributes == {"application": "harmonia", "service": "lastfm"}
    assert secret.store("session") is True
    assert secret.lookup() == "session"


def test_storage_migrates_legacy_cookie_to_secret(monkeypatch, tmp_path):
    from harmonia import storage as storage_module

    backend = FakeSecretAPI()

    class FakeSessionSecret:
        def lookup(self):
            return backend.value

        def store(self, value):
            backend.value = value
            return True

        def clear(self):
            backend.value = ""
            return True

    monkeypatch.setattr(storage_module, "SessionSecret", FakeSessionSecret)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    storage = storage_module.Storage()
    storage.cookie_file.write_text("SAPISID=legacy")
    assert storage.load_cookie() == "SAPISID=legacy"
    assert backend.value == "SAPISID=legacy"
    assert not storage.cookie_file.exists()
