import os
import sqlite3
import time
import zipfile
from contextlib import closing

from harmonia import auto_backup
from harmonia.models import LibraryItem


def isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


def backups(storage):
    return sorted((storage.database_file.parent / "backups").glob("*.zip"))


def test_no_backup_on_a_first_run_or_the_same_version(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    storage = auto_backup.open_storage("1.0")
    assert backups(storage) == []  # nothing to protect yet
    storage.save_library({"songs": [LibraryItem("v", "Faixa", kind="songs")]})
    auto_backup.open_storage("1.0")
    assert backups(storage) == []
    assert storage.get_setting(auto_backup.VERSION_SETTING) == "1.0"


def test_a_new_version_backs_up_the_database_as_the_old_one_left_it(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    storage = auto_backup.open_storage("1.0")
    storage.save_library({"songs": [LibraryItem("v", "Faixa", kind="songs")]})
    upgraded = auto_backup.open_storage("2.0 beta")
    (backup,) = backups(upgraded)
    assert backup.name.startswith("harmonia-antes-de-2.0_beta-")
    with zipfile.ZipFile(backup) as archive:
        archive.extract("library.db", tmp_path / "restored")
    with closing(sqlite3.connect(tmp_path / "restored" / "library.db")) as db:
        version = db.execute("SELECT value FROM settings WHERE key = ?", ("last_run_version",))
        assert version.fetchone()[0] == "1.0"  # taken before the new version opened it
        assert db.execute("SELECT item_id FROM library_items").fetchall() == [("v",)]
    assert upgraded.get_setting(auto_backup.VERSION_SETTING) == "2.0 beta"


def test_only_the_newest_backups_are_kept(tmp_path):
    for index in range(5):
        old = tmp_path / f"{auto_backup.PREFIX}{index}.zip"
        old.write_bytes(b"zip")
        os.utime(old, (time.time() + index, time.time() + index))
    (tmp_path / "other.zip").write_bytes(b"mine")
    auto_backup.prune(tmp_path, 3)
    names = sorted(path.name for path in tmp_path.iterdir())
    assert names == [f"{auto_backup.PREFIX}{index}.zip" for index in (2, 3, 4)] + ["other.zip"]


def test_a_failed_backup_does_not_stop_harmonia(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    storage = auto_backup.open_storage("1.0")
    storage.save_library({"songs": [LibraryItem("v", "Faixa", kind="songs")]})

    def broken(*_args):
        raise OSError("disco cheio")

    monkeypatch.setattr(auto_backup, "export_database", broken)
    assert auto_backup.open_storage("2.0").get_setting(auto_backup.VERSION_SETTING) == "2.0"


def test_restoring_an_old_backup_recreates_the_newer_tables(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    from harmonia.backup import BackupManager

    storage = auto_backup.open_storage("1.0")
    storage.save_library({"songs": [LibraryItem("v", "Faixa", kind="songs")]})
    archive = BackupManager(storage).export_to(tmp_path / "backup.zip")
    with zipfile.ZipFile(archive) as backup:
        backup.extract("library.db", tmp_path / "old")
    # As a backup from before the equalizer profiles existed.
    with closing(sqlite3.connect(tmp_path / "old" / "library.db")) as db:
        db.execute("DROP TABLE eq_profiles")
        db.commit()
    with zipfile.ZipFile(tmp_path / "old.zip", "w") as old:
        old.writestr("manifest.json", zipfile.ZipFile(archive).read("manifest.json"))
        old.write(tmp_path / "old" / "library.db", "library.db")
    BackupManager(storage).restore_from(tmp_path / "old.zip")
    assert storage.eq_profiles() == {}
