from harmonia.innertube import (
    find_browse_endpoint,
    find_continuation,
    find_video_counterpart,
    parse_account_profile,
    parse_cookie,
    parse_explore,
    parse_library_items,
    parse_lyrics,
    parse_watch_queue,
    sapisid_hash,
)


def test_parse_active_account_profile_and_largest_avatar():
    payload = {
        "actions": [
            {
                "openPopupAction": {
                    "popup": {
                        "multiPageMenuRenderer": {
                            "header": {
                                "activeAccountHeaderRenderer": {
                                    "accountName": {"runs": [{"text": "Maylton"}]},
                                    "email": {"runs": [{"text": "user@example.com"}]},
                                    "channelHandle": {"runs": [{"text": "@maylton"}]},
                                    "accountPhoto": {
                                        "thumbnails": [
                                            {"url": "avatar-small", "width": 32, "height": 32},
                                            {"url": "avatar-large", "width": 128, "height": 128},
                                        ]
                                    },
                                }
                            }
                        }
                    }
                }
            }
        ]
    }
    profile = parse_account_profile(payload)
    assert (profile.name, profile.thumbnail) == ("Maylton", "avatar-large")
    assert (profile.email, profile.channel_handle) == ("user@example.com", "@maylton")


def test_cookie_and_sapisid_hash_are_compatible():
    cookie = "foo=bar; SAPISID=secret-value; SID=another"
    assert parse_cookie(cookie)["SAPISID"] == "secret-value"
    assert (
        sapisid_hash(cookie, 1234)
        == "SAPISIDHASH 1234_"
        + __import__("hashlib").sha1(b"1234 secret-value https://music.youtube.com").hexdigest()
    )


def test_parse_grid_and_list_items():
    payload = {
        "contents": [
            {
                "musicTwoRowItemRenderer": {
                    "title": {"runs": [{"text": "Favoritas"}]},
                    "subtitle": {"runs": [{"text": "Playlist"}, {"text": " · 20 músicas"}]},
                    "navigationEndpoint": {"browseEndpoint": {"browseId": "VL123"}},
                    "thumbnailRenderer": {
                        "thumbnails": [
                            {"url": "small", "width": 60},
                            {"url": "large", "width": 240},
                        ]
                    },
                }
            },
            {
                "musicResponsiveListItemRenderer": {
                    "flexColumns": [
                        {
                            "musicResponsiveListItemFlexColumnRenderer": {
                                "text": {"runs": [{"text": "Canção"}]}
                            }
                        },
                        {
                            "musicResponsiveListItemFlexColumnRenderer": {
                                "text": {"runs": [{"text": "Artista"}]}
                            }
                        },
                    ],
                    "fixedColumns": [
                        {
                            "musicResponsiveListItemFixedColumnRenderer": {
                                "text": {"runs": [{"text": "3:42"}]}
                            }
                        }
                    ],
                    "navigationEndpoint": {"watchEndpoint": {"videoId": "vid1"}},
                }
            },
        ]
    }
    items = parse_library_items(payload, "songs")
    assert [(x.title, x.id) for x in items] == [("Favoritas", "VL123"), ("Canção", "vid1")]
    assert items[0].thumbnail == "large"
    assert items[1].subtitle == "Artista · 3:42"


def test_find_continuation():
    payload = {"continuations": [{"nextContinuationData": {"continuation": "next-token"}}]}
    assert find_continuation(payload) == "next-token"


def test_find_and_parse_native_lyrics():
    next_payload = {
        "tabs": [
            {
                "tabRenderer": {
                    "endpoint": {
                        "browseEndpoint": {
                            "browseId": "MPLYlyrics",
                            "params": "lyrics-params",
                            "browseEndpointContextSupportedConfigs": {
                                "browseEndpointContextMusicConfig": {
                                    "pageType": "MUSIC_PAGE_TYPE_TRACK_LYRICS"
                                }
                            },
                        }
                    }
                }
            }
        ]
    }
    lyrics_payload = {
        "contents": [
            {
                "musicDescriptionShelfRenderer": {
                    "description": {
                        "runs": [{"text": "Primeira linha\n"}, {"text": "Segunda linha"}]
                    }
                }
            }
        ]
    }
    assert find_browse_endpoint(next_payload, "MUSIC_PAGE_TYPE_TRACK_LYRICS") == (
        "MPLYlyrics",
        "lyrics-params",
    )
    assert parse_lyrics(lyrics_payload) == "Primeira linha\nSegunda linha"


