from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARMONIA = ROOT / "src" / "harmonia"


def test_gtk_media_variant_layer_wraps_the_video_layer_which_wraps_playback() -> None:
    source = (HARMONIA / "app.py").read_text(encoding="utf-8")
    start = source.index("class HarmoniaWindow(")
    bases = source[start : source.index("):", start)]
    # super() resolves in base order: variants, then video, then playback.
    assert bases.index("GtkMediaVariantsMixin") < bases.index("GtkVideoMixin")
    assert bases.index("GtkVideoMixin") < bases.index("WindowPlaybackMixin")
    assert "self._video_feature_init()" in source


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
    # The base controller binds the surface and plays into _video_output().
    assert "def _video_output(self):" in source and "return video_output" in source
    base = (HARMONIA / "qt_video.py").read_text(encoding="utf-8")
    assert 'self._video_player.set_property("video-sink", self._video_output())' in base
    assert "self._qt_glsinkbin = glsinkbin" in source
    assert "self._qt_video_output = video_output" in source
