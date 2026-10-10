"""Age-restricted tracks: their original stream, or a clear reason why not."""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import pytest

from harmonia import js_runtime
from harmonia.innertube import AgeRestrictedError, InnerTubeClient, InnerTubeError, restricted
from harmonia.innertube import client as innertube_client
from harmonia.innertube.challenges import NoJsRuntimeError, Player, PlayerChallenges
from harmonia.models import LibraryItem
from harmonia.video import resolve_video_stream
from harmonia.window_playback_recovery import WindowPlaybackRecoveryMixin

# What the usual clients answer for an age-restricted track, even signed in.
AGE_GATED = {"playabilityStatus": {"status": "LOGIN_REQUIRED", "desktopLegacyAgeGateReason": 1}}
# The TV client's answer once its URLs are decrypted (restricted.py).
ORIGINAL = {
    "playabilityStatus": {"status": "OK"},
    "streamingData": {
        "adaptiveFormats": [
            {"mimeType": "audio/webm", "bitrate": 128000, "itag": 251, "url": "https://g/a?sig=1"},
            {"mimeType": "audio/webm", "bitrate": 266000, "itag": 774, "url": "https://g/b?sig=2"},
            {
                "mimeType": "video/mp4",
                "bitrate": 900000,
                "itag": 136,
                "height": 720,
                "contentLength": "1000",
                "initRange": {"start": "0", "end": "10"},
                "indexRange": {"start": "11", "end": "20"},
                "url": "https://g/v?sig=3",
            },
        ],
        "formats": [{"mimeType": "video/mp4", "itag": 18, "height": 360, "url": "https://g/m"}],
    },
}


class PlayerClient(InnerTubeClient):
    def __init__(self, restricted_payload=None, error=None, cookie="SAPISID=x"):
        super().__init__(cookie)
        self._bootstrap = lambda: None
        self.restricted_payload = restricted_payload
        self.error = error
        self.restricted_calls = 0

    def player_response(self, _video_id, _profile):
        return AGE_GATED

    def restricted_player_response(self, _video_id):
        self.restricted_calls += 1
        if self.error:
            raise self.error
        return json.loads(json.dumps(self.restricted_payload))


def test_age_gated_track_plays_its_original_stream():
    innertube_client._STREAM_CACHE.clear()
    client = PlayerClient(ORIGINAL)

    stream = client.resolve_stream("adult", force=True)

    assert (stream.client, stream.url, stream.bitrate) == ("TVHTML5", "https://g/b?sig=2", 266000)
    assert client.restricted_calls == 1  # not once per refusing client
    assert client.resolve_stream("adult") is stream


@pytest.mark.parametrize(
    ("error", "cookie", "expected"),
    [
        (NoJsRuntimeError("none"), "SAPISID=x", "interpretador JavaScript"),
        (InnerTubeError("TVHTML5: HTTP 403"), "SAPISID=x", "HTTP 403"),
        (None, "", "entre na sua conta"),
    ],
)
def test_age_gated_track_says_why_its_original_stream_did_not_open(error, cookie, expected):
    innertube_client._STREAM_CACHE.clear()
    client = PlayerClient(ORIGINAL, error=error, cookie=cookie)

    with pytest.raises(AgeRestrictedError) as raised:
        client.resolve_stream("adult", force=True)
    assert expected in str(raised.value)


def test_other_failures_keep_the_per_client_report():
    innertube_client._STREAM_CACHE.clear()
    client = PlayerClient()
    client.player_response = lambda *_args: {
        "playabilityStatus": {"status": "UNPLAYABLE", "reason": "indisponível"}
    }

    with pytest.raises(InnerTubeError) as error:
        client.resolve_stream("gone", force=True)
    assert not isinstance(error.value, AgeRestrictedError)
    assert client.restricted_calls == 0
    assert "VISIONOS: indisponível" in str(error.value)


def test_age_gated_video_uses_the_original_indexed_formats(monkeypatch):
    monkeypatch.setattr("harmonia.video._probe_stream", lambda *_args: True)
    item = LibraryItem("adult-video", "Song", "Artist", kind="videos")

    stream = resolve_video_stream(PlayerClient(ORIGINAL), item, force=True, allow_video_only=True)

    assert (stream.client, stream.itag, stream.height) == ("TVHTML5", 136, 720)


def test_age_gated_video_without_engine_says_so():
    item = LibraryItem("adult-video-2", "Song", "Artist", kind="videos")
    client = PlayerClient(error=NoJsRuntimeError("none"))

    with pytest.raises(AgeRestrictedError) as raised:
        resolve_video_stream(client, item, force=True)
    assert "interpretador JavaScript" in str(raised.value)


class FakeChallenges:
    def __init__(self):
        self.calls = []

    def player(self):
        return Player("abcd1234", 20000)

    def solve(self, player, n, sig):
        self.calls.append((sorted(set(n)), sorted(set(sig))))
        return {value: value.upper() for value in n}, {value: value[::-1] for value in sig}


def test_decrypt_formats_answers_every_challenge_in_one_run():
    formats = [
        {"signatureCipher": "s=abc&sp=sig&url=https%3A%2F%2Fg%2Fa%3Fn%3Dxy%26itag%3D251"},
        {"signatureCipher": "s=def&url=https%3A%2F%2Fg%2Fb%3Fn%3Dxy"},
        {"url": "https://g/c?n=zz"},
        {"signatureCipher": "s=only"},  # no URL at all
    ]
    challenges = FakeChallenges()

    restricted.decrypt_formats(formats, challenges=challenges)

    assert challenges.calls == [(["xy", "zz"], ["abc", "def"])]  # the URL-less one is skipped
    assert formats[0]["url"] == "https://g/a?n=XY&itag=251&sig=cba"
    assert formats[1]["url"] == "https://g/b?n=XY&signature=fed"
    assert formats[2]["url"] == "https://g/c?n=ZZ"
    assert "url" not in formats[3]


