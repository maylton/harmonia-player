from harmonia import __version__
from harmonia.models import LibraryItem
from harmonia.playback_report import playback_report, scrub


def test_the_report_names_versions_track_and_error():
    item = LibraryItem("kJQP7kiw5Fk", "Despacito", kind="songs")
    error = (
        "Não foi possível obter um stream reproduzível. IOS: HTTP 403; ANDROID_VR: LOGIN_REQUIRED"
    )
    report = playback_report(f"  {error}\n", item)
    lines = report.splitlines()
    assert lines[0].startswith(f"Harmonia {__version__}")
    assert "Despacito [kJQP7kiw5Fk]" in report
    assert lines[-1] == error
    assert "Track" not in playback_report("falhou", None)


def test_stream_links_lose_their_query_with_the_users_ip():
    text = "Falha em https://rr3.googlevideo.com/videoplayback?expire=1&ip=203.0.113.9&sig=x (403)"
    assert scrub(text) == "Falha em https://rr3.googlevideo.com/videoplayback?… (403)"
    assert "203.0.113.9" not in playback_report(text, None)
