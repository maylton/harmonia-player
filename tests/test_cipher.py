from __future__ import annotations

import json
import urllib.parse

import pytest

from harmonia.cipher import YouTubeCipherService
from harmonia.cipher_config import extract_player_hash, parse_cipher_configs


class DummyClient:
    pass


class DummySolver:
    def solve_signature(self, value: str) -> str:
        return f"sig-{value}"

    def solve_n(self, value: str) -> str:
        return f"n-{value}"


def test_cipher_config_parses_aliases_and_player_hash():
    raw = json.dumps(
        {
            "schemaVersion": 1,
            "players": {
                "1234abcd": {
                    "sig": "Ab(1,2,INPUT)",
                    "nClass": "Nc",
                    "sts": 20640,
                    "aliases": ["abcd1234"],
                }
            },
        }
    )
    configs = parse_cipher_configs(raw)

    assert configs["1234abcd"] == configs["abcd1234"]
    assert configs["1234abcd"].signature_timestamp == 20640
    assert extract_player_hash(
        "https://www.youtube.com/s/player/1234abcd/player_ias.vflset/en_US/base.js"
    ) == "1234abcd"


def test_cipher_config_rejects_duplicate_aliases():
    raw = json.dumps(
        {
            "schemaVersion": 1,
            "players": {
                "1234abcd": {
                    "sig": "Ab(1,2,INPUT)",
                    "nClass": "Nc",
                    "sts": 20640,
                    "aliases": ["abcd1234"],
                },
                "abcd1234": {
                    "sig": "Cd(3,4,INPUT)",
                    "nClass": "Nd",
                    "sts": 20641,
                },
            },
        }
    )

    with pytest.raises(ValueError, match="duplicate cipher player hash/alias"):
        parse_cipher_configs(raw)


def test_cipher_service_applies_signature_and_n_transform(monkeypatch):
    service = YouTubeCipherService(DummyClient())
    monkeypatch.setattr(
        service,
        "_solver",
        lambda *_args, **_kwargs: (DummySolver(), None),
    )
    cipher_url = "https://r1.googlevideo.com/videoplayback?foo=1&n=original"
    cipher = urllib.parse.urlencode(
        {
            "url": cipher_url,
            "sp": "sig",
            "s": "encrypted",
        }
    )

    result = service.resolve_format_url(
        {"signatureCipher": cipher},
        "video-id",
    )

    assert result is not None
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(result.url).query)
    assert query["sig"] == ["sig-encrypted"]
    assert query["n"] == ["n-original"]
    assert result.transformed_signature is True
    assert result.transformed_n is True
