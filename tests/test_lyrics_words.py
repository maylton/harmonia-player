import json

from harmonia.lrc import parse_lrc
from harmonia.lyrics_providers import LyricsPlusClient
from harmonia.lyrics_words import sung_word_count, word_markup
from harmonia.models import LibraryItem


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


def test_the_sung_words_are_lit_and_the_rest_dimmed():
    (line,) = parse_lrc("[00:01.00]<00:01.00>Tom <00:01.50>& <00:02.00>Jerry")
    assert sung_word_count(line, 900) == 0
    assert sung_word_count(line, 1600) == 2
    assert word_markup(line, 0) == '<span alpha="45%">Tom &amp; Jerry</span>'
    assert word_markup(line, 2) == 'Tom &amp; <span alpha="45%">Jerry</span>'
    assert word_markup(line, 3) == "Tom &amp; Jerry"


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
