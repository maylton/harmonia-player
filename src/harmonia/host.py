"""The few facts about the host operating system the application depends on.

Harmonia was written for Linux desktops. Every place that needs a different
behaviour elsewhere asks this module instead of testing ``sys.platform``.
"""

from __future__ import annotations

import locale
import os
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
# Matched against the "platforms" list of platform-specific themes.
PLATFORM = "windows" if IS_WINDOWS else "linux" if IS_LINUX else sys.platform

# The integrated Google login embeds the platform's web engine: WebKitGTK on
# Linux (auth.py), the Edge WebView2 runtime on Windows (auth_webview2.py).
LOGIN_MODULE = "auth_webview2" if IS_WINDOWS else "auth" if IS_LINUX else ""
INTEGRATED_LOGIN = bool(LOGIN_MODULE)
# MPRIS media controls are exported on the D-Bus session bus.
MPRIS = IS_LINUX

DISCORD_IPC_SLOTS = 10
SINGLE_INSTANCE_NAME = r"Local\io.github.harmonia.Harmonia"
ERROR_ALREADY_EXISTS = 183
_instance_mutex = None


def _windows_folder(variable: str, fallback: str) -> Path:
    return Path(os.environ.get(variable) or Path.home() / fallback)


def config_dir() -> Path:
    """Where the session fallback and the integrated login profile live.

    An explicit XDG_CONFIG_HOME is honoured everywhere, as GLib does on Windows.
    """
    if os.environ.get("XDG_CONFIG_HOME") or not IS_WINDOWS:
        return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "harmonia"
    return _windows_folder("APPDATA", "AppData/Roaming") / "Harmonia"


def cache_dir() -> Path:
    """Where the library database, artwork and downloads live."""
    if os.environ.get("XDG_CACHE_HOME") or not IS_WINDOWS:
        return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "harmonia"
    return _windows_folder("LOCALAPPDATA", "AppData/Local") / "Harmonia"


def slash_path(path: str) -> str:
    """Write a native path with forward slashes so it can be matched as text."""
    return path.replace("\\", "/") if IS_WINDOWS else path


def posix_locale_name(bcp47: str) -> str | None:
    """Turn a Windows (BCP 47) locale name such as "pt-BR" or "sr-Latn-RS" into "pt_BR"."""
    parts = [part for part in bcp47.split("-") if part]
    if not parts:
        return None
    return f"{parts[0]}_{parts[-1]}" if len(parts) > 1 else parts[0]


def _windows_locale_name() -> str | None:
    import ctypes

    buffer = ctypes.create_unicode_buffer(85)  # LOCALE_NAME_MAX_LENGTH
    if not ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, len(buffer)):
        return None
    return posix_locale_name(buffer.value)


def user_locale() -> str | None:
    """The user's language and territory, such as "pt_BR".

    On Windows locale.getlocale() reports names like "Portuguese_Brazil", which
    neither YouTube Music nor gettext understand.
    """
    if IS_WINDOWS:
        return _windows_locale_name()
    return locale.getlocale()[0]


def translation_languages() -> list[str] | None:
    """Languages gettext should try; None keeps its LANGUAGE/LANG lookup.

    Windows does not export those variables, so the user's locale is used.
    """
    if not IS_WINDOWS or any(
        os.environ.get(name) for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")
    ):
        return None
    name = user_locale()
    return [name] if name else None


ACCENT_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent"


def accent_palette_colors(data: bytes) -> list[str] | None:
    """Decode AccentPalette: eight RGBA shades, Light3 first; the eighth is unused."""
    if len(data) < 28:
        return None
    return [f"#{data[i]:02x}{data[i + 1]:02x}{data[i + 2]:02x}" for i in range(0, 28, 4)]


def windows_accent_palette() -> list[str] | None:
    """The user's Windows accent shades, lightest first, or None elsewhere.

    libadwaita reads the system accent too, but rounds it to its nine presets;
    the Windows 11 theme wants the exact colour the rest of the desktop uses.
    """
    if not IS_WINDOWS:
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ACCENT_KEY) as key:
            data, _kind = winreg.QueryValueEx(key, "AccentPalette")
    except OSError:
        return None
    return accent_palette_colors(bytes(data))


def _raise_running_window(title: str) -> None:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    own_process = os.getpid()
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(window, _param):
        text = ctypes.create_unicode_buffer(256)
        kind = ctypes.create_unicode_buffer(256)
        process = wintypes.DWORD()
        user32.GetWindowTextW(window, text, len(text))
        user32.GetClassNameW(window, kind, len(kind))
        user32.GetWindowThreadProcessId(window, ctypes.byref(process))
        if (
            text.value == title
            and kind.value == "gdkSurfaceToplevel"
            and process.value != own_process
            and user32.IsWindowVisible(window)
        ):
            found.append(window)
            return False
        return True

    user32.EnumWindows(visit, 0)
    if found:
        if user32.IsIconic(found[0]):
            user32.ShowWindow(found[0], 9)  # SW_RESTORE
        user32.SetForegroundWindow(found[0])


def claim_single_instance(name: str = SINGLE_INSTANCE_NAME, title: str = "Harmonia") -> bool:
    """Whether this process is the only running Harmonia.

    Gtk.Application finds a running instance over D-Bus, which Windows lacks,
    so every launch would open another window playing its own audio over the
    same database. A named mutex marks the first instance; later launches
    bring its window forward and exit, as a second launch does on Linux.
    """
    global _instance_mutex
    if not IS_WINDOWS:
        return True
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        return True
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        _raise_running_window(title)
        return False
    _instance_mutex = handle  # held until the process exits
    return True


def discord_ipc_paths() -> list[str]:
    """Endpoints a running Discord client may listen on, in lookup order."""
    if IS_WINDOWS:
        return [rf"\\.\pipe\discord-ipc-{index}" for index in range(DISCORD_IPC_SLOTS)]
    roots = [
        Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")),
        Path(os.environ.get("TMPDIR", "/tmp")),
    ]
    candidates: list[str] = []
    for root in roots:
        for index in range(DISCORD_IPC_SLOTS):
            candidates.append(str(root / f"discord-ipc-{index}"))
            candidates.append(str(root / "app/com.discordapp.Discord" / f"discord-ipc-{index}"))
    return candidates
