"""Japanese lyrics in rōmaji, read on this device.

No lyrics provider ships rōmaji, so Harmonia reads the lyrics itself, as
Metrolist does with Kuromoji: MeCab (through fugashi, with the UniDic Lite
dictionary) splits each line into words and gives their kana reading, which
becomes modified Hepburn here. Particles take their pronunciation (は "wa",
へ "e", を "wo") and verb endings and auxiliaries stay on their word
("yonda", "tokete", "yokattadeshou").

fugashi and unidic-lite are optional: without them ``available()`` is False
and the lyrics stay as they are.
"""

from __future__ import annotations

import logging
import re
import threading
from functools import lru_cache

LOGGER = logging.getLogger(__name__)

_KANA = re.compile(r"[぀-ヿ]")
_JAPANESE = re.compile(r"[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]")

# Katakana to modified Hepburn; two-character keys (a kana and a small one)
# are tried before single ones.
_DIGRAPHS = {
    "キャ": "kya", "キュ": "kyu", "キョ": "kyo", "ギャ": "gya", "ギュ": "gyu", "ギョ": "gyo",
    "シャ": "sha", "シュ": "shu", "ショ": "sho", "シェ": "she", "ジャ": "ja", "ジュ": "ju",
    "ジョ": "jo", "ジェ": "je", "チャ": "cha", "チュ": "chu", "チョ": "cho", "チェ": "che",
    "ヂャ": "ja", "ヂュ": "ju", "ヂョ": "jo", "ニャ": "nya", "ニュ": "nyu", "ニョ": "nyo",
    "ヒャ": "hya", "ヒュ": "hyu", "ヒョ": "hyo", "ビャ": "bya", "ビュ": "byu", "ビョ": "byo",
    "ピャ": "pya", "ピュ": "pyu", "ピョ": "pyo", "ミャ": "mya", "ミュ": "myu", "ミョ": "myo",
    "リャ": "rya", "リュ": "ryu", "リョ": "ryo", "ファ": "fa", "フィ": "fi", "フェ": "fe",
    "フォ": "fo", "ティ": "ti", "ディ": "di", "トゥ": "tu", "ドゥ": "du", "ウィ": "wi",
    "ウェ": "we", "ウォ": "wo", "ヴァ": "va", "ヴィ": "vi", "ヴェ": "ve", "ヴォ": "vo",
    "ツァ": "tsa", "ツィ": "tsi", "ツェ": "tse", "ツォ": "tso", "デュ": "dyu", "テュ": "tyu",
}  # fmt: skip
_MONOGRAPHS = {
    "ア": "a", "イ": "i", "ウ": "u", "エ": "e", "オ": "o",
    "カ": "ka", "キ": "ki", "ク": "ku", "ケ": "ke", "コ": "ko",
    "ガ": "ga", "ギ": "gi", "グ": "gu", "ゲ": "ge", "ゴ": "go",
    "サ": "sa", "シ": "shi", "ス": "su", "セ": "se", "ソ": "so",
    "ザ": "za", "ジ": "ji", "ズ": "zu", "ゼ": "ze", "ゾ": "zo",
    "タ": "ta", "チ": "chi", "ツ": "tsu", "テ": "te", "ト": "to",
    "ダ": "da", "ヂ": "ji", "ヅ": "zu", "デ": "de", "ド": "do",
    "ナ": "na", "ニ": "ni", "ヌ": "nu", "ネ": "ne", "ノ": "no",
    "ハ": "ha", "ヒ": "hi", "フ": "fu", "ヘ": "he", "ホ": "ho",
    "バ": "ba", "ビ": "bi", "ブ": "bu", "ベ": "be", "ボ": "bo",
    "パ": "pa", "ピ": "pi", "プ": "pu", "ペ": "pe", "ポ": "po",
    "マ": "ma", "ミ": "mi", "ム": "mu", "メ": "me", "モ": "mo",
    "ヤ": "ya", "ユ": "yu", "ヨ": "yo",
    "ラ": "ra", "リ": "ri", "ル": "ru", "レ": "re", "ロ": "ro",
    "ワ": "wa", "ヰ": "i", "ヱ": "e", "ヲ": "wo", "ン": "n", "ヴ": "vu",
    "ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o",
    "ャ": "ya", "ュ": "yu", "ョ": "yo", "ヮ": "wa", "ヵ": "ka", "ヶ": "ke",
}  # fmt: skip
_PUNCTUATION = str.maketrans({
    "、": ",", "。": ".", "！": "!", "？": "?", "「": '"', "」": '"', "『": '"', "』": '"',
    "（": "(", "）": ")", "・": " ", "〜": "~", "～": "~", "…": "...", "　": " ", "：": ":",
})  # fmt: skip
# Words that keep to the previous one: auxiliaries and verb endings after a
# verb, adjective or auxiliary, and suffixes after anything.
_INFLECTING = {"動詞", "形容詞", "助動詞"}


