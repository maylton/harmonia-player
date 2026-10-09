"""A backup of the library before a new version of Harmonia first opens it.

A new version may migrate the database (new tables and columns), and opening
Storage runs those migrations, so the database file is backed up before
that, while it is still as the previous version left it. If something goes
wrong, the backup can be restored from Preferences > Dados e backup. Only
the newest few are kept, in the cache folder next to the database.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from . import __version__
from .backup import export_database
from .storage import Storage

LOGGER = logging.getLogger(__name__)
KEEP = 3
VERSION_SETTING = "last_run_version"
PREFIX = "harmonia-antes-de-"


def open_storage(version: str = __version__) -> Storage:
    """Storage for the app, with the database backed up first if the version changed."""
    backup_before_upgrade(Storage.default_database_file(), version)
    storage = Storage()
    storage.set_setting(VERSION_SETTING, version)
    return storage


def backup_before_upgrade(database_file: Path, version: str) -> Path | None:
    """Back ``database_file`` up when another version last ran on it and it has data.

    Never raises: a failed backup must not keep Harmonia from opening.
    """
    try:
        previous, has_data = _inspect(database_file)
        if previous == version or not has_data:
            return None
        stamp = time.strftime("%Y%m%d-%H%M%S")
        folder = database_file.parent / "backups"
        target = export_database(database_file, folder / f"{PREFIX}{_safe(version)}-{stamp}.zip")
        prune(folder, KEEP)
        return target
    except Exception:
        LOGGER.warning("Não foi possível fazer o backup antes da atualização", exc_info=True)
        return None


def _inspect(database_file: Path) -> tuple[str, bool]:
    """The version that last ran, and whether there is a library or history to protect."""
    if not database_file.is_file():
        return "", False
    with closing(sqlite3.connect(f"file:{database_file}?mode=ro", uri=True)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        previous = ""
        if "settings" in tables:
            row = db.execute(
                "SELECT value FROM settings WHERE key = ?", (VERSION_SETTING,)
            ).fetchone()
            previous = row[0] if row else ""
        has_data = any(
            db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
            for table in ("library_items", "play_history", "local_playlists")
            if table in tables
        )
    return previous, has_data


def prune(folder: Path, keep: int) -> None:
    backups = sorted(folder.glob(f"{PREFIX}*.zip"), key=lambda path: path.stat().st_mtime)
    for old in backups[:-keep] if keep else backups:
        old.unlink(missing_ok=True)


def _safe(version: str) -> str:
    return re.sub(r"[^\w.-]", "_", version)
