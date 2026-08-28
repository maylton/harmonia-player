from harmonia.media_variants import (
    VIDEO_DURATION_TOLERANCE_MS,
    is_independent_video_variant,
)


def test_small_duration_difference_keeps_shared_song_timeline() -> None:
    assert not is_independent_video_variant(
        item_kind="songs",
        song_duration_ms=180_000,
        video_duration_ms=180_000 + VIDEO_DURATION_TOLERANCE_MS,
    )


def test_distinct_music_video_uses_its_own_timeline() -> None:
    assert is_independent_video_variant(
        item_kind="songs",
        song_duration_ms=180_000,
        video_duration_ms=193_000,
    )


def test_existing_video_item_already_owns_its_audio_timeline() -> None:
    assert not is_independent_video_variant(
        item_kind="videos",
        song_duration_ms=180_000,
        video_duration_ms=220_000,
    )


def test_unknown_duration_does_not_force_independent_playback() -> None:
    assert not is_independent_video_variant(
        item_kind="songs",
        song_duration_ms=0,
        video_duration_ms=220_000,
    )
    assert not is_independent_video_variant(
        item_kind="songs",
        song_duration_ms=180_000,
        video_duration_ms=None,
    )
