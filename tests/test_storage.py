from harmonia.models import (
    ExploreData,
    ExploreDestination,
    HomeSection,
    LibraryItem,
    LyricLine,
    LyricsDocument,
    PlaybackState,
)
from harmonia.storage import Storage


def test_sqlite_library_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    storage = Storage()
    item = LibraryItem("id", "Título", "Artista", "cover", "songs", "PL", "SET")
    storage.save_library({"songs": [item]})
    assert storage.load_library() == {"songs": [item]}
    assert storage.database_file.exists()


def test_action_log(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    storage = Storage()
    storage.log_action("like-song", "video", "completed")
    with storage._connect() as db:
        row = db.execute("SELECT action, target_id, status FROM action_log").fetchone()
    assert tuple(row) == ("like-song", "video", "completed")


def test_home_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    storage = Storage()
    sections = [HomeSection("Ouvir de novo", [LibraryItem("v", "Faixa", kind="songs")])]
    storage.save_home(sections)
    assert storage.load_home() == sections


def test_lyrics_cached_by_older_versions_are_still_read(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    storage = Storage()
    assert storage.load_lyrics_document("video", "youtube") is None
    with storage._connect() as db:
        db.execute(
            "INSERT INTO lyrics(video_id, lyrics, provider, updated_at) VALUES(?,?,?,?)",
            ("video", "Linha um\nLinha dois", "YouTube Music", 0),
        )
    assert storage.load_lyrics_document("video", "youtube") == LyricsDocument(
        "Linha um\nLinha dois", "YouTube Music"
    )
    # The legacy cache only ever held YouTube Music lyrics.
    assert storage.load_lyrics_document("video", "lrclib") is None


def test_youtube_lyrics_are_not_answered_with_another_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    storage = Storage()
    storage.save_lyrics_document("video", LyricsDocument("Synced", "LRCLIB"))
    assert storage.load_lyrics_document("video", "youtube") is None


def test_advanced_lyrics_cache_keeps_providers_and_translation(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    storage = Storage()
    native = LyricsDocument("Native", "YouTube Music")
    synced = LyricsDocument(
        "One\nTwo",
        "LRCLIB",
        [LyricLine(1000, "One", "Um"), LyricLine(2500, "Two", "Dois")],
        "",
        "pt",
    )
    storage.save_lyrics_document("video", native)
    storage.save_lyrics_document("video", synced)
    assert storage.load_lyrics_document("video", "youtube") == native
    assert storage.load_lyrics_document("video", "auto") == synced

    # Lyrics timed by word keep their words and win the automatic choice.
    from harmonia.models import LyricWord

    words = (LyricWord(1000, 1400, "One "), LyricWord(1400, 2400, "more"))
    karaoke = LyricsDocument("One more", "LyricsPlus", [LyricLine(1000, "One more", words=words)])
    storage.save_lyrics_document("video", karaoke)
    assert storage.load_lyrics_document("video", "auto") == karaoke
    assert storage.load_lyrics_document("video", "lyricsplus") == karaoke
    assert storage.load_lyrics_document("video", "lrclib") == synced


def test_explore_cache_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    storage = Storage()
    data = ExploreData(
        [HomeSection("Em alta", [LibraryItem("video", "Faixa", kind="songs")])],
        [ExploreDestination("Paradas", "FEmusic_charts", "charts")],
        [ExploreDestination("Rock", "FEmusic_moods_and_genres_category", "rock")],
    )
    storage.save_explore(data)
    assert storage.load_explore() == data


def test_playback_queue_and_related_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    storage = Storage()
    state = PlaybackState(
        [LibraryItem("one", "Primeira", kind="songs"), LibraryItem("two", "Segunda", kind="songs")],
        [LibraryItem("related", "Relacionada", kind="songs")],
        index=1,
        position_ms=42000,
        shuffle=True,
        repeat=True,
        autoplay=False,
    )
    storage.save_playback_state(state)
    assert storage.load_playback_state() == state
    storage.clear_playback_state()
    assert storage.load_playback_state() is None


def test_local_history_respects_privacy_and_removal(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    storage = Storage()
    item = LibraryItem("song", "Faixa", "Artista", kind="songs")
    entry_id = storage.record_history(item, 12000)
    assert entry_id is not None
    entries = storage.load_history()
    assert entries[0].item == item
    assert entries[0].position_ms == 12000
    storage.remove_history(entry_id)
    assert storage.load_history() == []
    storage.set_history_enabled(False)
    assert storage.record_history(item) is None
    assert storage.load_history() == []


def test_local_media_and_playlist_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    first = tmp_path / "Primeira faixa.mp3"
    second = tmp_path / "segunda_faixa.flac"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    storage = Storage()
    items = storage.add_local_files([str(first), str(second)])
    assert [item.title for item in items] == ["Primeira faixa", "segunda faixa"]
    assert storage.local_media_path(items[0].id) == first
    playlist_id = storage.create_local_playlist("Local", items)
    playlist = storage.get_local_playlist(playlist_id)
    assert playlist.title == "Local"
    assert playlist.items == items
    playlist.items.reverse()
    playlist.title = "Reordenada"
    storage.save_local_playlist(playlist)
    assert storage.get_local_playlist(playlist_id).items == list(reversed(items))
    storage.delete_local_playlist(playlist_id)
    assert storage.get_local_playlist(playlist_id) is None