def test_find_official_video_counterpart_from_watch_next():
    def counterpart(video_id, music_type):
        return {
            "counterpartRenderer": {
                "playlistPanelVideoRenderer": {
                    "videoId": video_id,
                    "navigationEndpoint": {
                        "watchEndpoint": {
                            "watchEndpointMusicSupportedConfigs": {
                                "watchEndpointMusicConfig": {"musicVideoType": music_type}
                            }
                        }
                    },
                }
            }
        }

    payload = {
        "contents": [
            counterpart("audio-placeholder", "MUSIC_VIDEO_TYPE_ATV"),
            counterpart("official-video", "MUSIC_VIDEO_TYPE_OMV"),
        ]
    }
    assert find_video_counterpart(payload) == "official-video"


def test_video_counterpart_uses_authenticated_next_endpoint():
    from harmonia.innertube import InnerTubeClient

    client = InnerTubeClient("SAPISID=x")
    calls = []
    client._api_post = lambda endpoint, body, authenticated=True: (
        calls.append((endpoint, body, authenticated))
        or {
            "counterpart": [
                {
                    "counterpartRenderer": {
                        "playlistPanelVideoRenderer": {
                            "videoId": "official-video",
                            "navigationEndpoint": {
                                "watchEndpoint": {
                                    "watchEndpointMusicSupportedConfigs": {
                                        "watchEndpointMusicConfig": {
                                            "musicVideoType": "MUSIC_VIDEO_TYPE_OMV"
                                        }
                                    }
                                }
                            },
                        }
                    }
                }
            ]
        }
    )
    assert client.video_counterpart("audio") == "official-video"
    assert calls == [("next", {"videoId": "audio"}, True)]


def test_lyrics_follows_watch_next_endpoint():
    from harmonia.innertube import InnerTubeClient

    client = InnerTubeClient("SAPISID=x")
    calls = []
    client._api_post = lambda endpoint, body, authenticated=True: (
        calls.append((endpoint, body))
        or {
            "endpoint": {
                "browseEndpoint": {
                    "browseId": "MPLYid",
                    "browseEndpointContextSupportedConfigs": {
                        "browseEndpointContextMusicConfig": {
                            "pageType": "MUSIC_PAGE_TYPE_TRACK_LYRICS"
                        }
                    },
                }
            }
        }
    )
    client._post = lambda body: (
        calls.append(("browse", body))
        or {"musicDescriptionShelfRenderer": {"description": {"runs": [{"text": "Letra"}]}}}
    )
    assert client.lyrics("video") == "Letra"
    assert calls == [("next", {"videoId": "video"}), ("browse", {"browseId": "MPLYid"})]


def test_watch_queue_prefers_audio_tracks_and_deduplicates():
    def row(video_id, title, music_type):
        return {
            "playlistPanelVideoRenderer": {
                "videoId": video_id,
                "title": {"runs": [{"text": title}]},
                "longBylineText": {"runs": [{"text": "Artista"}]},
                "navigationEndpoint": {
                    "watchEndpoint": {
                        "watchEndpointMusicSupportedConfigs": {
                            "watchEndpointMusicConfig": {"musicVideoType": music_type}
                        }
                    }
                },
            }
        }

    payload = {
        "contents": [
            row("song", "Música", "MUSIC_VIDEO_TYPE_ATV"),
            row("video", "Clipe", "MUSIC_VIDEO_TYPE_OMV"),
            row("song", "Música duplicada", "MUSIC_VIDEO_TYPE_ATV"),
        ]
    }
    assert [(item.id, item.title) for item in parse_watch_queue(payload)] == [("song", "Música")]
    assert [item.id for item in parse_watch_queue(payload, audio_only=False)] == ["song", "video"]


