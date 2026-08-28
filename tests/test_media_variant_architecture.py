from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARMONIA = ROOT / "src" / "harmonia"


def test_gtk_installs_media_variant_layer_after_video_layer() -> None:
    source = (HARMONIA / "frontend.py").read_text(encoding="utf-8")
    video_install = source.index("install_gtk_video(window_class)")
    variant_install = source.index("install_gtk_media_variants(window_class)")
    assert video_install < variant_install


def test_gtk_independent_video_resolves_its_own_audio_and_restarts() -> None:
    source = (HARMONIA / "gtk_media_variants.py").read_text(encoding="utf-8")
    assert "self.youtube.resolve_stream(stream.video_id)" in source
    assert "IndependentVideoPlayback(stream, audio)" in source
    assert "self.player.replace(playback.audio.url, position_us=0" in source
    assert "_independent_video_primary_position_us" in source
    assert "Ignoring visual EOS" in source


def test_qt_uses_official_video_controller() -> None:
    source = (HARMONIA / "qt_app.py").read_text(encoding="utf-8")
    assert "from .qt_media_variants import OfficialVideoQtController" in source
    assert "video = OfficialVideoQtController(backend, video_sink, engine)" in source


def test_qt_independent_video_resolves_its_own_audio_and_restarts() -> None:
    source = (HARMONIA / "qt_media_variants.py").read_text(encoding="utf-8")
    assert "self.backend.youtube.resolve_stream(stream.video_id)" in source
    assert "IndependentVideoPlayback(stream, audio)" in source
    assert "self.playback.player.replace(" in source
    assert "position_us=0" in source
    assert "_independent_video_primary_position_ms" in source
    assert "Ignoring visual EOS" in source


def test_qt_video_primes_qml_gl_display_and_uses_glsinkbin() -> None:
    source = (HARMONIA / "qt_media_variants.py").read_text(encoding="utf-8")
    assert "self._sink.set_state(Gst.State.READY)" in source
    assert 'Gst.ElementFactory.make("glsinkbin", "harmonia-qt-video-bin")' in source
    assert 'glsinkbin.set_property("sink", self._sink)' in source
    assert 'self._video_player.set_property("video-sink", video_output)' in source
    assert "Qt video output using glsinkbin -> qml6glsink" in source
