"""Persistent, resumable audio downloads independent from GTK."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .models import DownloadRecord, LibraryItem
from .services import YouTubeMusicService
from .storage import Storage

LOGGER = logging.getLogger(__name__)


class DownloadManager:
    CHUNK_SIZE = 1024 * 1024
    VALIDATION_MAX_AGE = 30 * 24 * 60 * 60

    def __init__(self, storage: Storage, youtube: YouTubeMusicService, on_update=None):
        self.storage = storage
        self.youtube = youtube
        self.on_update = on_update
        self._cancellations: dict[str, threading.Event] = {}
        self._workers: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def account_hash(self) -> str:
        cookie = self.storage.load_cookie()
        return hashlib.sha256(cookie.encode()).hexdigest() if cookie else ""

    def validate_account(self) -> bool:
        valid = self.youtube.validate_account()
        if valid:
            self.storage.set_setting("download_account_hash", self.account_hash())
            self.storage.set_setting("download_account_validated_at", str(int(time.time())))
        return valid

    def access_allowed(self, record: DownloadRecord) -> bool:
        if not record.account_hash or record.account_hash != self.account_hash():
            return False
        validated_hash = self.storage.get_setting("download_account_hash")
        try:
            validated_at = int(self.storage.get_setting("download_account_validated_at", "0"))
        except ValueError:
            validated_at = 0
        return (
            validated_hash == record.account_hash
            and int(time.time()) - validated_at <= self.VALIDATION_MAX_AGE
        )

    def offline_path(self, item_id: str) -> Path | None:
        record = self.storage.get_download(item_id)
        if (
            record
            and record.status == "completed"
            and self.access_allowed(record)
            and Path(record.file_path).is_file()
        ):
            return Path(record.file_path)
        return None

    def start(self, item: LibraryItem) -> None:
        if not item.id or item.id.startswith("local:"):
            return
        with self._lock:
            worker = self._workers.get(item.id)
            if worker and worker.is_alive():
                return
            cancel = threading.Event()
            self._cancellations[item.id] = cancel
            record = self.storage.get_download(item.id) or DownloadRecord(item)
            record.item = item
            record.status = "queued"
            record.account_hash = self.account_hash()
            record.error = ""
            record.updated_at = int(time.time())
            self.storage.save_download(record)
            worker = threading.Thread(
                target=self._download,
                args=(record, cancel),
                daemon=True,
                name=f"download-{item.id[:8]}",
            )
            self._workers[item.id] = worker
            worker.start()
        self._notify(record)

    def pause(self, item_id: str) -> None:
        event = self._cancellations.get(item_id)
        if event:
            event.set()

    def resume_pending(self) -> None:
        for record in self.storage.load_downloads():
            if record.status in ("queued", "downloading"):
                self.start(record.item)

    def remove(self, item_id: str) -> None:
        self.pause(item_id)
        record = self.storage.get_download(item_id)
        if record:
            for path in (Path(record.file_path), Path(record.file_path + ".part")):
                try:
                    if path.is_file():
                        path.unlink()
                except OSError:
                    LOGGER.warning("Não foi possível remover o download %s", path, exc_info=True)
        self.storage.delete_download_record(item_id)
        self._notify(None)

    def _target(self, item_id: str) -> Path:
        safe_id = "".join(
            character for character in item_id if character.isalnum() or character in "-_"
        )
        return (
            self.storage.downloads_dir
            / f"{safe_id or hashlib.sha256(item_id.encode()).hexdigest()}.media"
        )

    def _download(self, record: DownloadRecord, cancel: threading.Event) -> None:
        final = Path(record.file_path) if record.file_path else self._target(record.item.id)
        part = Path(str(final) + ".part")
        try:
            stream = self.youtube.resolve_stream(record.item.id, force=True)
            self.storage.set_setting("download_account_hash", record.account_hash)
            self.storage.set_setting("download_account_validated_at", str(int(time.time())))
            final.parent.mkdir(parents=True, exist_ok=True)
            downloaded = part.stat().st_size if part.exists() else 0
            record.file_path = str(final)
            record.downloaded_bytes = downloaded
            record.status = "downloading"
            record.updated_at = int(time.time())
            self.storage.save_download(record)
            self._notify(record)
            total = record.total_bytes
            while not total or downloaded < total:
                if cancel.is_set():
                    record.status = "paused"
                    break
                end = downloaded + self.CHUNK_SIZE - 1
                request = urllib.request.Request(
                    stream.url,
                    headers={"Range": f"bytes={downloaded}-{end}", "User-Agent": "Mozilla/5.0"},
                )
                with urllib.request.urlopen(request, timeout=45) as response:
                    content_range = response.headers.get("Content-Range", "")
                    if "/" in content_range:
                        total = int(content_range.rsplit("/", 1)[1])
                    elif response.headers.get("Content-Length"):
                        length = int(response.headers["Content-Length"])
                        total = downloaded + length
                    mode = "ab" if downloaded else "wb"
                    with part.open(mode) as output:
                        while chunk := response.read(128 * 1024):
                            if cancel.is_set():
                                break
                            output.write(chunk)
                            downloaded += len(chunk)
                            record.downloaded_bytes = downloaded
                            record.total_bytes = total
                            if downloaded % (512 * 1024) < len(chunk):
                                record.updated_at = int(time.time())
                                self.storage.save_download(record)
                                self._notify(record)
                if cancel.is_set():
                    record.status = "paused"
                    break
                if total and downloaded >= total:
                    part.replace(final)
                    record.status = "completed"
                    record.downloaded_bytes = total
                    break
            record.total_bytes = total
            record.updated_at = int(time.time())
            self.storage.save_download(record)
            self._notify(record)
        except Exception as exc:
            record.status = "failed"
            record.error = str(exc)
            record.updated_at = int(time.time())
            self.storage.save_download(record)
            self._notify(record)
        finally:
            with self._lock:
                self._workers.pop(record.item.id, None)
                self._cancellations.pop(record.item.id, None)

    def _notify(self, record: DownloadRecord | None) -> None:
        if self.on_update:
            self.on_update(record)