def test_browse_detail_normalizes_playlist_id():
    from harmonia.innertube import InnerTubeClient

    client = InnerTubeClient("SAPISID=test")
    calls = []
    client._post = lambda body: (
        calls.append(body)
        or {
            "contents": [
                {
                    "musicResponsiveListItemRenderer": {
                        "flexColumns": [
                            {
                                "musicResponsiveListItemFlexColumnRenderer": {
                                    "text": {"runs": [{"text": "Faixa"}]}
                                }
                            }
                        ],
                        "navigationEndpoint": {"watchEndpoint": {"videoId": "video-id"}},
                    }
                }
            ]
        }
    )
    tracks = client.browse("PL123", "playlists")
    assert calls[0]["browseId"] == "VLPL123"
    assert tracks[0].id == "video-id"


def test_player_selects_highest_bitrate(monkeypatch):
    import io
    import json

    from harmonia import innertube
    from harmonia.innertube import InnerTubeClient

    payload = {
        "playabilityStatus": {"status": "OK"},
        "streamingData": {
            "adaptiveFormats": [
                {"mimeType": "video/mp4", "bitrate": 999, "url": "video"},
                {"mimeType": "audio/webm", "bitrate": 128000, "url": "medium"},
                {
                    "mimeType": "audio/mp4",
                    "bitrate": 256000,
                    "url": "best",
                    "approxDurationMs": "42000",
                },
            ]
        },
    }

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        innertube.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(json.dumps(payload).encode()),
    )
    assert InnerTubeClient("SAPISID=x").player("id") == ("best", 42000)


def test_player_honors_configured_quality_ceiling(monkeypatch):
    import io
    import json

    from harmonia import innertube
    from harmonia.innertube import InnerTubeClient

    payload = {
        "playabilityStatus": {"status": "OK"},
        "streamingData": {
            "adaptiveFormats": [
                {"mimeType": "audio/webm", "bitrate": 128000, "url": "medium"},
                {"mimeType": "audio/mp4", "bitrate": 256000, "url": "best"},
            ]
        },
    }

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        innertube.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(json.dumps(payload).encode()),
    )
    assert InnerTubeClient("SAPISID=x", max_bitrate=160_000).player("quality-id")[0] == "medium"


def test_search_uses_song_filter():
    from harmonia.innertube import SEARCH_FILTER_SONGS, InnerTubeClient

    client = InnerTubeClient("SAPISID=x")
    calls = []
    client._api_post = lambda endpoint, body, authenticated: (
        calls.append((endpoint, body, authenticated))
        or {
            "contents": [
                {
                    "musicResponsiveListItemRenderer": {
                        "flexColumns": [
                            {
                                "musicResponsiveListItemFlexColumnRenderer": {
                                    "text": {"runs": [{"text": "Resultado"}]}
                                }
                            }
                        ],
                        "navigationEndpoint": {"watchEndpoint": {"videoId": "result-id"}},
                    }
                }
            ]
        }
    )
    assert client.search("teste")[0].id == "result-id"
    assert calls == [("search", {"query": "teste", "params": SEARCH_FILTER_SONGS}, False)]


def test_mpris_interface_is_valid():
    from gi.repository import Gio

    from harmonia.mpris import XML

    node = Gio.DBusNodeInfo.new_for_xml(XML)
    assert [interface.name for interface in node.interfaces] == [
        "org.mpris.MediaPlayer2",
        "org.mpris.MediaPlayer2.Player",
    ]


def test_native_player_keeps_local_files_out_of_http_relay():
    from harmonia.player import NativePlayer

    player = NativePlayer()
    assert player._source_uri("file:///tmp/faixa.flac") == "file:///tmp/faixa.flac"
    remote = player._source_uri("https://rr1.googlevideo.com/audio")
    assert remote.startswith("http://127.0.0.1:")
    player.stop()


def test_posix_locale_falls_back_to_valid_youtube_locale(monkeypatch):
    from harmonia import innertube

    monkeypatch.setattr(innertube.locale, "getlocale", lambda: ("C", None))
    client = innertube.InnerTubeClient("SAPISID=x")
    assert (client.hl, client.gl) == ("pt-BR", "BR")


