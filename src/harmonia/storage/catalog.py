"""Cached YouTube Music pages: library, home, explore, artwork and the action log."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path

from ..models import (
    ExploreData,
    ExploreDestination,
    HomeSection,
    LibraryItem,
)
from .database import ITEM_COLUMNS, Database

LOGGER = logging.getLogger(__name__)


class CatalogCache(Database):
    def _migrate_json_cache(self) -> None:
        if not self.library_file.exists():
            return
        with self._connect() as db:
            count = db.execute("SELECT count(*) FROM library_items").fetchone()[0]
        if count:
            return
        try:
            data = json.loads(self.library_file.read_text())
            sections = {
                key: [LibraryItem.from_dict(item) for item in items] for key, items in data.items()
            }
            self.save_library(sections)
            self.library_file.rename(self.library_file.with_suffix(".json.migrated"))
        except (OSError, ValueError, TypeError):
            LOGGER.warning("O cache JSON legado não pôde ser migrado", exc_info=True)

    def clear_cache(self) -> int:
        removed = 0
        for path in self.artwork_dir.iterdir():
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
                    f"""INSERT INTO library_items
                    (category,{ITEM_COLUMNS},position,synced_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    [
                        (category, *self._item_values(item), position, now)
                        for position, item in enumerate(items)
                    ],
                )

    def load_library(self) -> dict[str, list[LibraryItem]]:
        result: dict[str, list[LibraryItem]] = {}
        with self._connect() as db:
            rows = db.execute("SELECT * FROM library_items ORDER BY category, position").fetchall()
        for row in rows:
            result.setdefault(row["category"], []).append(self._item_from_row(row))
        return result

    def log_action(
        self, action: str, target_id: str | None, status: str, error: str | None = None
    ) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO action_log(action,target_id,status,error,created_at) VALUES(?,?,?,?,?)",
                (action, target_id, status, error, int(time.time())),
            )

    def _save_sections(
        self, db: sqlite3.Connection, table: str, sections: list[HomeSection], now: int
    ) -> None:
        """Rows of ``home_items`` or ``explore_items``: one per item, by section."""
        for section_position, section in enumerate(sections):
            db.executemany(
                f"""INSERT INTO {table}
                (section_position,section_title,item_position,{ITEM_COLUMNS},synced_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    (section_position, section.title, item_position, *self._item_values(item), now)
                    for item_position, item in enumerate(section.items)
                ],
            )

    def _sections_from_rows(self, rows: list[sqlite3.Row]) -> list[HomeSection]:
        sections: dict[int, HomeSection] = {}
        for row in rows:
            section = sections.setdefault(
                row["section_position"], HomeSection(row["section_title"], [])
            )
            section.items.append(self._item_from_row(row))
        return list(sections.values())

    def save_home(self, sections: list[HomeSection]) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM home_items")
            self._save_sections(db, "home_items", sections, int(time.time()))

    def load_home(self) -> list[HomeSection]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM home_items ORDER BY section_position,item_position"
            ).fetchall()
        return self._sections_from_rows(rows)

    def save_explore(self, data: ExploreData) -> None:
        now = int(time.time())
        with self._connect() as db:
            db.execute("DELETE FROM explore_items")
            db.execute("DELETE FROM explore_destinations")
            self._save_sections(db, "explore_items", data.sections, now)
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
        groups: dict[str, list[ExploreDestination]] = {"shortcuts": [], "genres": []}
        for row in destination_rows:
            groups[row["destination_group"]].append(
                ExploreDestination(row["title"], row["browse_id"], row["params"])
            )
        return ExploreData(
            self._sections_from_rows(item_rows), groups["shortcuts"], groups["genres"]
        )

    def artwork_path(self, url: str) -> Path:
        return self.artwork_dir / hashlib.sha256(url.encode()).hexdigest()
