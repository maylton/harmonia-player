import uuid
from pathlib import Path

import pytest

from harmonia import host


def test_linux_folders_keep_the_xdg_layout(monkeypatch, tmp_path):
    monkeypatch.setattr(host, "IS_WINDOWS", False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    assert host.config_dir() == tmp_path / ".config" / "harmonia"
    assert host.cache_dir() == tmp_path / ".cache" / "harmonia"

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    assert host.config_dir() == tmp_path / "config" / "harmonia"
    assert host.cache_dir() == tmp_path / "cache" / "harmonia"


def test_windows_folders_use_roaming_and_local_app_data(monkeypatch, tmp_path):
    monkeypatch.setattr(host, "IS_WINDOWS", True)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))

    assert host.config_dir() == tmp_path / "Roaming" / "Harmonia"
    assert host.cache_dir() == tmp_path / "Local" / "Harmonia"


def test_windows_honours_an_explicit_xdg_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(host, "IS_WINDOWS", True)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    assert host.config_dir() == tmp_path / "config" / "harmonia"


def test_discord_endpoints_follow_the_platform(monkeypatch, tmp_path):
    monkeypatch.setattr(host, "IS_WINDOWS", True)
    pipes = host.discord_ipc_paths()
    assert pipes[0] == r"\\.\pipe\discord-ipc-0"
    assert pipes[-1] == r"\\.\pipe\discord-ipc-9"

    monkeypatch.setattr(host, "IS_WINDOWS", False)
    monkeypatch.setattr(host.os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    sockets = host.discord_ipc_paths()
    assert sockets[:2] == [
        str(tmp_path / "discord-ipc-0"),
        str(tmp_path / "app/com.discordapp.Discord" / "discord-ipc-0"),
    ]
    assert len(sockets) == 40


def test_windows_locale_names_become_posix_names():
    assert host.posix_locale_name("pt-BR") == "pt_BR"
    assert host.posix_locale_name("sr-Latn-RS") == "sr_RS"
    assert host.posix_locale_name("en") == "en"
    assert host.posix_locale_name("") is None


def test_gettext_languages_come_from_windows_only_without_posix_variables(monkeypatch):
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(host, "user_locale", lambda: "en_US")

    monkeypatch.setattr(host, "IS_WINDOWS", False)
    assert host.translation_languages() is None

    monkeypatch.setattr(host, "IS_WINDOWS", True)
    assert host.translation_languages() == ["en_US"]

    monkeypatch.setenv("LANGUAGE", "pt_BR")
    assert host.translation_languages() is None


def test_accent_palette_registry_value_decodes_to_seven_shades():
    data = bytes.fromhex("99ebff004cc2ff000091f8000078d4000067c000003e9200001a6800f7630c00")
    assert host.accent_palette_colors(data) == [
        "#99ebff", "#4cc2ff", "#0091f8", "#0078d4", "#0067c0", "#003e92", "#001a68",
    ]  # fmt: skip
    assert host.accent_palette_colors(b"\x00" * 8) is None


def test_accent_palette_is_windows_only(monkeypatch):
    monkeypatch.setattr(host, "IS_WINDOWS", False)
    assert host.windows_accent_palette() is None


def test_linux_leaves_single_instance_to_gtk_application(monkeypatch):
    monkeypatch.setattr(host, "IS_WINDOWS", False)
    assert host.claim_single_instance() is True
    assert host.claim_single_instance() is True


@pytest.mark.skipif(not host.IS_WINDOWS, reason="usa um mutex nomeado do Windows")
def test_windows_second_launch_defers_to_the_running_instance(monkeypatch):
    monkeypatch.setattr(host, "_instance_mutex", None)
    name = rf"Local\io.github.harmonia.Harmonia.Test.{uuid.uuid4().hex}"
    title = f"Harmonia test {uuid.uuid4().hex}"  # no window to raise

    assert host.claim_single_instance(name, title) is True
    assert host.claim_single_instance(name, title) is False


def test_slash_path_only_rewrites_windows_paths(monkeypatch):
    monkeypatch.setattr(host, "IS_WINDOWS", True)
    assert host.slash_path(r"C:\icons\elementary\a.svg") == "C:/icons/elementary/a.svg"
    monkeypatch.setattr(host, "IS_WINDOWS", False)
    assert host.slash_path(r"/odd\name") == r"/odd\name"
