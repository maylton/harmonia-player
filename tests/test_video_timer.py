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

    State = gtk_video.Gst.State
    release = threading.Event()
    applied = []

    class Playbin:
        def set_state(self, state):
            applied.append((state, threading.current_thread() is threading.main_thread()))
            if state == State.READY:
                release.wait(5)  # waiting on a streaming thread that never returns

    class Window(gtk_video.GtkVideoMixin):
        _gtk_video_player = Playbin()

    window = Window()
    start = time.monotonic()
    window._stop_gtk_video_state()  # down to READY: on its own thread
    assert time.monotonic() - start < 1
    # While it runs nothing goes up, which would wait for its state lock.
    window._set_gtk_video_state(State.PAUSED)
    assert window._gtk_video_stopping()
    release.set()
    for _ in range(100):
        if not window._gtk_video_stopping():
            break
        threading.Event().wait(0.02)
    assert not window._gtk_video_stopping()
    # Up, on the main loop, where gtk4paintablesink prepares itself.
    window._set_gtk_video_state(State.PAUSED)
    assert applied == [(State.READY, False), (State.PAUSED, True)]
