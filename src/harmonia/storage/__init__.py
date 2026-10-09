"""Harmonia's local storage: the SQLite caches, settings and the session cookie.

Storage gathers one repository per domain (catalog, lyrics, playback,
downloads, local media) over the same database.
"""

from __future__ import annotations

from .. import host
from ..secrets import SessionSecret
from .catalog import CatalogCache
from .downloads import DownloadRecords
from .local import LocalMedia
from .loudness import LoudnessRecords
from .lyrics import LyricsCache
from .playback import PlaybackRecords


class Storage(
    CatalogCache, LyricsCache, PlaybackRecords, DownloadRecords, LocalMedia, LoudnessRecords
):
    def __init__(self) -> None:
        config = host.config_dir()
        cache = host.cache_dir()
        config.mkdir(parents=True, exist_ok=True)
        cache.mkdir(parents=True, exist_ok=True)
        self.cookie_file = config / "session"
        self.library_file = cache / "library.json"
        self.database_file = cache / "library.db"
        self.artwork_dir = cache / "artwork"
        self.artwork_dir.mkdir(exist_ok=True)
        self.downloads_dir = cache / "downloads"
        self.downloads_dir.mkdir(exist_ok=True)
        self.web_data_dir = config / "web-auth"
        self.session_secret = SessionSecret()
        self._initialize_database()
        self._initialize_loudness()
        self._migrate_json_cache()

    def load_cookie(self) -> str:
        secret = self.session_secret.lookup()
        if secret:
            return secret
        try:
            legacy = self.cookie_file.read_text().strip()
            if legacy and self.session_secret.store(legacy):
                self.cookie_file.unlink(missing_ok=True)
            return legacy
        except OSError:
            return ""

    def save_cookie(self, value: str) -> None:
        value = value.strip()
        if self.session_secret.store(value):
            self.cookie_file.unlink(missing_ok=True)
            return
        self.cookie_file.write_text(value)
        self.cookie_file.chmod(0o600)

    def clear_cookie(self) -> None:
        self.session_secret.clear()
        self.cookie_file.unlink(missing_ok=True)

    def get_setting(self, key: str, default: str = "") -> str:
        with self._connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO settings(key,value) VALUES(?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (key, value),
            )