def test_bidirectional_commands_build_expected_payloads():
    from harmonia.innertube import InnerTubeClient

    client = InnerTubeClient("SAPISID=x")
    calls = []
    client._api_post = lambda endpoint, body, authenticated=True: (
        calls.append((endpoint, body))
        or ({"playlistId": "PLNEW"} if endpoint == "playlist/create" else {})
    )
    client.like_song("video", False)
    client.subscribe_artist("channel", True)
    assert client.create_playlist("Nova") == "PLNEW"
    client.add_to_playlist("VLPL1", "video")
    client.remove_from_playlist("VLPL1", "video", "set-id")
    assert calls == [
        ("like/removelike", {"target": {"videoId": "video"}}),
        ("subscription/subscribe", {"channelIds": ["channel"]}),
        ("playlist/create", {"title": "Nova", "privacyStatus": "PRIVATE", "videoIds": None}),
        (
            "browse/edit_playlist",
            {
                "playlistId": "PL1",
                "actions": [{"action": "ACTION_ADD_VIDEO", "addedVideoId": "video"}],
            },
        ),
        (
            "browse/edit_playlist",
            {
                "playlistId": "PL1",
                "actions": [
                    {
                        "action": "ACTION_REMOVE_VIDEO",
                        "removedVideoId": "video",
                        "setVideoId": "set-id",
                    }
                ],
            },
        ),
    ]


def test_home_sections_preserve_grouping_and_item_kind():
    from harmonia.innertube import parse_home_sections

    payload = {
        "contents": [
            {
                "musicCarouselShelfRenderer": {
                    "header": {
                        "musicCarouselShelfBasicHeaderRenderer": {
                            "title": {"runs": [{"text": "Álbuns para você"}]}
                        }
                    },
                    "contents": [
                        {
                            "musicTwoRowItemRenderer": {
                                "title": {"runs": [{"text": "Álbum"}]},
                                "navigationEndpoint": {
                                    "browseEndpoint": {"browseId": "MPREb_test"}
                                },
                            }
                        }
                    ],
                }
            }
        ]
    }
    sections = parse_home_sections(payload)
    assert sections[0].title == "Álbuns para você"
    assert sections[0].items[0].kind == "albums"


def test_home_follows_continuations_and_merges_duplicate_shelves():
    from harmonia.innertube import InnerTubeClient

    def shelf(title, video_id):
        return {
            "musicCarouselShelfRenderer": {
                "header": {
                    "musicCarouselShelfBasicHeaderRenderer": {"title": {"runs": [{"text": title}]}}
                },
                "contents": [
                    {
                        "musicTwoRowItemRenderer": {
                            "title": {"runs": [{"text": video_id}]},
                            "navigationEndpoint": {"watchEndpoint": {"videoId": video_id}},
                        }
                    }
                ],
            }
        }

    pages = {
        "first": {
            "contents": [shelf("Ouvir", "one")],
            "nextContinuationData": {"continuation": "two"},
        },
        "two": {"contents": [shelf("Ouvir", "second"), shelf("Mixtapes", "mix")]},
    }
    client = InnerTubeClient("SAPISID=x")
    calls = []
    client._post = lambda body: calls.append(body) or pages[body.get("continuation", "first")]
    sections = client.home()
    assert [(section.title, [item.id for item in section.items]) for section in sections] == [
        ("Ouvir", ["one", "second"]),
        ("Mixtapes", ["mix"]),
    ]
    assert calls == [{"browseId": "FEmusic_home"}, {"continuation": "two"}]


def test_explore_parses_shortcuts_genres_and_sections():
    payload = {
        "contents": [
            {
                "musicNavigationButtonRenderer": {
                    "buttonText": {"runs": [{"text": "Paradas"}]},
                    "clickCommand": {
                        "browseEndpoint": {"browseId": "FEmusic_charts", "params": "charts"}
                    },
                }
            },
            {
                "musicNavigationButtonRenderer": {
                    "buttonText": {"runs": [{"text": "Rock"}]},
                    "clickCommand": {
                        "browseEndpoint": {
                            "browseId": "FEmusic_moods_and_genres_category",
                            "params": "rock",
                        }
                    },
                }
            },
            {
                "musicCarouselShelfRenderer": {
                    "header": {
                        "musicCarouselShelfBasicHeaderRenderer": {
                            "title": {"runs": [{"text": "Em alta"}]}
                        }
                    },
                    "contents": [
                        {
                            "musicTwoRowItemRenderer": {
                                "title": {"runs": [{"text": "Faixa"}]},
                                "navigationEndpoint": {"watchEndpoint": {"videoId": "video"}},
                            }
                        }
                    ],
                }
            },
        ]
    }
    data = parse_explore(payload)
    assert [(x.title, x.browse_id) for x in data.shortcuts] == [("Paradas", "FEmusic_charts")]
    assert [(x.title, x.params) for x in data.genres] == [("Rock", "rock")]
    assert data.sections[0].items[0].id == "video"


