"""Loudness YouTube reported per track, kept for playing downloads offline."""

from __future__ import annotations

import time

from .database import Database


class LoudnessRecords(Database):
    def _initialize_loudness(self) -> None:
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS track_loudness (
                       video_id TEXT PRIMARY KEY, loudness_db REAL NOT NULL,
                       updated_at INTEGER NOT NULL
                   )"""
            )

    def save_track_loudness(self, video_id: str, loudness_db: float | None) -> None:
        if not video_id or loudness_db is None:
            return
        with self._connect() as db:
            db.execute(
                """INSERT INTO track_loudness(video_id, loudness_db, updated_at) VALUES(?,?,?)
                   ON CONFLICT(video_id) DO UPDATE SET
                   loudness_db=excluded.loudness_db, updated_at=excluded.updated_at""",
                (video_id, float(loudness_db), int(time.time())),
            )

    def track_loudness(self, video_id: str) -> float | None:
        if not video_id:
            return None
        with self._connect() as db:
            row = db.execute(
                "SELECT loudness_db FROM track_loudness WHERE video_id = ?", (video_id,)
            ).fetchone()
        return float(row["loudness_db"]) if row else None
