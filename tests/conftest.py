import os

import pytest

# Automated tests must never read or prompt for a developer's desktop keyring.
os.environ["HARMONIA_DISABLE_SECRET_SERVICE"] = "1"


@pytest.fixture(autouse=True)
def isolated_player_clients(monkeypatch, tmp_path):
    """No published client list from the network, and no health from other tests."""
    from harmonia.innertube.player_clients import CATALOG

    def offline(_url):
        raise OSError("tests do not fetch the published client list")

    monkeypatch.setattr(CATALOG, "_download", offline)
    monkeypatch.setattr(CATALOG, "_cache_file", lambda: tmp_path / "player-clients.json")
    monkeypatch.setattr(CATALOG, "_health", {})
    monkeypatch.setattr(CATALOG, "_last_success", None)