def hiragana_to_katakana(text: str) -> str:
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in text)


def kana_to_romaji(kana: str) -> str:
    """Modified Hepburn for a katakana (or hiragana) reading."""
    kana = hiragana_to_katakana(kana)
    result: list[str] = []
    double_next = False
    index = 0
    while index < len(kana):
        pair, char = kana[index : index + 2], kana[index]
        if char == "ッ":
            double_next = True
            index += 1
            continue
        if char == "ー":
            # The long vowel mark repeats the vowel before it.
            vowel = next((c for c in reversed("".join(result)) if c in "aeiou"), "")
            result.append(vowel)
            index += 1
            continue
        syllable = _DIGRAPHS.get(pair)
        step = 2
        if syllable is None:
            syllable, step = _MONOGRAPHS.get(char, char), 1
        if double_next and syllable[:1].isalpha() and syllable[0] not in "aeiou":
            syllable = ("t" if syllable.startswith("ch") else syllable[0]) + syllable
        double_next = False
        result.append(syllable)
        index += step
    return "".join(result)


def is_japanese(text: str) -> bool:
    """Japanese, not Chinese: kana anywhere in it."""
    return bool(_KANA.search(text or ""))


class _Reader:
    """MeCab with UniDic Lite, created on first use; MeCab is not thread safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tagger = None
        self.failed = False

    def tagger(self):
        if self._tagger is None and not self.failed:
            try:
                import fugashi

                self._tagger = fugashi.Tagger()
            except Exception:  # missing module, dictionary or a broken MeCab
                LOGGER.info("Romaji indisponível: fugashi ou unidic-lite ausente", exc_info=True)
                self.failed = True
        return self._tagger

    def words(self, line: str) -> list[tuple[str, str, str, str]]:
        """(surface, reading, part of speech, its subtype) of each word."""
        with self._lock:
            tagger = self.tagger()
            if tagger is None:
                return []
            words = []
            for word in tagger(line):
                feature = word.feature
                pos, subtype = getattr(feature, "pos1", ""), getattr(feature, "pos2", "")
                kana = getattr(feature, "kana", None)
                if pos == "助詞":
                    # Particles read as said: は "wa", へ "e".
                    kana = getattr(feature, "pron", None) or kana
                if word.surface in ("を", "ヲ"):
                    kana = "ヲ"
                words.append((word.surface, kana or "", pos or "", subtype or ""))
            return words


_READER = _Reader()


def available() -> bool:
    try:
        import fugashi  # noqa: F401
        import unidic_lite  # noqa: F401
    except ImportError:
        return False
    return not _READER.failed


@lru_cache(maxsize=4096)
def romanize(line: str) -> str:
    """The line in rōmaji; text that is not Japanese passes through."""
    if not _JAPANESE.search(line):
        return line
    # Words that keep to the previous one are read together, so a small tsu
    # at the end of one doubles the next ("yokatta", "matte").
    groups: list[list[str]] = []  # each: [text, kana reading]
    previous_pos = ""
    for surface, kana, pos, subtype in _READER.words(line):
        if not _JAPANESE.search(surface):
            text = surface.translate(_PUNCTUATION).strip()
            if text and pos == "補助記号" and groups:
                groups[-1][0] += text
            elif text:
                groups.append([text, ""])
            previous_pos = pos
            continue
        reading = kana if kana and kana != "*" else surface
        attach = pos == "接尾辞" or (
            previous_pos in _INFLECTING
            and (pos == "助動詞" or subtype in ("接続助詞", "非自立可能"))
        )
        if attach and groups and groups[-1][1]:
            groups[-1][1] += reading
        else:
            groups.append(["", reading])
        previous_pos = pos
    return " ".join(
        (kana_to_romaji(reading) + text) if reading else text for text, reading in groups
    )
