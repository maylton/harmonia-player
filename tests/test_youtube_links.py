import pytest

from harmonia.youtube_links import YouTubeLink, parse_link


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://music.youtube.com/watch?v=kJQP7kiw5Fk&list=RDAMVM", ("songs", "kJQP7kiw5Fk")),
        ("https://www.youtube.com/watch?v=kJQP7kiw5Fk&t=42", ("songs", "kJQP7kiw5Fk")),
        ("youtu.be/kJQP7kiw5Fk?si=abc", ("songs", "kJQP7kiw5Fk")),
        ("https://youtube.com/shorts/kJQP7kiw5Fk", ("songs", "kJQP7kiw5Fk")),
        (
            "https://music.youtube.com/playlist?list=PLx0sYbCqOb8TBPRdmBHs5Iftvv9TPboYG",
            ("playlists", "PLx0sYbCqOb8TBPRdmBHs5Iftvv9TPboYG"),
        ),
        (
            " https://music.youtube.com/playlist?list=OLAK5uy_kJ7hPPm0a9 ",
            ("playlists", "OLAK5uy_kJ7hPPm0a9"),
        ),
        ("https://music.youtube.com/browse/MPREb_4pL8gzRtw1p", ("albums", "MPREb_4pL8gzRtw1p")),
        (
            "https://music.youtube.com/channel/UCRqkb0rWLAHvVA9VEoGa4Fg",
            ("artists", "UCRqkb0rWLAHvVA9VEoGa4Fg"),
        ),
    ],
)
def test_links_point_to_tracks_playlists_albums_and_artists(text, expected):
    assert parse_link(text) == YouTubeLink(*expected)


@pytest.mark.parametrize(
    "text",
    [
        "anitta envolver",
        "https://example.com/watch?v=kJQP7kiw5Fk",
        "https://music.youtube.com/watch?v=short",
        "https://www.youtube.com/@handle",
        "https://music.youtube.com/",
    ],
)
def test_searches_and_other_sites_are_not_links(text):
    assert parse_link(text) is None


def test_a_video_id_becomes_the_track_the_queue_shows():
    from harmonia.innertube import InnerTubeClient

    def renderer(video_id, title):
        return {
            "playlistPanelVideoRenderer": {
                "videoId": video_id,
                "title": {"runs": [{"text": title}]},
                "longBylineText": {"runs": [{"text": "Artista"}]},
            }
        }

    client = InnerTubeClient("")
    calls = []

    def api_post(endpoint, body, authenticated=False):
        calls.append((endpoint, body, authenticated))
        return {"contents": [renderer("other", "Outra"), renderer("kJQP7kiw5Fk", "Despacito")]}

    client._api_post = api_post
    item = client.watch_item("kJQP7kiw5Fk")
    assert (item.id, item.title, item.subtitle) == ("kJQP7kiw5Fk", "Despacito", "Artista")
    assert calls == [("next", {"videoId": "kJQP7kiw5Fk"}, False)]  # works signed out
    assert client.watch_item("") is None


def test_link_pages_open_as_library_items():
    item = YouTubeLink("artists", "UC1").as_item("Link")
    assert (item.id, item.kind, item.title) == ("UC1", "artists", "Link")
