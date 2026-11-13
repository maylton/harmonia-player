import json
import urllib.error

from harmonia.lyrics import GoogleTranslationClient, LrcLibClient, LyricsResolver, parse_lrc
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


def test_parse_lrc_multiple_timestamps_metadata_and_offset():
    lines = parse_lrc(
        "[ar:Artista]\n[offset:+150]\n[00:01.25][00:03.500]Primeira\n[1:02:03.004]Longa\n"
    )
    assert [(line.start_ms, line.text) for line in lines] == [
        (1400, "Primeira"),
        (3650, "Primeira"),
        (3_723_154, "Longa"),
    ]


def test_lrclib_builds_synced_document_and_uses_duration():
    requests = []

    def opener(request, timeout):
        requests.append((request.full_url, timeout, request.headers))
        return Response(
            {
                "plainLyrics": "Um\nDois",
                "syncedLyrics": "[00:01.00]Um\n[00:02.50]Dois",
            }
        )

    item = LibraryItem("video", "Canção (Official Audio)", "Artista · Álbum", kind="songs")
    document = LrcLibClient(opener).lyrics(item, 185_400)
    assert document and document.provider == "LRCLIB" and document.is_synced
    assert [line.start_ms for line in document.synced] == [1000, 2500]
    assert "track_name=Can%C3%A7%C3%A3o" in requests[0][0]
    assert "duration=185" in requests[0][0]


def test_lrclib_search_fallback_selects_closest_duration():
    def opener(request, timeout):
        if "/get?" in request.full_url:
            raise urllib.error.HTTPError(request.full_url, 404, "missing", {}, None)
        return Response(
            [
                {"duration": 100, "plainLyrics": "Errada"},
                {"duration": 201, "syncedLyrics": "[00:01]Certa"},
            ]
        )

    document = LrcLibClient(opener).lyrics(LibraryItem("v", "Faixa", "Artista"), 200_000)
    assert document and document.display_text == "Certa"


class Missing:
    def lyrics(self, item, duration_ms):
        return None


class Fixed:
    def __init__(self, document=None, error=None):
        self.document, self.error = document, error

    def lyrics(self, item, duration_ms):
        if self.error:
            raise self.error
        return self.document


def test_resolver_falls_back_to_native_and_honors_provider():
    resolver = LyricsResolver(lambda _video_id: "Letra nativa", Missing(), Missing(), Missing())
    item = LibraryItem("v", "Faixa", "Artista")
    assert resolver.fetch(item).provider == "YouTube Music"
    # A chosen service with nothing falls back to the others, the native last.
    assert resolver.fetch(item, provider="lrclib").provider == "YouTube Music"


def test_resolver_prefers_lyrics_timed_by_word():
    from harmonia.models import LyricLine, LyricsDocument, LyricWord

    by_word = LyricsDocument(
        "Um", "LyricsPlus", [LyricLine(0, "Um", words=(LyricWord(0, 500, "Um"),))]
    )
    by_line = LyricsDocument("Um", "LyricsPlus", [LyricLine(0, "Um")])
    lrclib = LyricsDocument("Um", "LRCLIB", [LyricLine(0, "Um")])
    item = LibraryItem("v", "Faixa", "Artista")

    def native(_video_id):
        return None

    assert LyricsResolver(native, Fixed(lrclib), Fixed(by_word), Missing()).fetch(item) is by_word
    # LRCLIB wins over LyricsPlus timed by line; LyricsPlus fills in when LRCLIB fails.
    assert LyricsResolver(native, Fixed(lrclib), Fixed(by_line), Missing()).fetch(item) is lrclib
    failing = Fixed(error=OSError("offline"))
    assert LyricsResolver(native, failing, Fixed(by_line), Missing()).fetch(item) is by_line
    assert LyricsResolver(native, Missing(), failing, Missing()).fetch(item) is None


def test_translation_preserves_line_mapping():
    def opener(request, timeout):
        assert "tl=pt" in request.full_url
        return Response([[["Olá\nMundo", "Hello\nWorld", None, None]]])

    assert GoogleTranslationClient(opener).translate(["Hello", "World"], "pt") == ["Olá", "Mundo"]


class Slow:
    def __init__(self, seconds, document=None):
        self.seconds, self.document = seconds, document

    def lyrics(self, _item, _duration_ms=0):
        import time

        time.sleep(self.seconds)
        return self.document


