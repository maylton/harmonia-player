import sqlite3

from harmonia.innertube.parsers import parse_library_items, parse_watch_queue
from harmonia.models import LibraryItem

EXPLICIT = {"musicInlineBadgeRenderer": {"icon": {"iconType": "MUSIC_EXPLICIT_BADGE"}}}


def song_renderer(video_id, title, badges=None):
    renderer = {
        "flexColumns": [
            {"musicResponsiveListItemFlexColumnRenderer": {"text": {"runs": [{"text": title}]}}}
        ],
        "playlistItemData": {"videoId": video_id},
        "overlay": {
            "musicItemThumbnailOverlayRenderer": {
                "content": {
                    "musicPlayButtonRenderer": {
                        "playNavigationEndpoint": {"watchEndpoint": {"videoId": video_id}}
                    }
                }
            }
        },
    }
    if badges:
        renderer["badges"] = badges
    return {"musicResponsiveListItemRenderer": renderer}


def test_the_explicit_badge_is_parsed_from_lists_and_queues():
    payload = {
        "contents": [
            song_renderer("aaaaaaaaaaa", "Clean"),
            song_renderer("bbbbbbbbbbb", "Dirty", [EXPLICIT]),
        ]
    }
    items = {item.title: item.explicit for item in parse_library_items(payload, "songs")}
    assert items == {"Clean": False, "Dirty": True}

    queue = {
        "contents": [
            {
                "playlistPanelVideoRenderer": {
                    "videoId": "ccccccccccc",
                    "title": {"runs": [{"text": "Na fila"}]},
                    "badges": [EXPLICIT],
                }
            }
        ]
    }
    assert parse_watch_queue(queue, audio_only=False)[0].explicit is True


def test_the_badge_survives_the_cache_and_old_databases_gain_the_column(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    database = tmp_path / "cache" / "harmonia" / "library.db"
    database.parent.mkdir(parents=True)
    # A library table from before the explicit column.
    with sqlite3.connect(database) as db:
        db.execute(
            """CREATE TABLE library_items (
                category TEXT NOT NULL, item_id TEXT NOT NULL, title TEXT NOT NULL,
                subtitle TEXT NOT NULL DEFAULT '', thumbnail TEXT, kind TEXT NOT NULL,
                playlist_id TEXT, set_video_id TEXT, position INTEGER NOT NULL,
                synced_at INTEGER NOT NULL, PRIMARY KEY (category, item_id))"""
        )
        db.execute(
            "INSERT INTO library_items VALUES('songs','old','Antiga','',NULL,'songs',NULL,NULL,0,0)"
        )
    db.close()
    from harmonia.storage import Storage

    storage = Storage()
    assert storage.load_library()["songs"][0].explicit is False
    dirty = LibraryItem("new", "Nova", kind="songs", explicit=True)
    storage.save_library({"songs": [dirty]})
    storage.record_history(dirty, 0)
    assert storage.load_library()["songs"][0].explicit is True
    assert storage.load_history()[0].item.explicit is True
