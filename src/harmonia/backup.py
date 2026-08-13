from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path

BACKUP_FORMAT = 1
REQUIRED_TABLES = {"library_items", "settings", "play_history", "local_playlists"}


class BackupError(ValueError):
    pass


class BackupManager:
    def __init__(self, storage) -> None:
        self.storage = storage

    def export_to(self, destination: Path) -> Path:
        destination = destination.expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="harmonia-backup-") as temporary:
            database = Path(temporary) / "library.db"
            with self.storage._connect() as source, sqlite3.connect(database) as target:
                source.backup(target)
            manifest = {
                "format": BACKUP_FORMAT,
                "created_at": int(time.time()),
                "application": "Harmonia",
                "contains_credentials": False,
                "contains_media": False,
            }
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, indent=2))
                archive.write(database, "library.db")
        return destination

    def restore_from(self, source: Path) -> Path:
        source = source.expanduser()
        try:
            with zipfile.ZipFile(source) as archive:
                names = set(archive.namelist())
                if not {"manifest.json", "library.db"} <= names:
                    raise BackupError("O arquivo não é um backup completo do Harmonia")
                manifest = json.loads(archive.read("manifest.json"))
                if manifest.get("format") != BACKUP_FORMAT:
                    raise BackupError("A versão deste backup não é compatível")
                with tempfile.TemporaryDirectory(prefix="harmonia-restore-") as temporary:
                    restored = Path(temporary) / "library.db"
                    restored.write_bytes(archive.read("library.db"))
                    self._validate_database(restored)
                    previous = self.storage.database_file.with_suffix(".db.before-restore")
                    if self.storage.database_file.exists():
                        shutil.copy2(self.storage.database_file, previous)
                    shutil.copy2(restored, self.storage.database_file)
        except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            raise BackupError("Não foi possível ler o backup do Harmonia") from exc
        self.storage._initialize_database()
        return self.storage.database_file

    @staticmethod
    def _validate_database(path: Path) -> None:
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as database:
                if database.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise BackupError("O banco de dados do backup está corrompido")
                tables = {
                    row[0]
                    for row in database.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                if not tables >= REQUIRED_TABLES:
                    raise BackupError("O backup não contém as tabelas obrigatórias")
        except sqlite3.DatabaseError as exc:
            raise BackupError("O banco de dados do backup é inválido") from exc
