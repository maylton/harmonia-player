from harmonia.models import LibraryItem, SearchGroup
from harmonia.services import SEARCH_ORDER, YouTubeMusicService


class MemoryStorage:
    def __init__(self):
        self.cookie = "SAPISID=test"
        self.library = None

    def load_cookie(self):
        return self.cookie

    def save_cookie(self, value):
        self.cookie = value

    def clear_cookie(self):
        self.cookie = ""

    def save_library(self, value):
        self.library = value

    def load_library(self):
        return self.library or {}

    def pending_library_changes(self):
        return getattr(self, "changes", [])

    def forget_library_changes(self, changes):
        self.forgotten = changes

    def record_library_change(self, category, item, added):
        from harmonia.library_sync import PendingChange

        self.changes = [*getattr(self, "changes", []), PendingChange(category, item, added)]


class FakeClient:
    authenticated = True

    def __init__(self, cookie):
        self.cookie = cookie

    def library(self, category):
        return [LibraryItem(category, category.title(), kind=category)]

    def library_listing(self, category, max_pages=10):
        return self.library(category), True

    def search_category(self, query, category, continuation=None):
        if category == "artists":
            raise RuntimeError("categoria temporariamente indisponível")
        suffix = "-more" if continuation else ""
        return SearchGroup(
            category,
            category.title(),
            [LibraryItem(category + suffix, query, kind=category)],
            None if continuation else "next",
        )

    def search_suggestions(self, query):
        return [query, f"{query} ao vivo"]


def test_service_syncs_library_in_stable_order():
    storage = MemoryStorage()
    service = YouTubeMusicService(storage, FakeClient)
    result = service.sync_library()
    assert list(result) == [
        "playlists",
        "songs",
        "albums",
        "artists",
        "uploads",
        "uploaded-albums",
        "podcasts",
        "podcast-episodes",
    ]
    assert storage.library == result


def test_universal_search_keeps_partial_results_ordered():
    service = YouTubeMusicService(MemoryStorage(), FakeClient)
    results = service.universal_search("teste")
    assert [group.key for group in results.groups] == [
        key for key in SEARCH_ORDER if key != "artists"
    ]
    assert "artists" in results.errors
    assert all(group.items[0].title == "teste" for group in results.groups)


def test_service_suggestions_and_category_pagination():
    service = YouTubeMusicService(MemoryStorage(), FakeClient)
    assert service.suggestions("daft") == ["daft", "daft ao vivo"]
    current = SearchGroup("songs", "Músicas", [], "next")
    page = service.search_more("daft", current)
    assert page.items[0].id == "songs-more"
    assert page.continuation is None


def test_service_owns_account_cookie_lifecycle():
    storage = MemoryStorage()
    service = YouTubeMusicService(storage, FakeClient)
    assert service.connect("  SAPISID=new  ") is True
    assert storage.cookie == "SAPISID=new"
    service.disconnect()
    assert storage.cookie == ""


def test_optional_library_failure_preserves_cached_section():
    class PartialClient(FakeClient):
        def library(self, category):
            if category == "podcasts":
                raise RuntimeError("indisponível")
            return super().library(category)

    storage = MemoryStorage()
    storage.library = {"podcasts": [LibraryItem("cached", "Em cache", kind="podcasts")]}
    result = YouTubeMusicService(storage, PartialClient).sync_library()
    assert result["podcasts"][0].id == "cached"


def test_a_like_survives_the_sync_until_youtube_lists_it():
    liked = LibraryItem("new-like", "Nova", kind="songs")
    lagging = []

    class LaggingClient(FakeClient):
        def like_song(self, video_id, liked):
            pass

        def library(self, category):
            listed = super().library(category)
            return [*lagging, *listed] if category == "songs" else listed

    storage = MemoryStorage()
    service = YouTubeMusicService(storage, LaggingClient)
    service.set_song_liked(liked, True)
    result = service.sync_library()
    assert [item.id for item in result["songs"]] == ["new-like", "songs"]
    assert storage.forgotten == []  # YouTube does not list it yet
    lagging.append(liked)
    service.sync_library()
    assert [change.item.id for change in storage.forgotten] == ["new-like"]


def test_service_passes_connection_preferences_to_client():
    class ConfiguredStorage(MemoryStorage):
        def get_setting(self, key, default=""):
            return {
                "language": "en-US",
                "region": "US",
                "quality": "medium",
                "proxy": "http://127.0.0.1:8080",
            }.get(key, default)

    captured = {}

    class ConfiguredClient(FakeClient):
        def __init__(self, cookie, **kwargs):
            super().__init__(cookie)
            captured.update(kwargs)

    YouTubeMusicService(ConfiguredStorage(), ConfiguredClient).client()
    assert captured == {
        "hl": "en-US",
        "gl": "US",
        "max_bitrate": 160_000,
        "proxy": "http://127.0.0.1:8080",
    }


def test_service_exposes_active_account_profile():
    from harmonia.models import AccountProfile

    class AccountClient(FakeClient):
        def account_profile(self):
            return AccountProfile("Pessoa", "avatar")

    profile = YouTubeMusicService(MemoryStorage(), AccountClient).account_profile()
    assert (profile.name, profile.thumbnail) == ("Pessoa", "avatar")
