"""Age-restricted tracks: a clear reason, and no retry that cannot help."""

from __future__ import annotations

import pytest

from harmonia.innertube import AgeRestrictedError, InnerTubeClient, InnerTubeError
from harmonia.innertube import client as innertube_client
from harmonia.models import LibraryItem
from harmonia.video import resolve_video_stream
from harmonia.window_playback_recovery import WindowPlaybackRecoveryMixin

# What the clients answered for an age-restricted track, signed in: the web
# player says OK but has only ciphered formats, the others ask for the age.
AGE_GATED = {"status": "LOGIN_REQUIRED", "desktopLegacyAgeGateReason": 1, "reason": "idade"}
CIPHERED_ONLY = {
    "playabilityStatus": {"status": "OK"},
    "streamingData": {"adaptiveFormats": [{"mimeType": "audio/webm", "signatureCipher": "s=x"}]},
}


class PlayerClient(InnerTubeClient):
    def __init__(self, payloads):
        super().__init__("SAPISID=x")
        self.payloads = payloads
        self._bootstrap = lambda: None

    def player_response(self, _video_id, profile):
        return self.payloads.get(profile["name"], {"playabilityStatus": AGE_GATED})


def test_age_gated_track_raises_age_restricted_error():
    innertube_client._STREAM_CACHE.clear()
    client = PlayerClient({"WEB_REMIX": CIPHERED_ONLY})

    with pytest.raises(AgeRestrictedError) as error:
        client.resolve_stream("adult", force=True)
    assert "restrição de idade" in str(error.value)


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
