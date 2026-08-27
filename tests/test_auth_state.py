from harmonia.auth_state import (
    LOGIN_URL,
    SESSION_COOKIE_NAMES,
    has_session_cookie,
    is_youtube_music_url,
)


def test_login_policy_is_shared_and_toolkit_free() -> None:
    assert LOGIN_URL.startswith("https://accounts.google.com/")
    assert SESSION_COOKIE_NAMES == frozenset({"SAPISID", "__Secure-3PAPISID"})
    assert has_session_cookie({"SAPISID"})
    assert has_session_cookie({"__Secure-3PAPISID"})
    assert not has_session_cookie({"SID", "HSID"})


def test_youtube_music_origin_detection_is_case_insensitive() -> None:
    assert is_youtube_music_url("https://music.youtube.com/")
    assert is_youtube_music_url("HTTPS://MUSIC.YOUTUBE.COM/watch?v=test")
    assert not is_youtube_music_url("https://www.youtube.com/")
    assert not is_youtube_music_url("")
