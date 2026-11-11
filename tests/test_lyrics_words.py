import json

import pytest

from harmonia.lrc import parse_lrc
from harmonia.lyrics_providers import LyricsPlusClient
from harmonia.lyrics_words import word_glow, word_progress, word_spans, word_wobble
from harmonia.models import LibraryItem, LyricWord


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def read(self):
        return json.dumps(self.payload).encode()


def test_enhanced_lrc_times_each_word_and_hides_the_tags():
    lines = parse_lrc(
        "[offset:+100]\n[00:12.00]<00:12.00>Hello <00:12.50>dear <00:13.00>world<00:14.00>\n"
        "[00:15.00]Plain line\n"
    )
    first, plain = lines
    assert first.text == "Hello dear world"
    assert [(w.start_ms, w.end_ms, w.text) for w in first.words] == [
        (12_100, 12_600, "Hello "),
        (12_600, 13_100, "dear "),
        (13_100, 14_100, "world"),
    ]
    assert plain.text == "Plain line" and plain.words == ()


def test_each_word_has_its_span_without_the_spacing():
    (line,) = parse_lrc("[00:01.00]<00:01.00>Tom <00:01.50>& <00:02.00>Jerry")
    text, spans = word_spans(line)
    assert text == "Tom & Jerry"
    assert [text[start:end] for start, end, _word in spans] == ["Tom", "&", "Jerry"]


def test_words_fill_as_they_are_sung_like_metrolist():
    (line,) = parse_lrc("[00:01.00]<00:01.00>Tom <00:01.50>& <00:02.00>Jerry")
    tom, _and, jerry = line.words
    assert word_progress(tom, 900) == 0 and word_progress(tom, 1250) == 0.5
    assert word_progress(tom, 1600) == 1
    # The last word has no end of its own: it still fills over a moment.
    assert 0 < word_progress(jerry, 2100) < 1
    # The pulse peaks 125 ms into the word and is gone by 750 ms.
    assert word_wobble(tom, 1125) == 1 and word_wobble(tom, 1000) == 0
    assert word_wobble(tom, 1800) == 0
    assert word_glow(tom, 0) == word_glow(tom, 1) == 0


LYRICSPLUS_WORD = {
    "type": "Word",
    "lyrics": [
        {
            "time": 27395,
            "duration": 1565,
            "text": "I been tryna call",
            "syllabus": [
                {"time": 27395, "duration": 154, "text": "I "},
                {"time": 27549, "duration": 191, "text": "been "},
                {"time": 27740, "duration": 337, "text": "e"},
                {"time": 28077, "duration": 883, "text": "nough"},
                {"time": 29000, "duration": 300, "text": "(ooh)", "isBackground": True},
            ],
        }
    ],
}
LYRICSPLUS_LINE = {
    "type": "Line",
    "lyrics": [{"time": 12220, "duration": 4680, "text": "Quando eu digo"}],
}


def test_lyricsplus_document_keeps_words_and_leaves_out_background_vocals():
    document = LyricsPlusClient.document(LYRICSPLUS_WORD)
    (line,) = document.synced
    assert document.provider == "LyricsPlus"
    assert line.text == "I been enough"
    assert [word.text for word in line.words] == ["I ", "been ", "e", "nough"]
    assert line.words[-1].end_ms == 28960
    by_line = LyricsPlusClient.document(LYRICSPLUS_LINE)
    assert by_line.synced[0].words == () and by_line.synced[0].start_ms == 12220
    assert LyricsPlusClient.document({"lyrics": []}) is None


def test_lyricsplus_prefers_the_mirror_with_word_timing():
    requests = []

    def opener(request, timeout):
        requests.append(request.full_url)
        if "binimum" in request.full_url:
            return Response(LYRICSPLUS_LINE)
        return Response(LYRICSPLUS_WORD)

    item = LibraryItem("v", "Blinding Lights (Official Audio)", "The Weeknd · After Hours")
    document = LyricsPlusClient(opener).lyrics(item, 200_400)
    assert document.synced[0].words  # the second mirror had it by word
    assert "title=Blinding+Lights&artist=The+Weeknd&duration=200" in requests[0]
    assert len(requests) == 2


def test_lyricsplus_mirrors_down_report_the_error():
    import urllib.error

    import pytest

    def opener(request, timeout):
        raise urllib.error.URLError("offline")

    item = LibraryItem("v", "Faixa", "Artista")
    with pytest.raises(urllib.error.URLError):
        LyricsPlusClient(opener).lyrics(item)
    # Without an artist the services cannot match anything.
    assert LyricsPlusClient(opener).lyrics(LibraryItem("v", "Faixa")) is None


def test_letters_light_up_one_after_another_through_the_word():
    from harmonia.lyrics_words import letter_progress

    word = LyricWord(1000, 1400, "love ")
    # Four letters and the space share 400 ms: the second fills from 80 to 160 ms.
    assert letter_progress(word, 1080, 1, 5) == 0
    assert letter_progress(word, 1120, 1, 5) == pytest.approx(0.5)
    assert letter_progress(word, 1160, 1, 5) == 1
    assert letter_progress(word, 1400, 4, 5) == pytest.approx(1)


def test_a_letter_bumps_only_while_the_fill_crosses_it():
    from harmonia.lyrics_words import letter_nudge

    assert letter_nudge(0.5, 0.0) == 0 and letter_nudge(0.5, 1.0) == pytest.approx(0, abs=1e-6)
    assert 0 < letter_nudge(0.5, 0.25) < 0.038
    assert letter_nudge(1.0, 0.25) == 0  # the word is sung: back at rest


def test_hyphenated_syllables_form_a_growing_group():
    from harmonia.lyrics_words import crescendo, hyphen_groups

    words = (LyricWord(0, 200, "lo-"), LyricWord(200, 400, "ve-"), LyricWord(400, 900, "ly "),
             LyricWord(900, 1200, "day"))  # fmt: skip
    groups = hyphen_groups(words)
    assert groups == {0: (0, 3, 0, 900), 1: (1, 3, 0, 900), 2: (2, 3, 0, 900)}
    # Later syllables are a little larger; well after the group it settles.
    assert crescendo(groups[1], 1.0, 500) > crescendo(groups[0], 1.0, 500)
    assert crescendo(groups[2], 1.0, 2000) == 0
