import re
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

QML = Path(__file__).resolve().parents[1] / "src" / "harmonia" / "qml"


def test_every_name_qml_uses_is_still_on_the_controller():
    from harmonia.qt_integrations import QtIntegrationsController

    used = set()
    for qml in QML.glob("*.qml"):
        used |= set(re.findall(r"\bintegrations\.(\w+)", qml.read_text(encoding="utf-8")))
    assert used
    assert sorted(name for name in used if not hasattr(QtIntegrationsController, name)) == []


def make_context(playback=None, storage=None):
    from harmonia.preferences import Preferences
    from harmonia.qt_integration_context import IntegrationContext

    events = {"jobs": [], "status": [], "saved": 0, "changed": 0}

    def run(job, operation):
        events["jobs"].append(job.name)
        try:
            result, error = operation(), ""
        except Exception as exc:
            result, error = None, str(exc)
        if error:
            if job.on_failure:
                job.on_failure(error)
        elif job.on_done:
            job.on_done(result)

    def save():
        events["saved"] += 1

    def changed():
        events["changed"] += 1

    context = IntegrationContext(
        settings=SimpleNamespace(values=Preferences()),
        playback=playback,
        storage=storage,
        set_status=lambda text, error=False: events["status"].append((text, error)),
        run=run,
        save_preferences=save,
        changed=changed,
    )
    return context, events


def test_failed_jobs_report_with_their_label_or_stay_silent():
    from harmonia.qt_integration_context import Job
    from harmonia.qt_integrations import QtIntegrationsController

    status, failures = [], []
    stub = SimpleNamespace(backend=SimpleNamespace(_set_status=lambda *a, **k: status.append(a)))
    finished = QtIntegrationsController._job_finished
    finished(stub, Job("quiet", on_failure=failures.append), None, "boom")
    finished(stub, Job("loud", failure_label="Não deu"), None, "boom")
    done = []
    finished(stub, Job("ok", on_done=done.append), 42, "")
    assert failures == ["boom"] and status == [("Não deu: boom",)] and done == [42]


def test_lastfm_scrobbles_each_track_once(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    from harmonia.qt_lastfm import LastFmBridge
    from harmonia.social import LastFmCredentials, LastFmSession
    from harmonia.storage import Storage

    playback = SimpleNamespace(duration=200_000, position=150_000)
    context, events = make_context(playback, Storage())
    lastfm = LastFmBridge(context)
    lastfm.set_enabled(True)
    assert context.settings.values.lastfm_enabled is False  # not authorized yet
    lastfm.credentials.save(LastFmCredentials("secret", LastFmSession("eu", "key")))
    lastfm.set_enabled(True)
    scrobbled = []
    monkeypatch.setattr(
        lastfm, "client", lambda **_: SimpleNamespace(scrobble=lambda *a: scrobbled.append(a))
    )
    item = SimpleNamespace(title="Faixa")
    lastfm.position_changed(item, 1000)
    lastfm.position_changed(item, 1000)
    assert scrobbled == [(item, 1000, 200_000)]


def test_together_follows_the_host_and_ignores_old_states():
    from harmonia.models import LibraryItem
    from harmonia.qt_together import TogetherBridge
    from harmonia.together import TogetherState

    track = LibraryItem("v", "Faixa")
    calls = []
    playback = SimpleNamespace(
        current_item=None,
        load_shared_state=lambda queue, index, position: calls.append((index, position)),
    )
    context, _events = make_context(playback)
    together = TogetherBridge(context, lambda: None)
    together.apply(TogetherState([track], 0, 5000, False, revision=2))
    together.apply(TogetherState([track], 0, 9000, False, revision=1))
    assert calls == [(0, 5000)]


def test_cast_is_the_remote_transport_while_connected(monkeypatch):
    from harmonia.qt_cast import CastBridge

    sent = []
    renderer = SimpleNamespace(
        pause=lambda: sent.append("pause"),
        play=lambda: sent.append("play"),
        seek=lambda ms: sent.append(("seek", ms)),
        stop=lambda: sent.append("stop"),
    )
    emitted = []
    playback = SimpleNamespace(
        playbackChanged=SimpleNamespace(emit=lambda: emitted.append(1)),
        current_stream_uri="",
        current_item=None,
        player=SimpleNamespace(playing=False, position_us=0),
    )
    context, events = make_context(playback)
    cast = CastBridge(context, lambda: None)
    assert not cast.active and cast.toggle() is False
    cast.renderer, cast._playing = renderer, True
    assert cast.toggle() and sent == ["pause"] and not cast.playing
    assert cast.seek(42_000) and sent[-1] == ("seek", 42_000)
    assert cast.position_ms == 42_000
    assert cast.stop() and not cast.active and sent[-1] == "stop"
    assert events["jobs"][-1] == "cast-stop"
