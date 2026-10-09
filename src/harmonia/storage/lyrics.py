"""Lyrics documents per track and provider."""

from __future__ import annotations

import json
import time

from ..lyrics_state import PROVIDER_NAMES
from ..models import (
    LyricLine,
    LyricsDocument,
    LyricWord,
)
from .database import Database


def _line_to_json(line: LyricLine) -> dict:
    entry = {"start_ms": line.start_ms, "text": line.text, "translation": line.translation}
    if line.words:
        entry["words"] = [
            {"start_ms": word.start_ms, "end_ms": word.end_ms, "text": word.text}
            for word in line.words
        ]
    return entry


def _line_from_json(entry: dict) -> LyricLine:
    words = tuple(LyricWord(**word) for word in entry.get("words") or ())
    return LyricLine(entry["start_ms"], entry["text"], entry.get("translation", ""), words=words)


class LyricsCache(Database):
    def load_lyrics_document(self, video_id: str, provider: str = "auto") -> LyricsDocument | None:
        with self._connect() as db:
            if provider == "auto":
                # Timed by word first, then by line, then plain.
                row = db.execute(
                    """SELECT * FROM lyrics_documents WHERE video_id = ?
                       ORDER BY CASE WHEN synced_lyrics LIKE '%"words": [{%' THEN 0
                                     WHEN synced_lyrics != '[]' THEN 1 ELSE 2 END,
                                updated_at DESC
                       LIMIT 1""",
                    (video_id,),
                ).fetchone()
            else:
                provider_name = PROVIDER_NAMES.get(provider.lower(), PROVIDER_NAMES["youtube"])
                row = db.execute(
                    "SELECT * FROM lyrics_documents WHERE video_id = ? AND provider = ?",
                    (video_id, provider_name),
                ).fetchone()
            # The plain "lyrics" table is the cache of Harmonia versions before
            # lyrics documents; it only ever held YouTube Music lyrics.
            legacy = (
                db.execute(
                    "SELECT lyrics, provider FROM lyrics WHERE video_id = ?", (video_id,)
                ).fetchone()
                if row is None and provider == "youtube"
                else None
            )
        if row:
            try:
                lines = [_line_from_json(entry) for entry in json.loads(row["synced_lyrics"])]
            except (TypeError, ValueError, json.JSONDecodeError):
                lines = []
            return LyricsDocument(
                row["plain_lyrics"],
                row["provider"],
                lines,
                row["translated_lyrics"],
                row["translation_language"],
            )
        if legacy:
            return LyricsDocument(legacy["lyrics"], legacy["provider"])
        return None

    def save_lyrics_document(self, video_id: str, document: LyricsDocument) -> None:
        if not video_id or not document.display_text.strip():
            return
        synced = json.dumps([_line_to_json(line) for line in document.synced], ensure_ascii=False)
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