def test_search_suggestions_are_deduplicated_case_insensitively():
    from harmonia.innertube import parse_search_suggestions

    payload = {
        "contents": [
            {"searchSuggestionRenderer": {"suggestion": {"runs": [{"text": "Daft Punk"}]}}},
            {"searchSuggestionRenderer": {"suggestion": {"runs": [{"text": "daft punk"}]}}},
            {"searchSuggestionRenderer": {"suggestion": {"runs": [{"text": "Daft Punk RAM"}]}}},
        ]
    }
    assert parse_search_suggestions(payload) == ["Daft Punk", "Daft Punk RAM"]


def test_category_search_uses_filter_and_continuation_query():
    from harmonia.innertube import SEARCH_FILTERS, InnerTubeClient

    client = InnerTubeClient("SAPISID=x")
    calls = []
    client._api_post = lambda endpoint, body, authenticated: (
        calls.append((endpoint, body, authenticated))
        or {
            "contents": [
                {
                    "musicResponsiveListItemRenderer": {
                        "flexColumns": [
                            {
                                "musicResponsiveListItemFlexColumnRenderer": {
                                    "text": {"runs": [{"text": "Vídeo"}]}
                                }
                            }
                        ],
                        "navigationEndpoint": {"watchEndpoint": {"videoId": "video-id"}},
                    }
                }
            ],
            "nextContinuationData": {"continuation": "next page"},
        }
    )
    group = client.search_category("teste", "videos", "token /+=")
    assert group.key == "videos"
    assert group.items[0].kind == "videos"
    assert group.continuation == "next page"
    assert calls == [
        (
            "search?continuation=token%20%2F%2B%3D&ctoken=token%20%2F%2B%3D",
            {"query": "teste", "params": SEARCH_FILTERS["videos"]},
            False,
        )
    ]


def test_stream_resolution_caches_and_force_refreshes(monkeypatch):
    import io
    import json
    import time

    from harmonia import innertube

    innertube._STREAM_CACHE.clear()
    expires = int(time.time()) + 3600
    calls = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def urlopen(*_args, **_kwargs):
        calls.append(1)
        payload = {
            "playabilityStatus": {"status": "OK"},
            "playbackTracking": {
                "videostatsPlaybackUrl": {"baseUrl": "https://track.example/play"}
            },
            "streamingData": {
                "adaptiveFormats": [
                    {
                        "mimeType": "audio/webm",
                        "bitrate": 128000,
                        "itag": 251,
                        "approxDurationMs": "42000",
                        "url": f"https://media.example/audio?expire={expires}&generation={len(calls)}",
                    }
                ]
            },
        }
        return Response(json.dumps(payload).encode())

    client = innertube.InnerTubeClient("SAPISID=x")
    client._bootstrap = lambda: None
    monkeypatch.setattr(innertube.urllib.request, "urlopen", urlopen)
    first = client.resolve_stream("cached")
    second = client.resolve_stream("cached")
    refreshed = client.resolve_stream("cached", force=True)
    assert first == second
    assert refreshed.url != first.url
    assert (first.duration_ms, first.bitrate, first.itag, first.expires_at) == (
        42000,
        128000,
        251,
        expires,
    )
    assert first.playback_tracking_url == "https://track.example/play"
    assert len(calls) == 2


