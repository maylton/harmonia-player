# PyInstaller spec for the Windows build of the GTK frontend.
# Run from the repository root inside an MSYS2 UCRT64 shell:
#     pyinstaller --noconfirm --distpath build/windows/dist \
#         --workpath build/windows/work packaging/windows/harmonia.spec
# packaging/windows/build.sh prepares the icon and the compiled catalogs first.
# ruff: noqa

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parents[1]
SOURCE = ROOT / "src" / "harmonia"
STAGING = ROOT / "build" / "windows"

# Only the plugins the player, the video layer and local files need. The full
# MSYS2 set adds more than 130 MB of plugins (and their DLLs) the app never loads.
GSTREAMER_PLUGINS = [
    # Core and playbin
    "coreelements", "typefindfunctions", "playback", "app", "pbtypes", "gio", "soup",
    "autodetect", "rawparse",
    # Windows audio output
    "wasapi", "wasapi2", "directsound",
    # Audio processing used by the player's filter graph
    "audioconvert", "audioresample", "audiorate", "volume", "audiofx", "equalizer",
    "replaygain", "soundtouch", "removesilence", "level", "wavenc",
    # Containers and streaming
    "isomp4", "matroska", "ogg", "adaptivedemux2", "dash", "id3demux", "icydemux",
    "apetag", "wavparse", "audioparsers", "opusparse", "videoparsersbad",
    # Audio decoders (YouTube serves AAC and Opus; local files add the rest)
    "fdkaac", "faad", "opus", "vorbis", "flac", "mpg123",
    # Video: GTK 4 sink, conversion and decoders (hardware first, then software)
    "gtk4", "opengl", "videoconvertscale", "videorate", "videofilter", "deinterlace",
    "d3d11", "d3d12", "dav1d", "vpx", "openh264",
]


def harmonia_data():
    """Stylesheets, themes and bundled icons; the Qt/QML frontend is not shipped."""
    datas = []
    for path in SOURCE.rglob("*"):
        relative = path.relative_to(SOURCE)
        if not path.is_file() or path.suffix in {".py", ".pyc"}:
            continue
        if relative.parts[0] in {"qml", "__pycache__"}:
            continue
        datas.append((str(path), str(Path("harmonia") / relative.parent)))
    return datas


def tree(source: Path, target: str, skip=()):
    return [
        (str(path), str(Path(target) / path.relative_to(source).parent))
        for path in source.rglob("*")
        if path.is_file() and not any(part in skip for part in path.parts)
    ]


MSYS_PREFIX = Path(sys.base_prefix)

datas = harmonia_data()
# The WebView2 login loads its loader through ctypes, so PyInstaller cannot
# see it. (Window handles come from GDK's C API, so no GdkWin32 typelib.)
datas += [
    (str(MSYS_PREFIX / "share/licenses/webview2-loader/LICENSE"), "licenses/webview2-loader"),
    (str(ROOT / "licenses/Fluent-UI-System-Icons-MIT.txt"), "licenses"),
]
binaries = [(str(MSYS_PREFIX / "bin/WebView2Loader.dll"), ".")]
datas += tree(ROOT / "data" / "icons" / "hicolor", "share/icons/hicolor", skip={"1024x1024"})
datas += tree(STAGING / "locale", "share/locale")
datas += [
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
]

a = Analysis(
    [str(SPECPATH + "/launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "harmonia.app",
        "harmonia.gtk_video",
        "harmonia.gtk_media_variants",
        "harmonia.auth_webview2",
    ],
    hookspath=[SPECPATH + "/hooks"],
    hooksconfig={
        "gi": {
            "icons": ["Adwaita", "hicolor"],
            "themes": [],
            "languages": ["pt_BR", "pt", "en"],
            "module-versions": {"Gtk": "4.0", "Gdk": "4.0", "Gsk": "4.0", "Adw": "1"},
        },
        "gstreamer": {"include_plugins": GSTREAMER_PLUGINS},
    },
    excludes=[
        # Linux-only (WebKitGTK login) or Qt frontend modules, never loaded on Windows.
        "harmonia.auth",
        "harmonia.qt_app",
        "PySide6",
        "shiboken6",
        "tkinter",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Harmonia",
    icon=str(STAGING / "harmonia.ico"),
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Harmonia")
