from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
from pathlib import Path

from .insights import (
    PlaybackInsights,
    RankedArtist,
    RankedMedia,
    artist_from_subtitle,
    current_year,
)
from .models import (
    DownloadRecord,
    ExploreData,
    ExploreDestination,
    HistoryEntry,
    HomeSection,
    LibraryItem,
    LocalPlaylist,
    LyricLine,
    LyricsDocument,
    PlaybackState,
)
from .secrets import SessionSecret

LOGGER = logging.getLogger(__name__)


class Storage:
    def __init__(self) -> None:
        config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "harmonia"
        cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "harmonia"
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
        self._migrate_json_cache()

    def _connect(self):
        connection = sqlite3.connect(self.database_file)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_database(self) -> None:
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS library_items (
                    category TEXT NOT NULL, item_id TEXT NOT NULL, title TEXT NOT NULL,
                    subtitle TEXT NOT NULL DEFAULT '', thumbnail TEXT, kind TEXT NOT NULL,
                    playlist_id TEXT, set_video_id TEXT, position INTEGER NOT NULL,
                    synced_at INTEGER NOT NULL, PRIMARY KEY (category, item_id)
                );
                CREATE TABLE IF NOT EXISTS action_log (
                    id INTEGER PRIMARY KEY, action TEXT NOT NULL, target_id TEXT,
                    status TEXT NOT NULL, error TEXT, created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS library_category_position ON library_items(category, position);
                CREATE TABLE IF NOT EXISTS home_items (
                    section_position INTEGER NOT NULL, section_title TEXT NOT NULL,
                    item_position INTEGER NOT NULL, item_id TEXT NOT NULL, title TEXT NOT NULL,
                    subtitle TEXT NOT NULL DEFAULT '', thumbnail TEXT, kind TEXT NOT NULL,
                    playlist_id TEXT, set_video_id TEXT, synced_at INTEGER NOT NULL,
                    PRIMARY KEY (section_position, item_id)
                );
                CREATE TABLE IF NOT EXISTS lyrics (
                    video_id TEXT PRIMARY KEY, lyrics TEXT NOT NULL,
                    provider TEXT NOT NULL DEFAULT 'YouTube Music', updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS lyrics_documents (
                    video_id TEXT NOT NULL, provider TEXT NOT NULL,
                    plain_lyrics TEXT NOT NULL, synced_lyrics TEXT NOT NULL DEFAULT '[]',
                    translated_lyrics TEXT NOT NULL DEFAULT '',
                    translation_language TEXT NOT NULL DEFAULT '',
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (video_id, provider)
                );
                CREATE TABLE IF NOT EXISTS explore_items (
                    section_position INTEGER NOT NULL, section_title TEXT NOT NULL,
                    item_position INTEGER NOT NULL, item_id TEXT NOT NULL, title TEXT NOT NULL,
                    subtitle TEXT NOT NULL DEFAULT '', thumbnail TEXT, kind TEXT NOT NULL,
                    playlist_id TEXT, set_video_id TEXT, synced_at INTEGER NOT NULL,
                    PRIMARY KEY (section_position, item_id)
                );
                CREATE TABLE IF NOT EXISTS explore_destinations (
                    destination_group TEXT NOT NULL, position INTEGER NOT NULL,
                    title TEXT NOT NULL, browse_id TEXT NOT NULL, params TEXT,
                    synced_at INTEGER NOT NULL,
                    PRIMARY KEY (destination_group, position)
                );
                CREATE TABLE IF NOT EXISTS playback_queue (
                    queue_group TEXT NOT NULL, position INTEGER NOT NULL,
                    item_id TEXT NOT NULL, title TEXT NOT NULL, subtitle TEXT NOT NULL DEFAULT '',
                    thumbnail TEXT, kind TEXT NOT NULL, playlist_id TEXT, set_video_id TEXT,
                    PRIMARY KEY (queue_group, position)
                );
                CREATE TABLE IF NOT EXISTS playback_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1), queue_index INTEGER NOT NULL,
                    position_ms INTEGER NOT NULL, shuffle INTEGER NOT NULL,
                    repeat_mode INTEGER NOT NULL, autoplay INTEGER NOT NULL, updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS play_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT NOT NULL,
                    title TEXT NOT NULL, subtitle TEXT NOT NULL DEFAULT '', thumbnail TEXT,
                    kind TEXT NOT NULL, playlist_id TEXT, set_video_id TEXT,
                    played_at INTEGER NOT NULL, position_ms INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS play_history_played_at ON play_history(played_at DESC);
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS downloads (
                    item_id TEXT PRIMARY KEY, title TEXT NOT NULL, subtitle TEXT NOT NULL DEFAULT '',
                    thumbnail TEXT, kind TEXT NOT NULL, playlist_id TEXT, set_video_id TEXT,
                    status TEXT NOT NULL, file_path TEXT NOT NULL, downloaded_bytes INTEGER NOT NULL,
                    total_bytes INTEGER NOT NULL, account_hash TEXT NOT NULL, error TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS local_media (
                    item_id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
                    subtitle TEXT NOT NULL DEFAULT '', added_at INTEGER NOT NULL, modified_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS local_playlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS local_playlist_items (
                    playlist_id INTEGER NOT NULL, position INTEGER NOT NULL,
                    item_id TEXT NOT NULL, title TEXT NOT NULL, subtitle TEXT NOT NULL DEFAULT '',
                    thumbnail TEXT, kind TEXT NOT NULL, remote_playlist_id TEXT, set_video_id TEXT,
                    PRIMARY KEY (playlist_id, position),
                    FOREIGN KEY (playlist_id) REFERENCES local_playlists(id) ON DELETE CASCADE
                );
            """)
            columns = {
                row[1] for row in db.execute("PRAGMA table_info(lyrics_documents)").fetchall()
            }
            if "translated_lyrics" not in columns:
                db.execute(
                    "ALTER TABLE lyrics_documents ADD COLUMN translated_lyrics TEXT NOT NULL DEFAULT ''"
                )

    def _migrate_json_cache(self) -> None:
        if not self.library_file.exists():
            return
        with self._connect() as db:
            count = db.execute("SELECT count(*) FROM library_items").fetchone()[0]
        if count:
            return
        try:
            data = json.loads(self.library_file.read_text())
            sections = {key: [LibraryItem(**item) for item in items] for key, items in data.items()}
            self.save_library(sections)
            self.library_file.rename(self.library_file.with_suffix(".json.migrated"))
        except (OSError, ValueError, TypeError):
            LOGGER.warning("O cache JSON legado não pôde ser migrado", exc_info=True)

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

    def clear_cache(self) -> int:
        removed = 0
        for directory in (self.artwork_dir,):
            for path in directory.iterdir():
                if path.is_file():
                    removed += path.stat().st_size
                    path.unlink(missing_ok=True)
        return removed

    def save_library(self, sections: dict[str, list[LibraryItem]]) -> None:
        now = int(time.time())
        with self._connect() as db:
            for category, items in sections.items():
                db.execute("DELETE FROM library_items WHERE category = ?", (category,))
                db.executemany(
                    """INSERT INTO library_items
                    (category,item_id,title,subtitle,thumbnail,kind,playlist_id,set_video_id,position,synced_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    [
                        (
                            category,
                            item.id,
                            item.title,
                            item.subtitle,
                            item.thumbnail,
                            item.kind,
                            item.playlist_id,
                            item.set_video_id,
                            position,
                            now,
                        )
                        for position, item in enumerate(items)
                    ],
                )

    def load_library(self) -> dict[str, list[LibraryItem]]:
        result: dict[str, list[LibraryItem]] = {}
        with self._connect() as db:
            rows = db.execute("SELECT * FROM library_items ORDER BY category, position").fetchall()
        for row in rows:
            result.setdefault(row["category"], []).append(
                LibraryItem(
                    row["item_id"],
                    row["title"],
                    row["subtitle"],
                    row["thumbnail"],
                    row["kind"],
                    row["playlist_id"],
                    row["set_video_id"],
                )
            )
        return result

    def log_action(
        self, action: str, target_id: str | None, status: str, error: str | None = None
    ) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO action_log(action,target_id,status,error,created_at) VALUES(?,?,?,?,?)",
                (action, target_id, status, error, int(time.time())),
            )

    def save_home(self, sections: list[HomeSection]) -> None:
        now = int(time.time())
        with self._connect() as db:
            db.execute("DELETE FROM home_items")
            for section_position, section in enumerate(sections):
                db.executemany(
                    """INSERT INTO home_items
                    (section_position,section_title,item_position,item_id,title,subtitle,thumbnail,kind,playlist_id,set_video_id,synced_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    [
                        (
                            section_position,
                            section.title,
                            item_position,
                            item.id,
                            item.title,
                            item.subtitle,
                            item.thumbnail,
                            item.kind,
                            item.playlist_id,
                            item.set_video_id,
                            now,
                        )
                        for item_position, item in enumerate(section.items)
                    ],
                )

    def load_home(self) -> list[HomeSection]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM home_items ORDER BY section_position,item_position"
            ).fetchall()
        sections: dict[int, HomeSection] = {}
        for row in rows:
            section = sections.setdefault(
                row["section_position"], HomeSection(row["section_title"], [])
            )
            section.items.append(
                LibraryItem(
                    row["item_id"],
                    row["title"],
                    row["subtitle"],
                    row["thumbnail"],
                    row["kind"],
                    row["playlist_id"],
                    row["set_video_id"],
                )
            )
        return list(sections.values())

    def load_lyrics(self, video_id: str) -> tuple[str, str] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT lyrics, provider FROM lyrics WHERE video_id = ?", (video_id,)
            ).fetchone()
        return (row["lyrics"], row["provider"]) if row else None

    def save_lyrics(self, video_id: str, lyrics: str, provider: str = "YouTube Music") -> None:
        if not video_id or not lyrics.strip():
            return
        with self._connect() as db:
            db.execute(
                """INSERT INTO lyrics(video_id, lyrics, provider, updated_at) VALUES(?,?,?,?)
                   ON CONFLICT(video_id) DO UPDATE SET lyrics=excluded.lyrics,
                   provider=excluded.provider, updated_at=excluded.updated_at""",
                (video_id, lyrics.strip(), provider, int(time.time())),
            )

    def load_lyrics_document(self, video_id: str, provider: str = "auto") -> LyricsDocument | None:
        with self._connect() as db:
            if provider == "auto":
                row = db.execute(
                    """SELECT * FROM lyrics_documents WHERE video_id = ?
                       ORDER BY CASE WHEN synced_lyrics != '[]' THEN 0 ELSE 1 END, updated_at DESC
                       LIMIT 1""",
                    (video_id,),
                ).fetchone()
            else:
                provider_name = "LRCLIB" if provider.lower() == "lrclib" else "YouTube Music"
                row = db.execute(
                    "SELECT * FROM lyrics_documents WHERE video_id = ? AND provider = ?",
                    (video_id, provider_name),
                ).fetchone()
        if row:
            try:
                lines = [LyricLine(**entry) for entry in json.loads(row["synced_lyrics"])]
            except (TypeError, ValueError, json.JSONDecodeError):
                lines = []
            return LyricsDocument(
                row["plain_lyrics"],
                row["provider"],
                lines,
                row["translated_lyrics"],
                row["translation_language"],
            )
        # Transparently promote the cache created by older Harmonia versions.
        legacy = self.load_lyrics(video_id)
        if legacy and provider == "youtube":
            return LyricsDocument(legacy[0], legacy[1])
        return None

    def save_lyrics_document(self, video_id: str, document: LyricsDocument) -> None:
        if not video_id or not document.display_text.strip():
            return
        synced = json.dumps(
            [
                {"start_ms": line.start_ms, "text": line.text, "translation": line.translation}
                for line in document.synced
            ],
            ensure_ascii=False,
        )
        with self._connect() as db:
            db.execute(
                """INSERT INTO lyrics_documents
                   (video_id,provider,plain_lyrics,synced_lyrics,translated_lyrics,translation_language,updated_at)
                   VALUES(?,?,?,?,?,?,?) ON CONFLICT(video_id,provider) DO UPDATE SET
                   plain_lyrics=excluded.plain_lyrics, synced_lyrics=excluded.synced_lyrics,
                   translated_lyrics=excluded.translated_lyrics,
                   translation_language=excluded.translation_language, updated_at=excluded.updated_at""",
                (
                    video_id,
                    document.provider,
                    document.display_text,
                    synced,
                    document.translation,
                    document.translation_language,
                    int(time.time()),
                ),
            )
        # Preserve compatibility with consumers of the original cache API.
        self.save_lyrics(video_id, document.display_text, document.provider)

    def save_explore(self, data: ExploreData) -> None:
        now = int(time.time())
        with self._connect() as db:
            db.execute("DELETE FROM explore_items")
            db.execute("DELETE FROM explore_destinations")
            for section_position, section in enumerate(data.sections):
                db.executemany(
                    """INSERT INTO explore_items
                    (section_position,section_title,item_position,item_id,title,subtitle,thumbnail,kind,playlist_id,set_video_id,synced_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    [
                        (
                            section_position,
                            section.title,
                            item_position,
                            item.id,
                            item.title,
                            item.subtitle,
                            item.thumbnail,
                            item.kind,
                            item.playlist_id,
                            item.set_video_id,
                            now,
                        )
                        for item_position, item in enumerate(section.items)
                    ],
                )
            for group, destinations in (("shortcuts", data.shortcuts), ("genres", data.genres)):
                db.executemany(
                    """INSERT INTO explore_destinations
                    (destination_group,position,title,browse_id,params,synced_at) VALUES (?,?,?,?,?,?)""",
                    [
                        (group, position, item.title, item.browse_id, item.params, now)
                        for position, item in enumerate(destinations)
                    ],
                )

    def load_explore(self) -> ExploreData:
        with self._connect() as db:
            item_rows = db.execute(
                "SELECT * FROM explore_items ORDER BY section_position,item_position"
            ).fetchall()
            destination_rows = db.execute(
                "SELECT * FROM explore_destinations ORDER BY destination_group,position"
            ).fetchall()
        sections: dict[int, HomeSection] = {}
        for row in item_rows:
            section = sections.setdefault(
                row["section_position"], HomeSection(row["section_title"], [])
            )
            section.items.append(
                LibraryItem(
                    row["item_id"],
                    row["title"],
                    row["subtitle"],
                    row["thumbnail"],
                    row["kind"],
                    row["playlist_id"],
                    row["set_video_id"],
                )
            )
        groups: dict[str, list[ExploreDestination]] = {"shortcuts": [], "genres": []}
        for row in destination_rows:
            groups[row["destination_group"]].append(
                ExploreDestination(row["title"], row["browse_id"], row["params"])
            )
        return ExploreData(list(sections.values()), groups["shortcuts"], groups["genres"])

    def artwork_path(self, url: str) -> Path:
        return self.artwork_dir / hashlib.sha256(url.encode()).hexdigest()

    @staticmethod
    def _item_values(item: LibraryItem) -> tuple:
        return (
            item.id,
            item.title,
            item.subtitle,
            item.thumbnail,
            item.kind,
            item.playlist_id,
            item.set_video_id,
        )

    @staticmethod
    def _item_from_row(row: sqlite3.Row) -> LibraryItem:
        return LibraryItem(
            row["item_id"],
            row["title"],
            row["subtitle"],
            row["thumbnail"],
            row["kind"],
            row["playlist_id"],
            row["set_video_id"],
        )

    def save_playback_state(self, state: PlaybackState) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM playback_queue")
            for queue_group, items in (("queue", state.queue), ("related", state.related)):
                db.executemany(
                    """INSERT INTO playback_queue
                    (queue_group,position,item_id,title,subtitle,thumbnail,kind,playlist_id,set_video_id)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    [
                        (queue_group, position, *self._item_values(item))
                        for position, item in enumerate(items)
                    ],
                )
            db.execute(
                """INSERT INTO playback_state
                (id,queue_index,position_ms,shuffle,repeat_mode,autoplay,updated_at)
                VALUES (1,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                queue_index=excluded.queue_index, position_ms=excluded.position_ms,
                shuffle=excluded.shuffle, repeat_mode=excluded.repeat_mode,
                autoplay=excluded.autoplay, updated_at=excluded.updated_at""",
                (
                    state.index,
                    max(0, state.position_ms),
                    int(state.shuffle),
                    int(state.repeat),
                    int(state.autoplay),
                    int(time.time()),
                ),
            )

    def load_playback_state(self) -> PlaybackState | None:
        with self._connect() as db:
            state = db.execute("SELECT * FROM playback_state WHERE id = 1").fetchone()
            rows = db.execute(
                "SELECT * FROM playback_queue ORDER BY queue_group, position"
            ).fetchall()
        if state is None:
            return None
        grouped: dict[str, list[LibraryItem]] = {"queue": [], "related": []}
        for row in rows:
            grouped.setdefault(row["queue_group"], []).append(self._item_from_row(row))
        queue = grouped["queue"]
        index = max(0, min(state["queue_index"], len(queue) - 1)) if queue else 0
        return PlaybackState(
            queue,
            grouped["related"],
            index,
            state["position_ms"],
            bool(state["shuffle"]),
            bool(state["repeat_mode"]),
            bool(state["autoplay"]),
        )

    def clear_playback_state(self) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM playback_queue")
            db.execute("DELETE FROM playback_state")

    def history_enabled(self) -> bool:
        with self._connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key = 'history_enabled'").fetchone()
        return row is None or row["value"] == "1"

    def set_history_enabled(self, enabled: bool) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO settings(key,value) VALUES('history_enabled',?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                ("1" if enabled else "0",),
            )

    def record_history(self, item: LibraryItem, position_ms: int = 0) -> int | None:
        if not self.history_enabled():
            return None
        with self._connect() as db:
            cursor = db.execute(
                """INSERT INTO play_history
                (item_id,title,subtitle,thumbnail,kind,playlist_id,set_video_id,played_at,position_ms)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (*self._item_values(item), int(time.time()), max(0, position_ms)),
            )
            db.execute(
                "DELETE FROM play_history WHERE id NOT IN (SELECT id FROM play_history ORDER BY played_at DESC, id DESC LIMIT 1000)"
            )
            return int(cursor.lastrowid)

    def load_history(self, limit: int = 250) -> list[HistoryEntry]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM play_history ORDER BY played_at DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            HistoryEntry(row["id"], self._item_from_row(row), row["played_at"], row["position_ms"])
            for row in rows
        ]

    def remove_history(self, entry_id: int) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM play_history WHERE id = ?", (entry_id,))

    def clear_history(self) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM play_history")

    def playback_insights(self, year: int | None = None, limit: int = 8) -> PlaybackInsights:
        selected_year = year or current_year()
        with self._connect() as db:
            rows = db.execute(
                """SELECT * FROM play_history
                WHERE strftime('%Y', played_at, 'unixepoch', 'localtime') = ?
                ORDER BY played_at""",
                (str(selected_year),),
            ).fetchall()
        track_totals: dict[str, dict] = {}
        artist_plays: dict[str, int] = {}
        months = [0] * 12
        listened_ms = 0
        for row in rows:
            listened = max(0, row["position_ms"])
            listened_ms += listened
            month = int(time.strftime("%m", time.localtime(row["played_at"]))) - 1
            months[month] += 1
            total = track_totals.setdefault(
                row["item_id"], {"row": row, "plays": 0, "listened_ms": 0}
            )
            total["plays"] += 1
            total["listened_ms"] += listened
            artist = artist_from_subtitle(row["subtitle"])
            artist_plays[artist] = artist_plays.get(artist, 0) + 1
        ranked_tracks = sorted(
            track_totals.values(),
            key=lambda value: (value["plays"], value["listened_ms"]),
            reverse=True,
        )[:limit]
        top_tracks = tuple(
            RankedMedia(
                self._item_from_row(value["row"]),
                value["plays"],
                value["listened_ms"],
            )
            for value in ranked_tracks
        )
        top_artists = tuple(
            RankedArtist(name, plays)
            for name, plays in sorted(
                artist_plays.items(), key=lambda value: value[1], reverse=True
            )[:limit]
        )
        return PlaybackInsights(
            selected_year,
            len(rows),
            len(track_totals),
            listened_ms,
            top_tracks,
            top_artists,
            tuple(months),
        )

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

    def save_download(self, record: DownloadRecord) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO downloads
                (item_id,title,subtitle,thumbnail,kind,playlist_id,set_video_id,status,file_path,
                 downloaded_bytes,total_bytes,account_hash,error,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(item_id) DO UPDATE SET
                title=excluded.title, subtitle=excluded.subtitle, thumbnail=excluded.thumbnail,
                kind=excluded.kind, playlist_id=excluded.playlist_id,
                set_video_id=excluded.set_video_id, status=excluded.status,
                file_path=excluded.file_path, downloaded_bytes=excluded.downloaded_bytes,
                total_bytes=excluded.total_bytes, account_hash=excluded.account_hash,
                error=excluded.error, updated_at=excluded.updated_at""",
                (
                    *self._item_values(record.item),
                    record.status,
                    record.file_path,
                    record.downloaded_bytes,
                    record.total_bytes,
                    record.account_hash,
                    record.error,
                    record.updated_at or int(time.time()),
                ),
            )

    @staticmethod
    def _download_from_row(row: sqlite3.Row) -> DownloadRecord:
        item = Storage._item_from_row(row)
        return DownloadRecord(
            item,
            row["status"],
            row["file_path"],
            row["downloaded_bytes"],
            row["total_bytes"],
            row["account_hash"],
            row["error"],
            row["updated_at"],
        )

    def load_downloads(self) -> list[DownloadRecord]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM downloads ORDER BY updated_at DESC").fetchall()
        return [self._download_from_row(row) for row in rows]

    def get_download(self, item_id: str) -> DownloadRecord | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM downloads WHERE item_id = ?", (item_id,)).fetchone()
        return self._download_from_row(row) if row else None

    def delete_download_record(self, item_id: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM downloads WHERE item_id = ?", (item_id,))

    def download_storage_bytes(self) -> int:
        return sum(
            record.downloaded_bytes
            for record in self.load_downloads()
            if record.status == "completed"
        )

    def add_local_files(self, paths: list[str]) -> list[LibraryItem]:
        now = int(time.time())
        items: list[LibraryItem] = []
        with self._connect() as db:
            for raw_path in paths:
                path = Path(raw_path).expanduser().resolve()
                if not path.is_file():
                    continue
                item_id = "local:" + hashlib.sha256(str(path).encode()).hexdigest()[:24]
                title = path.stem.replace("_", " ")
                subtitle = path.parent.name
                modified = int(path.stat().st_mtime)
                db.execute(
                    """INSERT INTO local_media(item_id,path,title,subtitle,added_at,modified_at)
                    VALUES(?,?,?,?,?,?) ON CONFLICT(item_id) DO UPDATE SET
                    path=excluded.path,title=excluded.title,subtitle=excluded.subtitle,
                    modified_at=excluded.modified_at""",
                    (item_id, str(path), title, subtitle, now, modified),
                )
                items.append(LibraryItem(item_id, title, subtitle, kind="songs"))
        return items

    def load_local_media(self) -> list[LibraryItem]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM local_media ORDER BY added_at DESC, title COLLATE NOCASE"
            ).fetchall()
        return [
            LibraryItem(row["item_id"], row["title"], row["subtitle"], kind="songs") for row in rows
        ]

    def local_media_path(self, item_id: str) -> Path | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT path FROM local_media WHERE item_id = ?", (item_id,)
            ).fetchone()
        return Path(row["path"]) if row else None

    def remove_local_media(self, item_id: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM local_media WHERE item_id = ?", (item_id,))

    def create_local_playlist(self, title: str, items: list[LibraryItem] | None = None) -> int:
        now = int(time.time())
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO local_playlists(title,created_at,updated_at) VALUES(?,?,?)",
                (title.strip(), now, now),
            )
            playlist_id = int(cursor.lastrowid)
            self._replace_local_playlist_items(db, playlist_id, items or [])
        return playlist_id

    def _replace_local_playlist_items(
        self, db: sqlite3.Connection, playlist_id: int, items: list[LibraryItem]
    ) -> None:
        db.execute("DELETE FROM local_playlist_items WHERE playlist_id = ?", (playlist_id,))
        db.executemany(
            """INSERT INTO local_playlist_items
            (playlist_id,position,item_id,title,subtitle,thumbnail,kind,remote_playlist_id,set_video_id)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            [
                (playlist_id, position, *self._item_values(item))
                for position, item in enumerate(items)
            ],
        )

    def save_local_playlist(self, playlist: LocalPlaylist) -> None:
        if playlist.id is None:
            playlist.id = self.create_local_playlist(playlist.title, playlist.items)
            return
        with self._connect() as db:
            db.execute(
                "UPDATE local_playlists SET title = ?, updated_at = ? WHERE id = ?",
                (playlist.title.strip(), int(time.time()), playlist.id),
            )
            self._replace_local_playlist_items(db, playlist.id, playlist.items)

    def load_local_playlists(self) -> list[LocalPlaylist]:
        with self._connect() as db:
            playlists = db.execute(
                "SELECT * FROM local_playlists ORDER BY updated_at DESC, title COLLATE NOCASE"
            ).fetchall()
            items = db.execute(
                "SELECT * FROM local_playlist_items ORDER BY playlist_id, position"
            ).fetchall()
        grouped: dict[int, list[LibraryItem]] = {}
        for row in items:
            grouped.setdefault(row["playlist_id"], []).append(
                LibraryItem(
                    row["item_id"],
                    row["title"],
                    row["subtitle"],
                    row["thumbnail"],
                    row["kind"],
                    row["remote_playlist_id"],
                    row["set_video_id"],
                )
            )
        return [
            LocalPlaylist(
                row["id"],
                row["title"],
                grouped.get(row["id"], []),
                row["created_at"],
                row["updated_at"],
            )
            for row in playlists
        ]

    def get_local_playlist(self, playlist_id: int) -> LocalPlaylist | None:
        return next(
            (playlist for playlist in self.load_local_playlists() if playlist.id == playlist_id),
            None,
        )

    def delete_local_playlist(self, playlist_id: int) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM local_playlist_items WHERE playlist_id = ?", (playlist_id,))
            db.execute("DELETE FROM local_playlists WHERE id = ?", (playlist_id,))
