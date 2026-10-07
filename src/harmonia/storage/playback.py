"""The saved queue and position, the play history and its yearly insights."""

from __future__ import annotations

import time

from ..insights import (
    PlaybackInsights,
    RankedArtist,
    RankedMedia,
    artist_from_subtitle,
    current_year,
)
from ..models import (
    HistoryEntry,
    LibraryItem,
    PlaybackState,
)
from .database import ITEM_COLUMNS, Database


class PlaybackRecords(Database):
    def save_playback_state(self, state: PlaybackState) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM playback_queue")
            for queue_group, items in (("queue", state.queue), ("related", state.related)):
                db.executemany(
                    f"""INSERT INTO playback_queue
                    (queue_group,position,{ITEM_COLUMNS})
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
                f"""INSERT INTO play_history
                ({ITEM_COLUMNS},played_at,position_ms)
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
