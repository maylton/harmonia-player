"""Library changes made in Harmonia that YouTube Music may not list yet."""

from __future__ import annotations

import dataclasses
import json
import time

from ..library_sync import PENDING_TTL_S, PendingChange
from ..models import LibraryItem
from .database import Database


class LibraryChanges(Database):
    def _initialize_library_changes(self) -> None:
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS library_changes (
                       category TEXT NOT NULL, item_id TEXT NOT NULL, added INTEGER NOT NULL,
                       item TEXT NOT NULL, created_at INTEGER NOT NULL,
                       PRIMARY KEY (category, item_id)
                   )"""
            )

    def record_library_change(self, category: str, item: LibraryItem, added: bool) -> None:
        """The latest change to an item wins: liking and unliking cancel out."""
        with self._connect() as db:
            db.execute(
                """INSERT INTO library_changes(category,item_id,added,item,created_at)
                   VALUES(?,?,?,?,?) ON CONFLICT(category,item_id) DO UPDATE SET
                   added=excluded.added, item=excluded.item, created_at=excluded.created_at""",
                (
                    category,
                    item.id,
                    int(added),
                    json.dumps(dataclasses.asdict(item), ensure_ascii=False),
                    int(time.time()),
                ),
            )

    def pending_library_changes(self, now: int | None = None) -> list[PendingChange]:
        """The changes still pending; older ones are dropped, YouTube has had time."""
        now = int(time.time()) if now is None else now
        with self._connect() as db:
            db.execute("DELETE FROM library_changes WHERE created_at < ?", (now - PENDING_TTL_S,))
            rows = db.execute("SELECT * FROM library_changes ORDER BY created_at DESC").fetchall()
        changes = []
        for row in rows:
            try:
                item = LibraryItem.from_dict(json.loads(row["item"]))
            except (TypeError, ValueError):
                continue
            changes.append(
                PendingChange(row["category"], item, bool(row["added"]), row["created_at"])
            )
        return changes

    def clear_library_changes(self) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM library_changes")

    def forget_library_changes(self, changes: list[PendingChange]) -> None:
        if not changes:
            return
        with self._connect() as db:
            db.executemany(
                "DELETE FROM library_changes WHERE category = ? AND item_id = ?",
                [(change.category, change.item.id) for change in changes],
            )
