"""New releases: their order, the file each install takes, and the checksum."""

import hashlib

import pytest

from harmonia import updates


@pytest.mark.parametrize(
    ("newer", "older"),
    [
        ("1.0.1", "1.0.0"),
        ("1.0.0", "1.0.0-rc.2"),
        ("1.0.0-rc.2", "1.0.0-rc.1"),
        ("1.0.0-rc.10", "1.0.0-rc.9"),
        ("v1.1.0", "1.0.9"),
        ("1.0.0-rc.1", "0.1.0-beta.6"),
    ],
)
def test_versions_are_ordered_as_releases(newer, older):
    assert updates.is_newer(newer, older)
    assert not updates.is_newer(older, newer)


def test_the_same_version_is_not_an_update():
    assert not updates.is_newer("1.0.0", "1.0.0")


def release(version="1.1.0", *names):
    return updates.Release(version, "https://page", assets={n: f"https://dl/{n}" for n in names})


def test_each_install_takes_its_own_file():
    full = release(
        "1.1.0", "Harmonia-1.1.0-x86_64-setup.exe", "Harmonia-1.1.0-x86_64.flatpak", "install.sh"
    )
    assert updates.asset_name(full, "windows") == "Harmonia-1.1.0-x86_64-setup.exe"
    assert updates.asset_name(full, "flatpak") == "Harmonia-1.1.0-x86_64.flatpak"
    for method in ("source", "source-system", "deb", "rpm"):
        assert updates.asset_name(full, method) == "install.sh"
    assert updates.asset_name(release("1.1.0"), "windows") is None


def test_linux_updates_run_the_new_install_sh_with_the_same_method(tmp_path):
    script = tmp_path / "install.sh"
    assert updates.install_command("source", script, "1.1.0") == [
        "sh", str(script), "--release", "1.1.0", "--yes", "--method", "source",
    ]  # fmt: skip
    assert updates.install_command("source-system", script, "1.1.0")[-3:] == [
        "--method", "source", "--system",
    ]  # fmt: skip
    assert updates.install_command("deb", script, "1.1.0")[-2:] == ["--method", "deb"]
    windows = updates.install_command("windows", tmp_path / "setup.exe", "1.1.0")
    assert "/SILENT" in windows and "/CLOSEAPPLICATIONS" in windows


def test_the_download_is_checked_against_its_sha256(monkeypatch, tmp_path):
    payload = b"installer"
    good = hashlib.sha256(payload).hexdigest()
    sums = {"https://dl/a.exe": payload, "https://dl/a.exe.sha256": f"{good}  a.exe".encode()}
    monkeypatch.setattr(updates, "_get", lambda url, timeout=15: sums[url])
    file = updates.download(release("1.1.0", "a.exe", "a.exe.sha256"), "a.exe", tmp_path)
    assert file.read_bytes() == payload

    sums["https://dl/a.exe.sha256"] = b"0" * 64
    with pytest.raises(ValueError):
        updates.download(release("1.1.0", "a.exe", "a.exe.sha256"), "a.exe", tmp_path / "bad")
    assert not (tmp_path / "bad" / "a.exe").exists()


def test_the_install_is_recognized_from_where_the_code_lives(monkeypatch):
    monkeypatch.setattr(updates.host, "IS_WINDOWS", False)
    monkeypatch.setattr(updates.Path, "exists", lambda self: False)  # not in a Flatpak

    def at(path):
        monkeypatch.setattr(updates, "__file__", f"{path}/harmonia/updates.py")
        return updates.install_method()

    assert at("/home/me/.local/share/harmonia/python") == "source"
    assert at("/usr/local/share/harmonia/python") == "source-system"
    monkeypatch.setattr(updates.shutil, "which", lambda name: name == "rpm")
    assert at("/usr/share/harmonia/python") == "rpm"
    assert at("/home/me/harmonia-player/src") == ""  # a checkout updates with git
