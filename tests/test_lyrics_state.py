from harmonia.lyrics_state import (
    active_lyric_index,
    clamp_lyrics_offset,
    lyric_seek_target,
    lyrics_copy_text,
    next_lyrics_provider,
    normalize_lyrics_provider,
)
from harmonia.models import LyricLine, LyricsDocument


def test_lyrics_provider_normalization_and_cycle() -> None:
    assert normalize_lyrics_provider("YOUTUBE") == "youtube"
    assert normalize_lyrics_provider("unknown") == "auto"
    assert normalize_lyrics_provider("LyricsPlus") == "lyricsplus"
    assert next_lyrics_provider("auto") == "lyricsplus"
    assert next_lyrics_provider("lyricsplus") == "lrclib"
    assert next_lyrics_provider("lrclib") == "youtube"
    assert next_lyrics_provider("youtube") == "auto"
    assert next_lyrics_provider("invalid") == "lyricsplus"


def test_translations_keep_the_words_of_each_line() -> None:
    from harmonia.lyrics_state import remove_translation, with_translations
    from harmonia.models import LyricWord

    words = (LyricWord(1000, 1400, "One "), LyricWord(1400, 1900, "day"))
    document = LyricsDocument("One day", "LyricsPlus", [LyricLine(1000, "One day", words=words)])
    document.synced = with_translations(document.synced, ["Um dia"])
    document.translation_language = "pt"
    assert document.synced[0].translation == "Um dia" and document.synced[0].words == words
    assert remove_translation(document)
    assert document.synced[0].translation == "" and document.synced[0].words == words


def test_lyrics_offset_is_clamped_and_seek_uses_the_same_offset_rule() -> None:
    assert clamp_lyrics_offset(-9000) == -5000
    assert clamp_lyrics_offset(9000) == 5000
    assert clamp_lyrics_offset(750) == 750
    assert lyric_seek_target(1000, 250) == 750
    assert lyric_seek_target(100, 250) == 0
    assert lyric_seek_target(1000, -250) == 1250


def test_active_lyric_index_uses_position_and_offset() -> None:
    lines = [
        LyricLine(1000, "one"),
        LyricLine(2500, "two"),
        LyricLine(4000, "three"),
    ]
    assert active_lyric_index(lines, 500) == -1
    assert active_lyric_index(lines, 2200) == 0
    assert active_lyric_index(lines, 2200, 400) == 1
    assert active_lyric_index(lines, 4200, -300) == 1


def test_active_lyric_index_can_preserve_negative_adjusted_position() -> None:
    lines = [LyricLine(0, "zero"), LyricLine(1000, "one")]
    assert active_lyric_index(lines, 0, -250) == 0
    assert active_lyric_index(lines, 0, -250, floor_at_zero=False) == -1


def test_lyrics_copy_text_prefers_timestamp_aligned_translations() -> None:
    document = LyricsDocument(
        "One\nTwo",
        "LRCLIB",
        [LyricLine(1000, "One", "Um"), LyricLine(2000, "Two")],
        translation="Tradução simples",
        translation_language="pt",
    )
    assert lyrics_copy_text(document) == "One\nUm\nTwo"


def test_lyrics_copy_text_preserves_plain_translation() -> None:
    document = LyricsDocument(
        "One\nTwo",
        "YouTube Music",
        translation="Um\nDois",
        translation_language="pt",
    )
    assert lyrics_copy_text(document) == "One\nTwo\n\nUm\nDois"
