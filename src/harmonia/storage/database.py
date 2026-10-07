"""The SQLite database under every cache: connection, schema and item rows."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from ..models import (
    LibraryItem,
)

# Columns of every table that stores a LibraryItem, in _item_values order.
ITEM_COLUMNS = "item_id,title,subtitle,thumbnail,kind,playlist_id,set_video_id"


class Database:
    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # sqlite3's own context manager only commits or rolls back; it never
        # closes the connection, which leaks file handles and triggers
        # ResourceWarning on Python 3.13+.
        connection = sqlite3.connect(self.database_file)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

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
    def _item_from_row(row: sqlite3.Row, playlist_column: str = "playlist_id") -> LibraryItem:
        return LibraryItem(
            row["item_id"],
            row["title"],
            row["subtitle"],
            row["thumbnail"],
            row["kind"],
            row[playlist_column],
            row["set_video_id"],
        )
