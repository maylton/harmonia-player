"""Open every GTK page, theme and icon style with sample data and fail on warnings.

The window is built exactly as the application builds it, but the YouTube Music
service is replaced by sample data and every other network access is refused,
so the run is deterministic and offline. Any Python exception, any GLib/GTK
warning or critical, and any icon the active icon theme cannot resolve make
the run fail.

    python3 tools/gtk_smoke.py            # run and report
    python3 tools/gtk_smoke.py --verbose  # also print each step

It needs libadwaita >= 1.7, so CI runs it inside the GNOME Flatpak runtime:

    flatpak run --command=python3 --filesystem="$PWD" --env=PYTHONPATH="$PWD/src" \\
        io.github.harmonia.Harmonia "$PWD/tools/gtk_smoke.py"
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

CHILD_FLAG = "--child"
# GLib prints "<domain>-WARNING **" and "<domain>-CRITICAL **" (and the
# structured "(prog:pid): Gtk-WARNING **:" form); Python callbacks that raise
# inside the main loop only print their traceback.
FAILURE = re.compile(r"-(WARNING|CRITICAL|ERROR) \*\*|^Traceback |^SMOKE-FAIL ", re.M)
# Noise from the session around the app, not from Harmonia: portals and the
# accessibility bus are absent or half-started under xvfb and dbus-run-session,
# and GTK warns about entries of the system Compose table it cannot represent.
IGNORED = re.compile(
    r"Can't handle (> ?16bit|Unicode codepoint)|xdg-desktop-portal|settings-daemon|atspi|dbus-daemon|"
    r"Unable to acquire session bus|Failed to create secret proxy|No skeleton to export|"
    r"fuse init failed|gnome-keyring"
)


def main(argv: list[str]) -> int:
    if CHILD_FLAG in argv:
        return _child(verbose="--verbose" in argv)
    with tempfile.TemporaryDirectory(prefix="harmonia-smoke-") as home:
        env = dict(os.environ, HARMONIA_SMOKE_HOME=home)
        started = time.monotonic()
        process = subprocess.run(
            [sys.executable, __file__, *argv, CHILD_FLAG],
            env=env,
            capture_output=True,
            text=True,
            timeout=900,
        )
    output = process.stdout + process.stderr
    failures = [
        line for line in output.splitlines() if FAILURE.search(line) and not IGNORED.search(line)
    ]
    if "--verbose" in argv or failures or process.returncode:
        print(output, end="")
    elapsed = time.monotonic() - started
    if process.returncode or failures or "SMOKE-DONE" not in output:
        print(
            f"\nGTK smoke falhou em {elapsed:.0f}s: código {process.returncode}, "
            f"{len(failures)} problema(s)",
            file=sys.stderr,
        )
        for line in failures[:40]:
            print(f"  {line}", file=sys.stderr)
        return 1
    summary = next(line for line in output.splitlines() if line.startswith("SMOKE-DONE"))
    print(f"GTK smoke ok em {elapsed:.0f}s: {summary.removeprefix('SMOKE-DONE ')}")
    return 0


# --------------------------------------------------------------------------- #
# Child process: builds the window and walks through the app.


def _isolate(home: str) -> None:
    """Point every per-user location at the scratch home, inside this process.

    Set here rather than by the caller: `flatpak run --env=XDG_CACHE_HOME=…`
    is silently overridden by Flatpak with the app's real directories, which
    would seed the sample data into the user's own Harmonia profile.
    """
    os.environ.update(
        XDG_CONFIG_HOME=f"{home}/config",
        XDG_CACHE_HOME=f"{home}/cache",
        XDG_DATA_HOME=f"{home}/data",
        HARMONIA_DISABLE_SECRET_SERVICE="1",
        GSETTINGS_BACKEND="memory",
        GTK_A11Y="none",
        # Keep the run identical on any desktop.
        XDG_CURRENT_DESKTOP="GNOME",
        LANGUAGE="pt_BR",
    )
    os.environ.pop("GTK_THEME", None)


def _child(verbose: bool) -> int:
    home = os.environ.get("HARMONIA_SMOKE_HOME") or tempfile.mkdtemp(prefix="harmonia-smoke-")
    _isolate(home)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    _refuse_network()

    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    gi.require_version("Gst", "1.0")
    from gi.repository import Adw, Gio, GLib, Gst

    if (Adw.MAJOR_VERSION, Adw.MINOR_VERSION) < (1, 7):
        print(f"SMOKE-FAIL libadwaita {Adw.MAJOR_VERSION}.{Adw.MINOR_VERSION} < 1.7")
        return 2

    from harmonia import app as gtk_app
    from harmonia.gtk_media_variants import install_gtk_media_variants
    from harmonia.gtk_video import install_gtk_video
    from harmonia.storage import Storage
    from harmonia.theming import builtin_themes

    install_gtk_video(gtk_app.HarmoniaWindow)
    install_gtk_media_variants(gtk_app.HarmoniaWindow)
    samples = _Samples(Path(os.environ["XDG_CACHE_HOME"]) / "smoke-media")
    gtk_app.YouTubeMusicService = lambda storage: _FakeService(storage, samples)
    storage = Storage()
    if not storage.database_file.resolve().is_relative_to(Path(home).resolve()):
        print(f"SMOKE-FAIL o perfil não está isolado: {storage.database_file}", flush=True)
        return 2
    _seed_storage(storage, samples)

    errors: list[str] = []

    def excepthook(kind, value, traceback):
        errors.append(f"{kind.__name__}: {value}")
        sys.__excepthook__(kind, value, traceback)

    sys.excepthook = excepthook
    steps = 0
    icons_seen: set[str] = set()

    def log(message: str) -> None:
        if verbose:
            print(f"  · {message}", flush=True)

    class SmokeApplication(gtk_app.HarmoniaApplication):
        def do_activate(self):
            window = gtk_app.HarmoniaWindow(self)
            sink = Gst.ElementFactory.make("fakesink", "smoke-audio")
            window.player._playbin.set_property("audio-sink", sink)
            window.present()
            driver = _drive(window, builtin_themes(), log)

            def advance() -> bool:
                nonlocal steps
                try:
                    wait = next(driver)
                except StopIteration:
                    window.close()
                    self.quit()
                    return False
                except Exception as exc:
                    sys.excepthook(type(exc), exc, exc.__traceback__)
                    self.quit()
                    return False
                steps += 1
                _check_icons(window, icons_seen, errors)
                GLib.timeout_add(wait, advance)
                return False

            GLib.timeout_add(300, advance)

    application = SmokeApplication()
    # Never hand the run over to a Harmonia instance that is already open on
    # this session bus: it would just present that window and exit at once.
    application.set_flags(application.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
    status = application.run([])
    for error in errors:
        print(f"SMOKE-FAIL {error}")
    if steps == 0:
        print("SMOKE-FAIL a janela não foi criada; nenhum passo executado", flush=True)
    print(f"SMOKE-DONE {steps} passos, {len(icons_seen)} ícones verificados", flush=True)
    return status or (1 if errors else 0)


def _refuse_network() -> None:
    """Fail loudly instead of reaching the network from a smoke run."""
    import socket

    original = socket.socket.connect

    def connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if self.family in (socket.AF_INET, socket.AF_INET6) and host not in (
            "127.0.0.1",
            "::1",
            "localhost",
        ):
            caller = next(
                (
                    f"{frame.filename.rsplit('/', 1)[-1]}:{frame.lineno} {frame.name}"
                    for frame in reversed(traceback.extract_stack())
                    if "/harmonia/" in frame.filename
                ),
                "?",
            )
            print(f"SMOKE-FAIL acesso à rede em {caller}: {address}", flush=True)
            raise OSError("rede desativada no smoke")
        return original(self, address)

    socket.socket.connect = connect


def _check_icons(window, seen: set[str], errors: list[str]) -> None:
    """Report icons that the current icon theme cannot resolve (they render blank)."""
    from gi.repository import Gtk

    theme = Gtk.IconTheme.get_for_display(window.get_display())
    pending = [window]
    while pending:
        widget = pending.pop()
        named_image = (
            isinstance(widget, Gtk.Image) and widget.get_storage_type() == Gtk.ImageType.ICON_NAME
        )
        name = (
            widget.get_icon_name()
            if named_image or isinstance(widget, Gtk.Button | Gtk.MenuButton)
            else None
        )
        if name:
            key = f"{theme.get_theme_name()}:{name}"
            if key not in seen:
                seen.add(key)
                if not theme.has_icon(name):
                    errors.append(f"ícone ausente em {theme.get_theme_name()}: {name}")
        child = widget.get_first_child()
        while child:
            pending.append(child)
            child = child.get_next_sibling()


def _drive(window, themes, log):
    """Yield the delay to wait after each step, so the main loop draws it."""
    yield 400  # initial render and the fake initial sync
    from gi.repository import Gtk

    settings = Gtk.Settings.get_for_display(window.get_display())
    # "gtk" follows the desktop icon theme: Adwaita, elementary (whose 8.x
    # symbolic icons need the compat shadow on GTK 4.21+) and an accent variant
    # of it that the sandbox cannot see, which must fall back cleanly.
    icon_styles = (
        ("gtk", "Adwaita"),
        ("gtk", "elementary"),
        ("gtk", "elementary-grape"),
        ("material", "Adwaita"),
    )
    combinations = [
        (theme, variant, style, icon_theme)
        for theme in themes
        for variant in ("dark", "light")
        for style, icon_theme in icon_styles
    ]
    for index, (theme, variant, style, icon_theme) in enumerate(combinations):
        window.preferences.theme = theme
        window.preferences.theme_variant = variant
        window.preferences.icon_style = style
        window.preferences.background_blur = index % 2 == 1
        window._apply_appearance_preferences()
        if style == "gtk":
            # As if the desktop switched icon theme while Harmonia is open.
            settings.set_property("gtk-icon-theme-name", icon_theme)
        yield 60
        active = settings.get_property("gtk-icon-theme-name")
        log(f"tema {theme} · {variant} · ícones {style}/{icon_theme} → {active}")
        # The whole app on the first combination, the main pages afterwards:
        # theme and icon problems show up there, and the run stays short.
        yield from _visit_pages(window, log, full=index == 0)
    for accent in ("blue", "green", "pink"):
        window.preferences.accent = accent
        window._apply_appearance_preferences()
        window.show_home()
        yield 60


def _page_problem(window, name: str) -> str | None:
    """Why the page is not ready: not open, an error or still loading."""
    from gi.repository import Adw

    visible = window.stack.get_visible_child_name()
    if visible != name:
        return f"página {name!r} esperada, aberta {visible!r}"
    page = window.stack.get_visible_child()
    if isinstance(page, Adw.StatusPage) and (
        page.get_icon_name() in ("view-refresh-symbolic", "dialog-error-symbolic")
        or page.get_title() == "Buscando…"  # the search placeholder
    ):
        return f"página {name!r} mostra {page.get_title()!r}: {page.get_description()!r}"
    return None


def _expect_page(window, name: str, timeout: float = 15.0):
    """Wait for a page to finish loading; fail if it never does.

    Pages load in worker threads, and CI renders in software on two CPUs, so a
    fixed delay is either too short there or wastes time everywhere else.
    """
    deadline = time.monotonic() + timeout
    while (problem := _page_problem(window, name)) and time.monotonic() < deadline:
        yield 50
    if problem:
        print(f"SMOKE-FAIL {problem}", flush=True)


def _visit_pages(window, log, full: bool):
    from harmonia.models import ArtistSection, ExploreDestination

    samples = window.youtube.samples
    log("início")
    window.show_home()
    yield 80
    yield from _expect_page(window, "home")
    log("explorar")
    window.show_explore()
    yield 80
    yield from _expect_page(window, "explore")
    window.open_destination(ExploreDestination("Lançamentos", "FEmusic_new_releases"))
    yield 120
    yield from _expect_page(window, "discovery")
    for origin in ("youtube", "uploads", "downloads", "local", "podcasts"):
        window.show_library()
        window._set_library_origin(origin)
        filters = ("albums", "artists", "songs", "playlists") if full else ("albums", "songs")
        for key in filters:
            log(f"biblioteca {origin}/{key}")
            window._set_library_filter(key)
            yield 50
            yield from _expect_page(window, "library")
    if full:
        window._set_library_sort("title")
        yield 50
        window._set_library_sort("recent")
    log("álbum")
    window.open_item(samples.album)
    yield 150
    yield from _expect_page(window, "detail")
    log("playlist")
    window.open_item(samples.playlist)
    yield 150
    yield from _expect_page(window, "detail")
    log("artista")
    window._open_artist(samples.artist)
    yield 150
    yield from _expect_page(window, "artist")
    window._open_artist_section(ArtistSection("Singles", samples.songs, "UCartist", "params"))
    yield 150
    yield from _expect_page(window, "artist-section")
    log("busca")
    window.search_entry.set_text("elis & tom")
    window.search("elis & tom")
    yield 200
    yield from _expect_page(window, "search")
    log("sugestões")
    window.search_entry.grab_focus()
    window._show_search_suggestions(window._suggestion_request, "elis & tom", samples.suggestions)
    yield 80
    window.search_suggestions.popdown()
    log("histórico")
    window.show_history()
    yield 150
    yield from _expect_page(window, "history")
    log("estatísticas")
    window.show_insights()
    yield 100
    yield from _expect_page(window, "insights")
    log("downloads")
    window.show_downloads()
    yield 100
    yield from _expect_page(window, "downloads")
    log("configurações")
    window.show_settings()
    yield 120
    yield from _expect_page(window, "settings")
    if not full:
        return
    log("fila e player expandido")
    window.set_queue(samples.songs, 0)
    yield 400
    window._show_expanded_player()
    for page in ("music", "lyrics", "related"):
        window.expanded_stack.set_visible_child_name(page)
        yield 200
    window._hide_expanded_player()
    yield 100
    log("letras e fila no rodapé")
    window.lyrics_button.popup()
    yield 200
    window.lyrics_button.popdown()
    window.queue_button.popup()
    yield 120
    window.queue_button.popdown()
    log("playlist local")
    window._show_local_playlist(window.storage.load_local_playlists()[0])
    yield 100
    window._stop_player()
    yield 60


# --------------------------------------------------------------------------- #
# Sample data.


class _Samples:
    def __init__(self, folder: Path) -> None:
        from harmonia.models import (
            ArtistPage,
            ArtistSection,
            ExploreData,
            ExploreDestination,
            HomeSection,
            LibraryItem,
            SearchGroup,
        )

        folder.mkdir(parents=True, exist_ok=True)
        self.folder = folder
        covers = [self._cover(folder / f"cover-{index}.png", index) for index in range(6)]
        self.audio = self._silence(folder / "silence.wav")

        def cover(index: int) -> str:
            return covers[index % len(covers)].as_uri()

        names = [
            ("Águas de Março", "Elis & Tom", "Elis Regina"),
            ("Garota de Ipanema", "Getz/Gilberto", "João Gilberto"),
            ("Construção", "Construção", "Chico Buarque"),
            ("Sozinho", "Sozinho <ao vivo>", "Caetano Veloso"),
            ("Oceano", "Djavan", "Djavan"),
            (
                "Um título muito longo para testar o corte do texto em linhas estreitas",
                "",
                "Vários",
            ),
        ]
        self.songs = [
            LibraryItem(
                f"vid{index:08d}",
                title,
                f"{artist} • {album}" if album else artist,
                cover(index),
                "songs",
                artist=artist,
                artist_id=f"UCartist{index}",
                album=album,
                album_id=f"MPREalbum{index}" if album else None,
                links=(("artist", artist, f"UCartist{index}"),)
                + ((("album", album, f"MPREalbum{index}"),) if album else ()),
            )
            for index, (title, album, artist) in enumerate(names)
        ]
        self.album = LibraryItem("MPREalbum0", "Elis & Tom", "Álbum • 1974", cover(0), "albums")
        self.playlist = LibraryItem(
            "VLPLsample", "Bossa nova & MPB", "Playlist • 6 faixas", cover(1), "playlists"
        )
        self.artist = LibraryItem("UCartist0", "Elis Regina", "Artista", cover(2), "artists")
        self.albums = [
            LibraryItem(f"MPREalbum{index}", song.album or song.title, "Álbum", song.thumbnail,
                        "albums")
            for index, song in enumerate(self.songs)
        ]  # fmt: skip
        self.artists = [
            LibraryItem(song.artist_id, song.artist, "Artista", song.thumbnail, "artists")
            for song in self.songs
        ]
        self.playlists = [self.playlist] + [
            LibraryItem(f"VLPL{index}", f"Mix {index}", "Playlist", cover(index), "playlists")
            for index in range(3)
        ]
        self.podcasts = [
            LibraryItem("MPSPpodcast", "Podcast & Conversa", "Podcast", cover(3), "podcasts")
        ]
        self.home = [
            HomeSection("Ouvir novamente", self.songs),
            HomeSection("Álbuns para você", self.albums),
            HomeSection("Artistas", self.artists),
            HomeSection("Playlists & mixes", self.playlists),
        ]
        destinations = [
            ExploreDestination("Lançamentos", "FEmusic_new_releases"),
            ExploreDestination("Paradas", "FEmusic_charts"),
            ExploreDestination("Momentos e gêneros", "FEmusic_moods_and_genres"),
        ]
        genres = [ExploreDestination(name, "FEmusic_moods_and_genres_category", name)
                  for name in ("Samba", "Rock & Roll", "Forró", "Jazz")]  # fmt: skip
        self.explore = ExploreData(self.home[:2], destinations, genres)
        self.artist_page = ArtistPage(
            "UCartist0",
            "Elis Regina",
            "Cantora brasileira. Uma descrição com <marcação> & símbolos.",
            cover(2),
            "1,2 mi de inscritos",
            False,
            [
                ArtistSection("Músicas", self.songs, "VLPLsongs"),
                ArtistSection("Álbuns", self.albums, "UCartist0", "albums"),
                ArtistSection("Singles", self.albums[:2], "UCartist0", "singles"),
                ArtistSection("Artistas semelhantes", self.artists[1:]),
            ],
        )
        self.search_groups = [
            SearchGroup("songs", "Músicas", self.songs, "next"),
            SearchGroup("videos", "Vídeos", self.songs[:2]),
            SearchGroup("albums", "Álbuns", self.albums),
            SearchGroup("artists", "Artistas", self.artists),
            SearchGroup("playlists", "Playlists", self.playlists),
        ]
        self.suggestions = ["elis regina", "elis & tom", "elis regina águas de março"]
        self.lyrics = (
            "[00:00.50] Águas de março fechando o verão\n"
            "[00:03.00] É a promessa de vida no teu coração\n"
            "[00:06.00] É pau, é pedra, é o fim do caminho\n"
        )

    @staticmethod
    def _cover(path: Path, index: int) -> Path:
        from gi.repository import GdkPixbuf

        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 96, 96)
        palette = (0x8E44ADFF, 0x2E86C1FF, 0x28B463FF, 0xD68910FF, 0xC0392BFF, 0x5D6D7EFF)
        pixbuf.fill(palette[index % len(palette)])
        pixbuf.savev(str(path), "png", [], [])
        return path

    @staticmethod
    def _silence(path: Path) -> Path:
        import wave

        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(b"\0\0" * 8000 * 3)
        return path


class _FakeService:
    """Answers the window's service calls with sample data, never the network."""

    def __init__(self, storage, samples: _Samples) -> None:
        self.storage = storage
        self.samples = samples
        # HARMONIA_SMOKE_DELAY=1.5 makes page loads as slow as a busy network
        # (or a CI runner), to exercise the loading states.
        self.delay = float(os.environ.get("HARMONIA_SMOKE_DELAY", "0"))

    def _slow(self) -> None:
        if self.delay:
            time.sleep(self.delay)

    def connect(self, cookie: str) -> bool:
        self.storage.save_cookie(cookie)
        return True

    def disconnect(self) -> None:
        self.storage.clear_cookie()

    def validate_account(self) -> bool:
        return True

    def account_profile(self):
        from harmonia.models import AccountProfile

        return AccountProfile("Pessoa de Teste", None, "teste@example.org", "@teste")

    def sync_library(self):
        samples = self.samples
        sections = {
            "playlists": samples.playlists,
            "songs": samples.songs,
            "albums": samples.albums,
            "artists": samples.artists,
            "uploads": samples.songs[:3],
            "uploaded-albums": samples.albums[:2],
            "podcasts": samples.podcasts,
            "podcast-episodes": samples.songs[:2],
        }
        self.storage.save_library(sections)
        return sections

    def sync_home(self):
        self.storage.save_home(self.samples.home)
        return self.samples.home

    def sync_explore(self):
        self.storage.save_explore(self.samples.explore)
        return self.samples.explore

    def discovery(self, _destination):
        self._slow()
        return self.samples.explore

    def browse(self, _item):
        self._slow()
        return self.samples.songs

    def artist(self, _artist_id):
        self._slow()
        return self.samples.artist_page

    def artist_section(self, _section):
        self._slow()
        return self.samples.albums

    def mutate(self, _operation):
        return None

    def radio(self, _video_id):
        return self.samples.songs[::-1]

    def lyrics(self, _video_id):
        return self.samples.lyrics

    def history(self):
        from harmonia.models import HistoryEntry

        return [
            HistoryEntry(None, song, None, 0, "youtube", group, f"token{index}")
            for index, (song, group) in enumerate(
                zip(
                    self.samples.songs,
                    ("Hoje", "Hoje", "Ontem", "Esta semana", "Março", "Março"),
                    strict=True,
                )
            )
        ]

    def remove_history_item(self, _token):
        return None

    def universal_search(self, query):
        self._slow()
        from harmonia.models import SearchResults

        return SearchResults(query, list(self.samples.search_groups))

    def search_more(self, _query, group):
        from harmonia.models import SearchGroup

        return SearchGroup(group.key, group.title, group.items + self.samples.songs)

    def suggestions(self, _query):
        return self.samples.suggestions

    def resolve_stream(self, video_id, force=False):
        from harmonia.models import StreamInfo

        return StreamInfo(self.samples.audio.as_uri(), 3000, "smoke", "audio/wav")

    def resolve_video(self, *_args, **_kwargs):
        raise RuntimeError("vídeo indisponível no smoke")

    def register_playback(self, *_args, **_kwargs):
        return None


def _seed_storage(storage, samples: _Samples) -> None:
    from harmonia.models import DownloadRecord, LocalPlaylist

    storage.save_cookie("SAPISID=smoke; __Secure-3PAPISID=smoke")
    storage.set_setting("lyrics_provider", "youtube")
    service = _FakeService(storage, samples)
    service.sync_library()
    service.sync_home()
    service.sync_explore()
    for position, song in enumerate(samples.songs[:4]):
        storage.record_history(song, position * 1000)
    statuses = ("completed", "downloading", "failed", "queued")
    for song, status in zip(samples.songs, statuses, strict=False):
        storage.save_download(
            DownloadRecord(
                song,
                status,
                str(samples.audio) if status == "completed" else "",
                40_000 if status == "downloading" else 0,
                120_000 if status == "downloading" else 0,
                error="Não foi possível baixar: erro & teste" if status == "failed" else "",
            )
        )
    storage.add_local_files([str(samples.audio)])
    storage.save_local_playlist(LocalPlaylist(None, "Favoritas & raras", samples.songs[:3]))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
