from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

import pytest

from harmonia.backup import BackupError, BackupManager
from harmonia.models import LibraryItem
from harmonia.storage import Storage


def storage_at(monkeypatch, root: Path) -> Storage:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(root / "cache"))
    return Storage()


def test_playback_insights_rank_tracks_artists_and_months(monkeypatch, tmp_path):
    storage = storage_at(monkeypatch, tmp_path)
    first = LibraryItem("one", "Primeira", "Artista A • Álbum", kind="songs")
    second = LibraryItem("two", "Segunda", "Artista B", kind="songs")
    storage.record_history(first, 60_000)
    storage.record_history(first, 90_000)
    storage.record_history(second, 30_000)

    insights = storage.playback_insights(time.localtime().tm_year)

    assert insights.total_plays == 3
    assert insights.unique_tracks == 2
    assert insights.listened_minutes == 3
    assert insights.top_tracks[0].item.id == "one"
    assert insights.top_tracks[0].plays == 2
    assert insights.top_artists[0].name == "Artista A"
    assert sum(insights.monthly_plays) == 3


def test_backup_roundtrip_excludes_credentials_and_media(monkeypatch, tmp_path):
    source = storage_at(monkeypatch, tmp_path / "source")
    source.set_setting("language", "en-US")
    source.save_library({"songs": [LibraryItem("song", "Faixa", kind="songs")]})
    source.record_history(LibraryItem("song", "Faixa", kind="songs"), 45_000)
    archive = BackupManager(source).export_to(tmp_path / "harmonia.harmonia-backup")

    with zipfile.ZipFile(archive) as backup:
        assert set(backup.namelist()) == {"manifest.json", "library.db"}
        manifest = json.loads(backup.read("manifest.json"))
        assert manifest["contains_credentials"] is False
        assert manifest["contains_media"] is False

    target = storage_at(monkeypatch, tmp_path / "target")
    target.set_setting("language", "pt-BR")
    BackupManager(target).restore_from(archive)

    assert target.get_setting("language") == "en-US"
    assert target.load_library()["songs"][0].id == "song"
    assert target.load_history()[0].position_ms == 45_000


def test_backup_rejects_unknown_format(monkeypatch, tmp_path):
    storage = storage_at(monkeypatch, tmp_path / "storage")
    archive = tmp_path / "invalid.harmonia-backup"
    with zipfile.ZipFile(archive, "w") as backup:
        backup.writestr("manifest.json", json.dumps({"format": 99}))
        backup.writestr("library.db", b"invalid")

    with pytest.raises(BackupError, match="versão"):
        BackupManager(storage).restore_from(archive)
