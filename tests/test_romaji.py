import pytest

from harmonia import romaji


def test_kana_becomes_modified_hepburn():
    assert romaji.kana_to_romaji("キミ") == "kimi"
    assert romaji.kana_to_romaji("シャシン") == "shashin"
    assert romaji.kana_to_romaji("チョット") == "chotto"
    # The small tsu doubles the next consonant, "tch" before "ch".
    assert romaji.kana_to_romaji("マッチ") == "matchi"
    # The long vowel mark repeats the vowel; hiragana reads the same.
    assert romaji.kana_to_romaji("コーヒー") == "koohii"
    assert romaji.kana_to_romaji("ふぁんたじー") == "fantajii"


def test_only_lyrics_with_kana_count_as_japanese():
    assert romaji.is_japanese("君の名前を呼んだ")
    assert romaji.is_japanese("アイドル")
    assert not romaji.is_japanese("我爱你")  # Chinese: no kana
    assert not romaji.is_japanese("Hello")


@pytest.mark.skipif(not romaji.available(), reason="fugashi/unidic-lite ausentes")
def test_lines_read_like_metrolist_and_cutlet():
    cases = {
        "君の名前を呼んだ": "kimi no namae wo yonda",
        "完璧で究極のアイドル": "kanpeki de kyuukyoku no aidoru",
        "夢ならばどれほどよかったでしょう": "yume naraba dore hodo yokattadeshou",
        "僕は、君を待っている！": "boku wa, kimi wo matte iru!",  # noqa: RUF001
        "Baby 愛してる forever": "Baby aishiteru forever",
    }
    for line, expected in cases.items():
        assert romaji.romanize(line) == expected
    assert romaji.romanize("No Japanese here") == "No Japanese here"
