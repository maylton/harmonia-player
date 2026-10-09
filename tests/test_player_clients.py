import json
import os
import time
from pathlib import Path

import pytest

from harmonia.innertube.player_clients import (
    REFRESH_S,
    PlayerClientCatalog,
    validate,
)
from harmonia.innertube.protocol import PLAYER_CLIENTS

PUBLISHED = Path(__file__).resolve().parents[1] / "data" / "player-clients.json"


def document(*clients):
    return {"schema": 1, "clients": list(clients)}


CLIENT = {"name": "IOS", "id": "5", "version": "21.26.4", "user_agent": "ios-agent"}


def test_the_published_list_is_valid_and_starts_as_the_builtin_profiles():
    published = validate(json.loads(PUBLISHED.read_text(encoding="utf-8")))
    assert published == [dict(profile) for profile in PLAYER_CLIENTS]


@pytest.mark.parametrize(
    "bad",
    [
        {"schema": 2, "clients": [CLIENT]},
        document(),
        document({**CLIENT, "name": "ios; drop"}),
        document({**CLIENT, "id": "five"}),
        document({**CLIENT, "user_agent": ""}),
        document({**CLIENT, "context": {"osName": ["x"]}}),
        document({**CLIENT, "enabled": False}),
    ],
)
def test_anything_unexpected_is_refused(bad):
    with pytest.raises(ValueError):
        validate(bad)


def test_only_known_fields_are_kept():
    (profile,) = validate(
        document({**CLIENT, "authenticated": True, "url": "https://evil", "context": {"a": 1}})
    )
    assert profile == {**CLIENT, "authenticated": True, "context": {"a": 1}}


def test_the_last_client_that_worked_goes_first_and_failing_ones_last():
    catalog = PlayerClientCatalog(cache_file=lambda: Path("missing"), download=None)
    names = lambda: [profile["name"] for profile in catalog.ordered(PLAYER_CLIENTS)]  # noqa: E731
    builtin = [profile["name"] for profile in PLAYER_CLIENTS]
    assert names() == builtin
    catalog.record("IOS", ok=True)
    assert names()[0] == "IOS"
    for _ in range(3):
        catalog.record("VISIONOS", ok=False)
    assert names()[-1] == "VISIONOS"
    catalog.record("VISIONOS", ok=True)  # one success forgives it
    assert names()[0] == "VISIONOS"


def test_the_published_list_is_fetched_once_a_day_and_used(tmp_path):
    cache = tmp_path / "player-clients.json"
    calls = []

    def download(url):
        calls.append(url)
        return json.dumps(document(CLIENT)).encode()

    catalog = PlayerClientCatalog(cache_file=lambda: cache, download=download)
    assert catalog.refresh()
    assert [profile["name"] for profile in catalog.profiles()] == ["IOS"]
    assert len(calls) == 1  # fresh: no new fetch

    # A broken or unreachable list keeps the built-in profiles, and waits a day.
    catalog = PlayerClientCatalog(cache_file=lambda: cache, download=lambda _url: b"{oops")
    cache.unlink()
    assert not catalog.refresh()
    assert cache.exists() and [p["name"] for p in catalog.profiles()] == [
        p["name"] for p in PLAYER_CLIENTS
    ]
    old = time.time() - REFRESH_S - 60
    os.utime(cache, (old, old))
    assert catalog._cached()[1] == pytest.approx(old)
