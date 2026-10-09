from harmonia.library_sync import Listing, PendingChange, merge_category, merge_library, settled
from harmonia.models import LibraryItem


def songs(*ids):
    return [LibraryItem(item_id, item_id.title(), kind="songs") for item_id in ids]


def ids(items):
    return [item.id for item in items]


def test_a_complete_listing_propagates_removals_made_on_youtube():
    merged = merge_category(songs("a", "b", "c"), Listing(songs("a", "c")), [])
    assert ids(merged) == ["a", "c"]


def test_an_incomplete_listing_only_adds():
    # More pages than were read: "c" may be on one of them.
    merged = merge_category(songs("a", "b", "c"), Listing(songs("new", "a"), complete=False), [])
    assert ids(merged) == ["new", "a", "b", "c"]


def test_an_empty_listing_does_not_wipe_the_cache():
    assert ids(merge_category(songs("a", "b"), Listing([]), [])) == ["a", "b"]
    # Unless everything left was removed here.
    removed = [PendingChange("songs", item, False) for item in songs("a", "b")]
    assert merge_category(songs("a", "b"), Listing([]), removed) == []
    assert merge_category([], Listing([]), []) == []


def test_recent_changes_stay_until_youtube_lists_them():
    like = PendingChange("songs", songs("liked")[0], True)
    unlike = PendingChange("songs", songs("b")[0], False)
    listing = Listing(songs("a", "b"))
    assert ids(merge_category(songs("a", "b"), listing, [like, unlike])) == ["liked", "a"]
    assert not settled(like, listing) and not settled(unlike, listing)
    caught_up = Listing(songs("liked", "a"))
    assert settled(like, caught_up) and settled(unlike, caught_up)
    # A removal is only confirmed by a listing that read every page.
    assert not settled(unlike, Listing(songs("a"), complete=False))


def test_merge_library_touches_only_the_listed_categories():
    like = PendingChange("songs", songs("liked")[0], True)
    other = PendingChange("artists", LibraryItem("artist", "Artista", kind="artists"), True)
    merged, done = merge_library(
        {"songs": songs("a"), "albums": songs("x")},
        {"songs": Listing(songs("liked", "a"))},
        [like, other],
    )
    assert list(merged) == ["songs"] and ids(merged["songs"]) == ["liked", "a"]
    assert done == [like]


def test_storage_keeps_pending_changes_for_a_while(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    from harmonia.library_sync import PENDING_TTL_S
    from harmonia.storage import Storage

    storage = Storage()
    item = LibraryItem("v", "Faixa", "Artista", kind="songs", links=(("artist", "A", "UC1"),))
    storage.record_library_change("songs", item, True)
    storage.record_library_change("songs", item, False)  # the latest change wins
    (change,) = storage.pending_library_changes()
    assert change.item == item and change.added is False
    storage.forget_library_changes([change])
    assert storage.pending_library_changes() == []
    storage.record_library_change("songs", item, True)
    later = change.created_at + PENDING_TTL_S + 3600
    assert storage.pending_library_changes(now=later) == []
