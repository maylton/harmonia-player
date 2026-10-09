"""Local files added to the library and local playlists."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path

from ..models import (
    LibraryItem,
    LocalPlaylist,
)
from .database import Database


class LocalMedia(Database):
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
            (playlist_id,position,item_id,title,subtitle,thumbnail,kind,remote_playlist_id,
             set_video_id,explicit)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
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
                self._item_from_row(row, "remote_playlist_id")
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
