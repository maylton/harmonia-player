"""Offline downloads and their progress."""

from __future__ import annotations

import sqlite3
import time

from ..models import (
    DownloadRecord,
)
from .database import ITEM_COLUMNS, Database


class DownloadRecords(Database):
    def save_download(self, record: DownloadRecord) -> None:
        with self._connect() as db:
            db.execute(
                f"""INSERT INTO downloads
                ({ITEM_COLUMNS},status,file_path,
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
        item = Database._item_from_row(row)
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