def test_stream_resolution_retries_then_falls_back(monkeypatch):
    import io
    import json
    import urllib.error

    from harmonia import innertube

    innertube._STREAM_CACHE.clear()
    calls = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def urlopen(request, **_kwargs):
        calls.append(request.headers["X-youtube-client-name"])
        if len(calls) <= 2:
            raise urllib.error.URLError("temporário")
        return Response(
            json.dumps(
                {
                    "playabilityStatus": {"status": "OK"},
                    "streamingData": {
                        "adaptiveFormats": [
                            {
                                "mimeType": "audio/mp4",
                                "bitrate": 256000,
                                "url": "https://media.example/fallback",
                            }
                        ]
                    },
                }
            ).encode()
        )

    client = innertube.InnerTubeClient("SAPISID=x")
    client._bootstrap = lambda: None
    monkeypatch.setattr(innertube.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(innertube.time, "sleep", lambda *_args: None)
    stream = client.resolve_stream("fallback")
    assert stream.client == innertube.PLAYER_CLIENTS[1]["name"]
    assert len(calls) == 3


def test_artist_page_parses_header_sections_and_show_all_target():
    from harmonia.innertube import parse_artist_page

    payload = {
        "contents": [
            {
                "musicImmersiveHeaderRenderer": {
                    "title": {"runs": [{"text": "Artista"}]},
                    "description": {"runs": [{"text": "Biografia completa"}]},
                    "monthlyListenerCount": {"runs": [{"text": "1 mi ouvintes mensais"}]},
                    "thumbnail": {"thumbnails": [{"url": "cover", "width": 500}]},
                    "subscriptionButton": {"subscribeButtonRenderer": {"subscribed": True}},
                }
            },
            {
                "musicShelfRenderer": {
                    "title": {"runs": [{"text": "Top músicas"}]},
                    "contents": [
                        {
                            "musicResponsiveListItemRenderer": {
                                "flexColumns": [
                                    {
                                        "musicResponsiveListItemFlexColumnRenderer": {
                                            "text": {"runs": [{"text": "Faixa"}]}
                                        }
                                    }
                                ],
                                "navigationEndpoint": {"watchEndpoint": {"videoId": "song"}},
                            }
                        }
                    ],
                    "bottomEndpoint": {"browseEndpoint": {"browseId": "VLTOP", "params": "all"}},
                }
            },
        ]
    }
    page = parse_artist_page(payload, "UCartist")
    assert (page.title, page.description, page.subscribers, page.subscribed) == (
        "Artista",
        "Biografia completa",
        "1 mi ouvintes mensais",
        True,
    )
    assert page.thumbnail == "cover"
    assert [(section.title, section.browse_id, section.params) for section in page.sections] == [
        ("Top músicas", "VLTOP", "all")
    ]
    assert page.songs[0].id == "song"


def test_remote_history_keeps_removal_feedback_token():
    from harmonia.innertube import parse_remote_history

    payload = {
        "musicShelfRenderer": {
            "title": {"runs": [{"text": "Hoje"}]},
            "contents": [
                {
                    "musicResponsiveListItemRenderer": {
                        "flexColumns": [
                            {
                                "musicResponsiveListItemFlexColumnRenderer": {
                                    "text": {"runs": [{"text": "Ouvida"}]}
                                }
                            }
                        ],
                        "navigationEndpoint": {"watchEndpoint": {"videoId": "history-song"}},
                        "menu": {
                            "feedbackEndpoint": {
                                "feedbackToken": "remove-token",
                                "actions": [{"hideEnclosingAction": {"hack": True}}],
                            }
                        },
                    }
                }
            ],
        }
    }
    entries = parse_remote_history(payload)
    assert len(entries) == 1
    assert (entries[0].item.id, entries[0].group, entries[0].source) == (
        "history-song",
        "Hoje",
        "remote",
    )
    assert entries[0].feedback_token == "remove-token"


def test_register_playback_builds_account_tracking_request(monkeypatch):
    import io
    import urllib.parse

    from harmonia import innertube

    requests = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        innertube.urllib.request,
        "urlopen",
        lambda request, **_kwargs: requests.append(request) or Response(b""),
    )
    client = innertube.InnerTubeClient("SAPISID=x")
    client.register_playback("https://s.youtube.com/api/stats/playback?docid=video", "VLPL123")
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(requests[0].full_url).query)
    assert query["docid"] == ["video"]
    assert query["c"] == ["WEB_REMIX"]
    assert query["ver"] == ["2"]
    assert query["list"] == ["PL123"]
    assert len(query["cpn"][0]) == 16


def test_podcast_multirow_episode_is_playable():
    from harmonia.innertube import parse_library_items

    payload = {
        "musicMultiRowListItemRenderer": {
            "title": {"runs": [{"text": "Episódio"}]},
            "subtitle": {"runs": [{"text": "Podcast"}]},
            "onTap": {"watchEndpoint": {"videoId": "episode-id"}},
        }
    }
    items = parse_library_items(payload, "auto")
    assert [(item.id, item.kind, item.title) for item in items] == [
        ("episode-id", "songs", "Episódio")
    ]
