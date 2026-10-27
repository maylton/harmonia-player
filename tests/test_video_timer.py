import pytest

pytest.importorskip("gi")


def test_the_video_sync_timer_runs_only_while_a_video_plays(monkeypatch):
    from harmonia import gtk_video

    scheduled = []
    monkeypatch.setattr(
        gtk_video.GLib, "timeout_add", lambda interval, callback: scheduled.append(callback) or 7
    )

    class Window(gtk_video.GtkVideoMixin):
        _gtk_video_sync_source = 0
        _media_mode = "video"
        _media_switch_loading = True

    window = Window()
    window._watch_gtk_video_transport()
    window._watch_gtk_video_transport()
    assert len(scheduled) == 1 and window._gtk_video_sync_source == 7

    assert window._sync_gtk_video_transport() is gtk_video.GLib.SOURCE_CONTINUE
    window._media_mode = "audio"
    assert window._sync_gtk_video_transport() is gtk_video.GLib.SOURCE_REMOVE
    assert window._gtk_video_sync_source == 0
    window._watch_gtk_video_transport()  # the next video starts it again
    assert len(scheduled) == 2


def test_a_stuck_video_pipeline_does_not_hold_the_main_loop():
    import threading
    import time

    from harmonia import gtk_video

    release = threading.Event()
    applied = []

    class Playbin:
        def set_state(self, state):
            applied.append(state)
            release.wait(5)  # READY waiting on a streaming thread that never returns

    class Window(gtk_video.GtkVideoMixin):
        _gtk_video_player = Playbin()

    window = Window()
    start = time.monotonic()
    window._set_gtk_video_state(gtk_video.Gst.State.READY)
    window._set_gtk_video_state(gtk_video.Gst.State.PAUSED)  # queued behind it
    assert time.monotonic() - start < 1
    release.set()
    for _ in range(100):
        if len(applied) == 2:
            break
        threading.Event().wait(0.02)
    assert applied == [gtk_video.Gst.State.READY, gtk_video.Gst.State.PAUSED]
