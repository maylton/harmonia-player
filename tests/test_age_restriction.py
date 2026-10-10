"""Age-restricted tracks: a clear reason, and no retry that cannot help."""

from __future__ import annotations

import pytest

from harmonia.innertube import AgeRestrictedError, InnerTubeClient, InnerTubeError
from harmonia.innertube import client as innertube_client
from harmonia.models import LibraryItem, SearchGroup
from harmonia.song_match import same_recording
from harmonia.video import resolve_video_stream
from harmonia.window_playback_recovery import WindowPlaybackRecoveryMixin

# What the clients answered for an age-restricted track, signed in: the web
# player says OK but has only ciphered formats, the others ask for the age.
AGE_GATED = {"status": "LOGIN_REQUIRED", "desktopLegacyAgeGateReason": 1, "reason": "idade"}
CIPHERED_ONLY = {
    "playabilityStatus": {"status": "OK"},
    "streamingData": {"adaptiveFormats": [{"mimeType": "audio/webm", "signatureCipher": "s=x"}]},
}


DETAILS = {
    "title": "SEQUÊNCIA CUNT",
    "author": "PEDRO SAMPAIO e Tasha Kaiala",
    "lengthSeconds": "130",
}
PLAYABLE = {
    "playabilityStatus": {"status": "OK"},
    "streamingData": {
        "adaptiveFormats": [
            {"mimeType": "audio/webm", "bitrate": 128000, "url": "https://media.example/alt"}
        ]
    },
}


class PlayerClient(InnerTubeClient):
    def __init__(self, payloads, results=(), playable=()):
        super().__init__("SAPISID=x")
        self.payloads = payloads
        self.results = list(results)
        self.playable = set(playable)
        self.searches = []
        self._bootstrap = lambda: None

    def player_response(self, video_id, profile):
        if video_id in self.playable:
            return PLAYABLE
        payload = self.payloads.get(profile["name"], {"playabilityStatus": AGE_GATED})
        return {**payload, "videoDetails": DETAILS}

    def search_category(self, query, category, continuation=None):
        self.searches.append((query, category))
        return SearchGroup(category, category, self.results if category == "videos" else [])


def test_age_gated_track_raises_age_restricted_error():
    innertube_client._STREAM_CACHE.clear()
    client = PlayerClient({"WEB_REMIX": CIPHERED_ONLY})

    with pytest.raises(AgeRestrictedError) as error:
        client.resolve_stream("adult", force=True)
    assert "restrição de idade" in str(error.value)
    assert client.searches  # it looked for another publication first


def test_age_gated_track_plays_another_publication_of_the_same_song():
    innertube_client._STREAM_CACHE.clear()
    results = [
        LibraryItem("live", "SEQUÊNCIA CUNT (Live)", "PEDRO SAMPAIO • 1 mi • 2:05", kind="videos"),
        LibraryItem(
            "artist-upload",
            "SEQUÊNCIA CUNT (part. CLEMENTAUM)",
            "Tasha Kaiala, PEDRO SAMPAIO • 3,7 mi de visualizações • 2:11",
            kind="videos",
        ),
    ]
    client = PlayerClient({"WEB_REMIX": CIPHERED_ONLY}, results, playable={"live", "artist-upload"})

    stream = client.resolve_stream("adult", force=True)

    assert stream.url == "https://media.example/alt"
    assert stream.substitute_id == "artist-upload"
    assert client.resolve_stream("adult") is stream  # cached under the track


def test_substitutes_are_never_resolved_recursively():
    innertube_client._STREAM_CACHE.clear()
    match = LibraryItem("also-adult", "SEQUÊNCIA CUNT", "PEDRO SAMPAIO • 2:10", kind="videos")
    client = PlayerClient({"WEB_REMIX": CIPHERED_ONLY}, [match])

    with pytest.raises(AgeRestrictedError):
        client.resolve_stream("adult", force=True)
    assert len(client.searches) == 2  # songs and videos, once


@pytest.mark.parametrize(
    ("title", "subtitle", "expected"),
    [
        ("SEQUÊNCIA CUNT (part. Clementaum)", "PEDRO SAMPAIO e Tasha Kaiala • 2,7 mi • 2:11", True),
        (
            "SEQUÊNCIA CUNT",
            "Tasha Kaiala, PEDRO SAMPAIO • SEQUÊNCIA CUNT • 2:10 · Tocou 1 mi",
            True,
        ),
        ("SEQUÊNCIA CUNT (Live Finale)", "PEDRO SAMPAIO • 42 mil • 2:09", False),
        ("SEQUÊNCIA CUNT - Pedro Sampaio, Tasha Kaiala", "FitDance • 129 mil • 2:07", False),
        ("SEQUÊNCIA CUNT | Coreografia", "PEDRO SAMPAIO e Tasha Kaiala • 1 mil • 2:11", False),
        ("SEQUÊNCIA CUNT", "Outra Banda • 2 mil • 2:11", False),
        ("SEQUÊNCIA FEITICEIRA", "PEDRO SAMPAIO e Tasha Kaiala • 1 mi • 2:11", False),
        ("SEQUÊNCIA CUNT", "PEDRO SAMPAIO e Tasha Kaiala • 1 mi", False),
    ],
)
def test_same_recording_is_strict(title, subtitle, expected):
    candidate = LibraryItem("x", title, subtitle, kind="videos")
    assert (
        same_recording("SEQUÊNCIA CUNT", "PEDRO SAMPAIO e Tasha Kaiala", 130, candidate) is expected
    )


def test_other_failures_keep_the_per_client_report():
    innertube_client._STREAM_CACHE.clear()
    unavailable = {"playabilityStatus": {"status": "UNPLAYABLE", "reason": "indisponível"}}
    client = PlayerClient(dict.fromkeys(("VISIONOS", "ANDROID_MUSIC", "IOS", "ANDROID_VR",
                                         "WEB_REMIX"), unavailable))  # fmt: skip

    with pytest.raises(InnerTubeError) as error:
        client.resolve_stream("gone", force=True)
    assert not isinstance(error.value, AgeRestrictedError)
    assert "VISIONOS: indisponível" in str(error.value)


def test_age_gated_video_raises_age_restricted_error():
    item = LibraryItem("adult-video", "Song", "Artist", kind="videos")
    client = PlayerClient({"WEB_REMIX": CIPHERED_ONLY})

    with pytest.raises(AgeRestrictedError):
        resolve_video_stream(client, item, force=True)


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
