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


def test_resolver_falls_back_to_native_and_honors_provider():
    class MissingLrcLib:
        def lyrics(self, item, duration_ms):
            return None

    resolver = LyricsResolver(lambda _video_id: "Letra nativa", MissingLrcLib())
    item = LibraryItem("v", "Faixa", "Artista")
    assert resolver.fetch(item).provider == "YouTube Music"
    assert resolver.fetch(item, provider="lrclib") is None


def test_translation_preserves_line_mapping():
    def opener(request, timeout):
        assert "tl=pt" in request.full_url
        return Response([[["Olá\nMundo", "Hello\nWorld", None, None]]])

    assert GoogleTranslationClient(opener).translate(["Hello", "World"], "pt") == ["Olá", "Mundo"]
