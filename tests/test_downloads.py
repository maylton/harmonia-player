import io

from harmonia.downloads import DownloadManager
from harmonia.models import DownloadRecord, LibraryItem, StreamInfo
from harmonia.storage import Storage


class FakeYouTube:
    def __init__(self):
        self.calls = []

    def resolve_stream(self, video_id, force=False):
        self.calls.append((video_id, force))
        return StreamInfo("https://media.example/audio", 1000, "TEST")

    def validate_account(self):
        return True


def make_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    storage = Storage()
    storage.save_cookie("SAPISID=test")
    return storage


def install_range_server(monkeypatch, payload, requests):
    from harmonia import downloads

    class Response(io.BytesIO):
        def __init__(self, value, start, end):
            super().__init__(value)
            self.headers = {
                "Content-Range": f"bytes {start}-{end}/{len(payload)}",
                "Content-Length": str(len(value)),
            }

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def urlopen(request, **_kwargs):
        value = request.headers["Range"].removeprefix("bytes=")
        start, end = (int(part) for part in value.split("-"))
        end = min(end, len(payload) - 1)
        requests.append((start, end))
        return Response(payload[start : end + 1], start, end)

    monkeypatch.setattr(downloads.urllib.request, "urlopen", urlopen)


def test_download_completes_in_bounded_chunks_and_is_available_offline(monkeypatch, tmp_path):
    storage = make_storage(monkeypatch, tmp_path)
    youtube = FakeYouTube()
    payload = b"audio" * 500_000
    requests = []
    install_range_server(monkeypatch, payload, requests)
    manager = DownloadManager(storage, youtube)
    item = LibraryItem("video", "Faixa", kind="songs")
    manager.start(item)
    manager._workers[item.id].join(timeout=5)
    record = storage.get_download(item.id)
    assert record.status == "completed"
    assert record.downloaded_bytes == record.total_bytes == len(payload)
    assert manager.offline_path(item.id).read_bytes() == payload
    assert requests[0][0] == 0
    assert all(end - start + 1 <= manager.CHUNK_SIZE for start, end in requests)
    assert youtube.calls == [("video", True)]


def test_download_resumes_from_partial_file(monkeypatch, tmp_path):
    storage = make_storage(monkeypatch, tmp_path)
    youtube = FakeYouTube()
    payload = b"0123456789" * 200_000
    requests = []
    install_range_server(monkeypatch, payload, requests)
    manager = DownloadManager(storage, youtube)
    item = LibraryItem("resume", "Retomar", kind="songs")
    final = manager._target(item.id)
    partial = payload[:345_678]
    (storage.downloads_dir / (final.name + ".part")).write_bytes(partial)
    storage.save_download(
        DownloadRecord(
            item, "paused", str(final), len(partial), len(payload), manager.account_hash()
        )
    )
    manager.start(item)
    manager._workers[item.id].join(timeout=5)
    assert requests[0][0] == len(partial)
    assert final.read_bytes() == payload


def test_download_access_requires_matching_recent_account(monkeypatch, tmp_path):
    storage = make_storage(monkeypatch, tmp_path)
    manager = DownloadManager(storage, FakeYouTube())
    item = LibraryItem("secure", "Offline", kind="songs")
    path = storage.downloads_dir / "secure.media"
    path.write_bytes(b"data")
    record = DownloadRecord(item, "completed", str(path), 4, 4, manager.account_hash())
    storage.save_download(record)
    assert manager.offline_path(item.id) is None
    assert manager.validate_account() is True
    assert manager.offline_path(item.id) == path
    storage.save_cookie("SAPISID=other")
    assert manager.offline_path(item.id) is None
