from harmonia.loudness import (
    MAX_CUT_DB,
    OFF,
    REPLAYGAIN_TO_YOUTUBE_DB,
    loudness_from_player,
    replaygain_settings,
    track_gain,
)


def test_loudness_comes_from_the_player_config_or_the_format():
    assert loudness_from_player({"playerConfig": {"audioConfig": {"loudnessDb": 3.2}}}) == 3.2
    assert loudness_from_player({}, {"loudnessDb": -1}) == -1.0
    # As the iOS and visionOS clients report it, without loudnessDb in audioConfig.
    absolute = {"trackAbsoluteLoudnessLkfs": -8.29, "loudnessTargetLkfs": -14}
    assert round(loudness_from_player({"playerConfig": {"audioConfig": absolute}}), 2) == 5.71
    assert loudness_from_player({"playerConfig": {"audioConfig": {"loudnessDb": True}}}) is None
    assert loudness_from_player({"playerConfig": None}) is None


def test_loud_tracks_are_turned_down_and_quiet_ones_kept():
    assert track_gain(6.0) == -6.0
    assert track_gain(-5.0) == 0.0  # like YouTube, quiet tracks are not boosted
    assert track_gain(60.0) == MAX_CUT_DB
    assert track_gain(None) == 0.0
    # The level shifts every track, known loudness or not.
    assert track_gain(6.0, "soft") == -10.0
    assert track_gain(None, "loud") == 3.0
    assert track_gain(6.0, "unknown") == -6.0


def test_replaygain_settings_add_up_to_the_track_gain():
    settings = replaygain_settings(True, "standard", 6.0)
    assert settings.fallback_gain + settings.pre_amp == -6.0
    # Tagged local files (ReplayGain, -18 LUFS) are raised to the streams' -14 LUFS.
    assert settings.pre_amp == REPLAYGAIN_TO_YOUTUBE_DB
    loud = replaygain_settings(True, "loud", None)
    assert loud.fallback_gain + loud.pre_amp == 3.0
    assert loud.headroom >= 3.0 and loud.limiter
    assert replaygain_settings(False, "loud", 6.0) == OFF


def test_storage_keeps_loudness_for_offline_playback(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    from harmonia.storage import Storage

    storage = Storage()
    assert storage.track_loudness("video") is None
    storage.save_track_loudness("video", 2.5)
    storage.save_track_loudness("video", 3.0)
    storage.save_track_loudness("other", None)
    assert storage.track_loudness("video") == 3.0
    assert storage.track_loudness("other") is None
