"""New releases from GitHub: finding, downloading and installing them.

Frontend-agnostic: the GTK window drives it (window_updates.py). How an
update is installed depends on how Harmonia was:

- the Windows installer: the new installer runs silently and starts the app
  again when it is done (packaging/windows/harmonia.iss);
- install.sh on Linux (built with Meson, or the .deb and .rpm packages): the
  new release's install.sh runs with the same method; a password, when one is
  needed, is asked for by the desktop (pkexec) since there is no terminal;
- the Flatpak cannot update itself from inside its sandbox: Harmonia shows
  the command instead.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__, host

REPOSITORY = "maylton/harmonia-player"
LATEST_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
CHECK_INTERVAL = 24 * 60 * 60  # seconds between automatic checks
USER_AGENT = f"Harmonia/{__version__} (+https://github.com/{REPOSITORY})"


@dataclass(frozen=True, slots=True)
class Release:
    version: str
    page: str
    notes: str = ""
    assets: dict[str, str] = field(default_factory=dict)  # file name -> download URL


def version_key(version: str) -> tuple:
    """Order versions as releases are: 1.0.0-rc.2 < 1.0.0 < 1.0.1."""
    core, _, prerelease = version.lstrip("v").partition("-")
    numbers = tuple(int(part) for part in re.findall(r"\d+", core)[:3])
    numbers += (0,) * (3 - len(numbers))
    if not prerelease:
        return (*numbers, 1, ())
    parts = tuple(
        (0, int(part), "") if part.isdigit() else (1, 0, part)
        for part in re.split(r"[.-]", prerelease)
        if part
    )
    return (*numbers, 0, parts)


def is_newer(candidate: str, current: str = __version__) -> bool:
    return version_key(candidate) > version_key(current)


def _get(url: str, timeout: float = 15) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def latest_release() -> Release:
    """The newest stable release on GitHub (pre-releases are left out)."""
    data = json.loads(_get(LATEST_URL))
    return Release(
        version=str(data["tag_name"]).lstrip("v"),
        page=str(data.get("html_url") or RELEASES_URL),
        notes=str(data.get("body") or ""),
        assets={
            str(asset["name"]): str(asset["browser_download_url"])
            for asset in data.get("assets") or []
        },
    )


def install_method() -> str:
    """How this copy of Harmonia was installed, which says how to update it.

    "windows", "flatpak", "source" (install.sh's Meson build, for this user),
    "source-system", "deb", "rpm", or "" for a copy that cannot update
    itself, such as a git checkout.
    """
    if host.IS_WINDOWS:
        return "windows" if getattr(sys, "frozen", False) else ""
    if Path("/.flatpak-info").exists():
        return "flatpak"
    code = Path(__file__).resolve().parent.parent.as_posix()
    if code.endswith("/.local/share/harmonia/python"):
        return "source"
    if code == "/usr/local/share/harmonia/python":
        return "source-system"
    if code == "/usr/share/harmonia/python":
        if shutil.which("dpkg"):
            return "deb"
        if shutil.which("rpm"):
            return "rpm"
    return ""


def asset_name(release: Release, method: str) -> str | None:
    """The release file that updates ``method``."""
    wanted = {
        "windows": f"Harmonia-{release.version}-x86_64-setup.exe",
        "flatpak": f"Harmonia-{release.version}-x86_64.flatpak",
    }.get(method, "install.sh")
    return wanted if wanted in release.assets else None


def download(release: Release, name: str, folder: Path) -> Path:
    """Fetch ``name`` from ``release`` into ``folder``, checked against its .sha256.

    install.sh has no checksum of its own: it checks every package it fetches.
    """
    folder.mkdir(parents=True, exist_ok=True)
    data = _get(release.assets[name], timeout=120)
    checksum = release.assets.get(f"{name}.sha256")
    if checksum:
        expected = _get(checksum).decode().split()[0].lower()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"{name}: SHA-256 não confere")
    target = folder / name
    partial = target.with_suffix(target.suffix + ".part")
    partial.write_bytes(data)
    partial.replace(target)
    return target


def install_command(method: str, file: Path, version: str) -> list[str]:
    """What installs ``file``, the update downloaded for ``method``."""
    if method == "windows":
        # Inno Setup: no wizard, the running app is closed and started again.
        return [str(file), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]
    installer = ["sh", str(file), "--release", version, "--yes"]
    if method == "source-system":
        return [*installer, "--method", "source", "--system"]
    return [*installer, "--method", method]


def flatpak_command(file_name: str) -> str:
    return f"flatpak install --user --bundle {file_name}"


def run_install(command: list[str]) -> subprocess.CompletedProcess:
    """Run a Linux update to its end; its output explains a failure."""
    return subprocess.run(command, capture_output=True, text=True, stdin=subprocess.DEVNULL)


def start_detached(command: list[str]) -> None:
    """Start what outlives this process: the Windows installer, or the restart."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    subprocess.Popen(
        command, creationflags=flags, close_fds=True, start_new_session=not host.IS_WINDOWS
    )


def restart_command() -> list[str]:
    """Start Harmonia again a moment after this process has quit."""
    launcher = shutil.which("harmonia") or sys.argv[0]
    return ["sh", "-c", 'sleep 1; exec "$0"', launcher]