class Runtime:
    name = "fake"

    def __init__(self):
        self.scripts = []

    def run(self, body, result):
        assert "Object.assign(globalThis, lib)" in body
        data = json.loads(result.removeprefix("JSON.stringify(jsc(").removesuffix("))"))
        self.scripts.append(data["type"])
        return json.dumps(
            {
                "type": "result",
                "preprocessed_player": "PRE" if data.get("output_preprocessed") else None,
                "responses": [
                    {"type": "result", "data": {c: c + "!" for c in r["challenges"]}}
                    for r in data["requests"]
                ],
            }
        )


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_player_challenges_cache_the_player_and_its_preprocessed_copy(tmp_path):
    fetched = []

    def opener(request):
        fetched.append(request.full_url)
        if request.full_url.endswith("iframe_api"):
            return Response(
                rb"var x='https:\/\/www.youtube.com\/s\/player\/abcd1234\/www-widgetapi.vflset';"
            )
        return Response(b"var cfg={signatureTimestamp:20732};")

    runtime = Runtime()
    challenges = PlayerChallenges(tmp_path, lambda: runtime, opener)

    player = challenges.player()
    first = challenges.solve(player, ["n1"], ["s1"])
    second = challenges.solve(challenges.player(), ["n2"], [])

    assert player == Player("abcd1234", 20732)
    assert first == ({"n1": "n1!"}, {"s1": "s1!"})
    assert second == ({"n2": "n2!"}, {})
    assert runtime.scripts == ["player", "preprocessed"]
    assert len(fetched) == 2  # the id once, the player once
    assert (tmp_path / "abcd1234.pre.js").read_text(encoding="utf-8") == "PRE"


def test_player_challenges_without_engine_raise_no_js_runtime(tmp_path):
    challenges = PlayerChallenges(tmp_path, lambda: None, lambda _request: None)
    with pytest.raises(NoJsRuntimeError):
        challenges.solve(Player("abcd1234", 1), ["n"], [])


def test_forced_runtime_and_javascriptcore_adapter(monkeypatch):
    js_runtime.find_runtime.cache_clear()
    monkeypatch.setenv("HARMONIA_JS_RUNTIME", "/opt/qjs")
    forced = js_runtime.find_runtime()
    js_runtime.find_runtime.cache_clear()
    assert (forced.name, forced.path, forced.arguments) == ("qjs", "/opt/qjs", ("--script",))

    class Value:
        def to_string(self):
            return "42"

    class Context:
        @staticmethod
        def new():
            return Context()

        def evaluate(self, code, _length):
            assert code.endswith(";6*7")
            return Value()

        def get_exception(self):
            return None

    class Module:
        pass

    Module.Context = Context
    assert js_runtime.JavaScriptCoreRuntime(Module).run("var a = 1;", "6*7") == "42"


QJS = shutil.which("qjs") or (
    "C:/msys64/ucrt64/bin/qjs.exe" if Path("C:/msys64/ucrt64/bin/qjs.exe").is_file() else None
)


def _solver_body() -> str:
    solver = Path(restricted.__file__).with_name("ejs")
    return "\n".join(
        (
            (solver / "lib.min.js").read_text(encoding="utf-8"),
            "Object.assign(globalThis, lib);",
            (solver / "core.min.js").read_text(encoding="utf-8"),
        )
    )


@pytest.mark.skipif(QJS is None, reason="QuickJS não instalado")
def test_bundled_solver_loads_in_quickjs():
    runtime = js_runtime.ProcessRuntime("qjs", QJS, ("--script",))
    assert runtime.run(_solver_body(), "typeof jsc") == "function"


def test_bundled_solver_loads_in_javascriptcore():
    runtime = js_runtime._javascriptcore()
    if runtime is None:
        pytest.skip("JavaScriptCore não disponível")
    assert runtime.run(_solver_body(), "typeof jsc") == "function"


class Toasts:
    def __init__(self):
        self.titles = []

    def add_toast(self, toast):
        self.titles.append(toast.get_title())


class Button:
    def set_sensitive(self, _value):
        pass

    def set_icon_name(self, _value):
        pass


class Window(WindowPlaybackRecoveryMixin):
    def __init__(self):
        self._play_request = 7
        self._stream_ready = True
        self._stream_recovery_attempts = 0
        self.current_item = LibraryItem("adult", "Song", "Artist")
        self.play_button = self.expanded_play_button = Button()
        self.toast_overlay = Toasts()
        self.youtube = None  # a retry would fail on it


def test_gtk_reports_a_final_error_without_renewing_the_stream(monkeypatch):
    pytest.importorskip("gi")
    monkeypatch.setattr(
        "harmonia.window_playback_recovery.playback_report", lambda *_args: "relatório"
    )
    window = Window()

    window._play_request_error(7, "Esta faixa tem restrição de idade", False)

    assert window._stream_recovery_attempts == 0
    assert window._stream_ready is False
    assert window.toast_overlay.titles == ["Esta faixa tem restrição de idade"]
