import time

import pytest

from harmonia.player import NativePlayer


class PlaybinStub:
    def __init__(self, query=(False, 0), seek_result=True):
        self.query = query
        self.seek_result = seek_result
        self.seek_target = None

    def query_position(self, _format):
        return self.query

    def seek_simple(self, _format, _flags, target):
        self.seek_target = target
        return self.seek_result


def player_stub(playbin, last_position=0):
    player = NativePlayer.__new__(NativePlayer)
    player._playbin = playbin
    player._last_position_us = last_position
    player._removed_us = 0
    return player


def test_failed_position_query_preserves_last_valid_value():
    player = player_stub(PlaybinStub(), last_position=42_000_000)

    assert player.position_us == 42_000_000


def test_successful_seek_updates_stable_position_immediately():
    playbin = PlaybinStub(seek_result=True)
    player = player_stub(playbin, last_position=42_000_000)

    assert player.seek(8_500_000)
    assert player._last_position_us == 8_500_000
    assert playbin.seek_target == 8_500_000_000


def test_position_counts_the_silence_skipping_removed():
    player = player_stub(PlaybinStub(query=(True, 9_000_000_000)))
    player._removed_us = 4_000_000

    assert player.position_us == 13_000_000


def _tone_with_a_silence(path) -> None:
    """One second of sound, five of silence, one of sound, as a WAV file."""
    Gst = pytest.importorskip("gi.repository.Gst")
    Gst.init(None)
    caps = "audio/x-raw,format=S16LE,rate=44100,channels=2"
    sources = " ".join(
        f"audiotestsrc num-buffers={count} wave={wave} ! {caps} ! c."
        for count, wave in ((43, "sine"), (215, "silence"), (43, "sine"))
    )
    pipeline = Gst.parse_launch(f"concat name=c ! wavenc ! filesink location={path} {sources}")
    pipeline.set_state(Gst.State.PLAYING)
    pipeline.get_bus().timed_pop_filtered(10 * Gst.SECOND, Gst.MessageType.EOS)
    pipeline.set_state(Gst.State.NULL)


def test_skipping_silence_ends_the_track_instead_of_resuming_it(tmp_path):
    # Squashed timestamps put the sink's position behind the track by the
    # silence removed: the end looked early, and the track was resumed there.
    Gst = pytest.importorskip("gi.repository.Gst")
    from gi.repository import GLib

    Gst.init(None)
    if Gst.ElementFactory.find("removesilence") is None:
        pytest.skip("removesilence (gst-plugins-bad) não está instalado")
    track = tmp_path / "silence.wav"
    _tone_with_a_silence(track)
    loop, ended = GLib.MainLoop(), []
    player = NativePlayer(
        on_error=lambda error: ended.append(error) or loop.quit(),
        on_eos=lambda: ended.append("eos") or loop.quit(),
    )
    player.apply_audio_settings(skip_silence=True)
    player.volume = 0.0
    player.play(track.as_uri())
    GLib.timeout_add_seconds(15, loop.quit)
    start = time.monotonic()
    loop.run()
    player.close()

    assert ended == ["eos"]
    # Seven seconds, less the silence after its first second and a half.
    assert time.monotonic() - start < 5