def test_the_services_are_asked_together_and_a_slow_one_does_not_hold_the_lyrics():
    import time

    from harmonia.models import LyricLine, LyricsDocument, LyricWord

    by_word = LyricsDocument(
        "Um", "BetterLyrics", [LyricLine(0, "Um", words=(LyricWord(0, 5, "Um"),))]
    )
    lrclib = LyricsDocument("Um", "LRCLIB", [LyricLine(0, "Um")])
    item = LibraryItem("v", "Faixa", "Artista")
    resolver = LyricsResolver(lambda _id: None, Fixed(lrclib), Slow(5), Fixed(by_word))
    started = time.monotonic()
    assert resolver.fetch(item, 200_000) is by_word  # LyricsPlus still answering
    assert time.monotonic() - started < 1

    resolver = LyricsResolver(lambda _id: None, Fixed(lrclib), Slow(5), Missing())
    resolver.WORD_GRACE = 0.2
    started = time.monotonic()
    assert resolver.fetch(item, 200_000) is lrclib  # by line, after a short wait for words
    assert time.monotonic() - started < 1

    # By line too, BetterLyrics comes before LRCLIB.
    better_by_line = LyricsDocument("Um", "BetterLyrics", [LyricLine(0, "Um")])
    resolver = LyricsResolver(lambda _id: None, Fixed(lrclib), Missing(), Fixed(better_by_line))
    resolver.WORD_GRACE = 0.2
    assert resolver.fetch(item, 200_000) is better_by_line


def test_betterlyrics_reads_apple_musics_ttml_word_by_word():
    from harmonia.lyrics_providers.betterlyrics import parse_ttml, search_title

    ttml = (
        '<tt xmlns="http://www.w3.org/ns/ttml" xmlns:ttm="http://www.w3.org/ns/ttml#metadata">'
        '<body><div><p begin="0.155" end="3.9"><span begin="0.155" end="0.587">Ab</span>'
        '<span begin="0.587" end="0.72">ra,</span> <span begin="1.4" end="1.9">hey</span>'
        '<span ttm:role="x-bg" begin="2.0" end="3.0"><span begin="2.0" end="3.0">(oh)</span></span>'
        '</p><p begin="1:04.5"><span begin="1:04.5" end="1:05">Fim</span></p></div></body></tt>'
    )
    document = parse_ttml(ttml)
    assert [line.text for line in document.synced] == ["Abra, hey", "(oh)", "Fim"]
    assert [word.text for word in document.synced[0].words] == ["Ab", "ra, ", "hey"]
    assert document.synced[2].start_ms == 64_500
    assert search_title("Poker Face (Official Video) [Remastered]") == "Poker Face"


def test_play_and_view_counts_are_not_taken_for_the_artist():
    from harmonia.lyrics_providers.common import lyrics_metadata

    assert lyrics_metadata(LibraryItem("v", "Me Voy", "Tocou 151\xa0mi vezes · 3:36"))[0] == ""
    assert lyrics_metadata(LibraryItem("v", "X", "Música · RBD · 2,1 mi visualizações"))[0] == "RBD"
    assert lyrics_metadata(LibraryItem("v", "X", "Song · Kelis · 3M plays"))[0] == "Kelis"


def test_the_subtitle_gives_the_length_before_the_stream_does():
    from harmonia.lyrics_providers.common import duration_from_subtitle

    assert duration_from_subtitle(LibraryItem("v", "X", "Tocou 151\xa0mi vezes · 3:36")) == 216_000
    assert duration_from_subtitle(LibraryItem("v", "X", "Música · Kelis · 1:02:05")) == 3_725_000
    assert duration_from_subtitle(LibraryItem("v", "X", "Música · Kelis")) == 0


def test_a_chosen_service_with_nothing_falls_back_to_the_others():
    from harmonia.models import LyricLine, LyricsDocument

    lrclib = LyricsDocument("Um", "LRCLIB", [LyricLine(0, "Um")])
    item = LibraryItem("v", "Faixa", "Artista")
    down = Fixed(error=OSError("todos os espelhos fora"))
    resolver = LyricsResolver(lambda _id: None, Fixed(lrclib), down, Missing())
    resolver.WORD_GRACE = 0.1
    assert resolver.fetch(item, 200_000, "lyricsplus") is lrclib
    assert resolver.fetch(item, 200_000, "lrclib") is lrclib
