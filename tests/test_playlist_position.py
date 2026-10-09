from harmonia.models import LibraryItem
from harmonia.playlist_position import added_set_video_id, with_item


def items(*ids):
    return [LibraryItem(item_id, item_id) for item_id in ids]


def test_local_playlists_add_at_the_end_or_the_start():
    song = LibraryItem("new", "Nova")
    assert [i.id for i in with_item(items("a", "b"), song, "end")] == ["a", "b", "new"]
    assert [i.id for i in with_item(items("a", "b"), song, "start")] == ["new", "a", "b"]
    # A track already in the playlist stays where it is.
    assert [i.id for i in with_item(items("a", "new"), song, "start")] == ["a", "new"]


def test_the_added_entry_is_found_in_the_edit_answer():
    payload = {
        "status": "STATUS_SUCCEEDED",
        "playlistEditResults": [
            {"playlistEditVideoAddedResultData": {"videoId": "vid", "setVideoId": "SET1"}}
        ],
    }
    assert added_set_video_id(payload, "vid") == "SET1"
    assert added_set_video_id(payload, "other") is None
    assert added_set_video_id({}, "vid") is None


def test_youtube_playlists_move_the_new_entry_before_the_first():
    from harmonia.innertube import InnerTubeClient

    client = InnerTubeClient("")
    edits = []

    def edit_playlist(playlist_id, actions):
        edits.append(actions)
        if actions[0]["action"] == "ACTION_ADD_VIDEO":
            return {
                "playlistEditResults": [
                    {"playlistEditVideoAddedResultData": {"videoId": "vid", "setVideoId": "NEW"}}
                ]
            }
        return {}

    client.edit_playlist = edit_playlist
    client.browse = lambda *_args, **_kwargs: [
        LibraryItem("x", "X", set_video_id="FIRST"),
        LibraryItem("vid", "Nova", set_video_id="NEW"),
    ]
    client.add_to_playlist("PL1", "vid")
    assert len(edits) == 1  # at the end: YouTube appends
    edits.clear()
    client.add_to_playlist("PL1", "vid", at_start=True)
    assert edits[1] == [
        {
            "action": "ACTION_MOVE_VIDEO_BEFORE",
            "setVideoId": "NEW",
            "movedSetVideoIdSuccessor": "FIRST",
        }
    ]
