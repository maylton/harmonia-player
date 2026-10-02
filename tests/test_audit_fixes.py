import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from harmonia.cast import LocalMediaServer, UpnpDiscovery, parse_byte_range

ROOT = Path(__file__).resolve().parents[1]


def test_byte_ranges_follow_http_semantics():
    assert parse_byte_range("", 10) is None
    assert parse_byte_range("bytes=3-6", 10) == (3, 6)
    assert parse_byte_range("bytes=4-", 10) == (4, 9)
    assert parse_byte_range("bytes=-3", 10) == (7, 9)  # the last three bytes
    assert parse_byte_range("bytes=-30", 10) == (0, 9)
    start, end = parse_byte_range("bytes=abc-", 10)
    assert start > end  # malformed: unsatisfiable instead of a crash


def test_cast_media_is_only_served_under_its_secret_path(tmp_path):
    media = tmp_path / "song.m4a"
    media.write_bytes(b"0123456789")
    server = LocalMediaServer(media)
    try:
        assert server.token in server.url
        with urllib.request.urlopen(server.url) as response:
            assert response.read() == b"0123456789"
        guessed = server.url.rsplit("/", 1)[0]
        for path in (guessed, guessed.replace("/audio", "/"), guessed + "/wrong"):
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(path)
            assert error.value.code == 404
            error.value.close()
        tail = urllib.request.Request(server.url, headers={"Range": "bytes=-2"})
        with urllib.request.urlopen(tail) as response:
            assert response.status == 206 and response.read() == b"89"
        broken = urllib.request.Request(server.url, headers={"Range": "bytes=x-"})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(broken)
        assert error.value.code == 416
        error.value.close()
    finally:
        server.close()


class Response:
    def __init__(self, data):
        self.data = data

    def read(self, limit=-1):
        return self.data if limit < 0 else self.data[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def test_device_descriptions_reject_entities_and_oversized_replies():
    bomb = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa">]><root>&a;</root>'
    huge = b"<root>" + b"x" * (600 * 1024) + b"</root>"
    for data in (bomb, huge):
        discovery = UpnpDiscovery(opener=lambda *_args, data=data, **_kw: Response(data))
        assert discovery._device("http://192.168.0.9/desc.xml") is None


def test_every_translatable_string_is_in_the_catalogs():
    if not shutil.which("xgettext"):
        pytest.skip("xgettext indisponível")
    files = (ROOT / "po" / "POTFILES").read_text().split()
    fresh = subprocess.run(
        ["xgettext", "--from-code=UTF-8", "--language=Python", "--keyword=_",
         "--keyword=ngettext:1,2", "-o", "-", *files],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    used = {m for m in re.findall(r'^msgid "(.+)"$', fresh, re.M)}
    for catalog in ("en.po", "pt_BR.po"):
        text = (ROOT / "po" / catalog).read_text(encoding="utf-8")
        known = set(re.findall(r'^msgid "(.+)"$', text, re.M))
        assert not used - known, f"{catalog}: faltando {sorted(used - known)[:5]}"
        assert "#~" not in text, f"{catalog}: entradas obsoletas"
        empty = re.findall(r'^msgid "(.+)"\nmsgstr ""\n\n', text, re.M)
        assert not empty, f"{catalog}: sem tradução {empty[:5]}"


def test_every_python_file_with_strings_is_listed_for_extraction():
    listed = set((ROOT / "po" / "POTFILES").read_text().split())
    for path in sorted((ROOT / "src" / "harmonia").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if re.search(r'(?<![\w.])_\(\s*["\']', source) or "ngettext(" in source:
            assert str(path.relative_to(ROOT)) in listed, path.name
