"""Equalizer profiles imported from AutoEQ, by name."""

from __future__ import annotations

import json
import time

from .database import Database


class EqProfiles(Database):
    def _initialize_eq_profiles(self) -> None:
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS eq_profiles (
                       name TEXT PRIMARY KEY, gains TEXT NOT NULL, created_at INTEGER NOT NULL
                   )"""
            )

    def save_eq_profile(self, name: str, gains: tuple[float, ...]) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO eq_profiles(name, gains, created_at) VALUES(?,?,?)
                   ON CONFLICT(name) DO UPDATE SET gains=excluded.gains""",
                (name, json.dumps(list(gains)), int(time.time())),
            )

    def eq_profiles(self) -> dict[str, tuple[float, ...]]:
        with self._connect() as db:
            rows = db.execute("SELECT name, gains FROM eq_profiles ORDER BY name").fetchall()
        profiles = {}
        for row in rows:
            try:
                profiles[row["name"]] = tuple(float(gain) for gain in json.loads(row["gains"]))
            except (TypeError, ValueError):
                continue
        return profiles

    def delete_eq_profile(self, name: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM eq_profiles WHERE name = ?", (name,))
