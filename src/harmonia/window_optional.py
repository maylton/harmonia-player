from __future__ import annotations

import logging
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk

from .cast import LocalMediaServer, UpnpDiscovery, UpnpRenderer
from .i18n import _
from .recognition import AuddRecognitionProvider, MusicRecognizer, RecognitionTokenStore
from .together import TogetherClient, TogetherHost, TogetherState

LOGGER = logging.getLogger(__name__)


class WindowOptionalMixin:
    def _initialize_optional_services(self) -> None:
        self.recognition_tokens = RecognitionTokenStore(self.storage)
        self.together_host = None
        self.together_client = None
        self._together_share_url = ""
        self._together_fetching = False
        self._together_revision = -1
        self._together_pending_state = None
        self._together_applying = False
        self.cast_renderer = None
        self.cast_device = None
        self._cast_playing = False
        self._cast_position_ms = 0
        self._cast_started = 0.0
        self._current_stream_url = ""
        self._cast_media_server = None
        GLib.timeout_add_seconds(1, self._optional_tick)
        self.connect("close-request", self._close_optional_services)

    def _append_optional_preferences(self, page: Adw.PreferencesPage) -> None:
        together = Adw.PreferencesGroup(
            title=_("Listen Together"),
            description=_("Sincroniza fila e reprodução entre dispositivos na mesma rede local."),
        )
        status = Adw.ActionRow(title=_("Sessão compartilhada"), subtitle=self._together_status())
        if self.together_host or self.together_client:
            leave = Gtk.Button(label=_("Sair"), valign=Gtk.Align.CENTER)
            leave.add_css_class("pill")
            leave.connect("clicked", lambda *_: self._leave_together_session())
            status.add_suffix(leave)
        else:
            create = Gtk.Button(label=_("Criar sessão"), valign=Gtk.Align.CENTER)
            create.add_css_class("pill")
            create.add_css_class("suggested-action")
            create.connect("clicked", lambda *_: self._create_together_session())
            status.add_suffix(create)
        together.add(status)
        join = Adw.ActionRow(
            title=_("Entrar com link"),
            subtitle=_("Cole o link harmonia:// enviado pelo anfitrião"),
        )
        join_entry = Gtk.Entry(
            placeholder_text="harmonia://listen-together…", valign=Gtk.Align.CENTER
        )
        join_entry.set_size_request(310, -1)
        join.add_suffix(join_entry)
        join_button = Gtk.Button(label=_("Entrar"), valign=Gtk.Align.CENTER)
        join_button.add_css_class("pill")
        join_button.connect(
            "clicked", lambda *_: self._join_together_session(join_entry.get_text())
        )
        join.add_suffix(join_button)
        together.add(join)
        if self._together_share_url:
            share = Adw.ActionRow(title=_("Link da sessão"), subtitle=self._together_share_url)
            copy = Gtk.Button(label=_("Copiar"), valign=Gtk.Align.CENTER)
            copy.add_css_class("pill")
            copy.connect(
                "clicked",
                lambda *_: Gdk.Display.get_default().get_clipboard().set(self._together_share_url),
            )
            share.add_suffix(copy)
            together.add(share)
        page.add(together)

        recognition = Adw.PreferencesGroup(
            title=_("Reconhecimento de música"),
            description=_("Captura temporariamente 12 segundos do microfone e apaga a amostra."),
        )
        provider = Adw.ComboRow(
            title=_("Provedor"),
            model=Gtk.StringList.new(["AudD", _("API compatível com AudD")]),
        )
        provider.set_selected(1 if self.preferences.recognition_provider == "custom" else 0)
        provider.connect(
            "notify::selected",
            lambda row, _pspec: self._preference_changed(
                "recognition_provider", "custom" if row.get_selected() == 1 else "audd"
            ),
        )
        recognition.add(provider)
        endpoint = Adw.ActionRow(
            title=_("Endpoint do provedor"),
            subtitle=_("Usado somente no modo de API compatível"),
        )
        endpoint_entry = Gtk.Entry(
            text=self.preferences.recognition_endpoint,
            placeholder_text="https://api.audd.io/",
            valign=Gtk.Align.CENTER,
        )
        endpoint_entry.set_size_request(310, -1)
        endpoint_entry.connect(
            "changed",
            lambda entry: self._preference_changed(
                "recognition_endpoint", entry.get_text().strip()
            ),
        )
        endpoint.add_suffix(endpoint_entry)
        recognition.add(endpoint)
        token = Adw.ActionRow(
            title=_("Token da API AudD"), subtitle=_("Armazenado no chaveiro do sistema")
        )
        token_entry = Gtk.PasswordEntry(
            placeholder_text=_("Configurado") if self.recognition_tokens.load() else _("Token"),
            show_peek_icon=True,
            valign=Gtk.Align.CENTER,
        )
        token_entry.set_size_request(260, -1)
        token_entry.connect(
            "activate", lambda entry: self.recognition_tokens.save(entry.get_text())
        )
        token_focus = Gtk.EventControllerFocus()
        token_focus.connect(
            "leave", lambda *_: self.recognition_tokens.save(token_entry.get_text())
        )
        token_entry.add_controller(token_focus)
        token.add_suffix(token_entry)
        recognize = Gtk.Button(label=_("Reconhecer agora"), valign=Gtk.Align.CENTER)
        recognize.add_css_class("pill")
        recognize.add_css_class("suggested-action")
        recognize.connect("clicked", lambda *_: self._recognize_music())
        token.add_suffix(recognize)
        recognition.add(token)
        page.add(recognition)

        devices = Adw.PreferencesGroup(
            title=_("Transmitir para dispositivo"),
            description=_("Descobre Media Renderers UPnP/DLNA na rede local."),
        )
        cast = Adw.ActionRow(
            title=_("Dispositivo de reprodução"),
            subtitle=self.cast_device.name if self.cast_device else _("Este computador"),
        )
        if self.cast_renderer:
            disconnect = Gtk.Button(label=_("Desconectar"), valign=Gtk.Align.CENTER)
            disconnect.add_css_class("pill")
            disconnect.connect("clicked", lambda *_: self._disconnect_cast())
            cast.add_suffix(disconnect)
        scan = Gtk.Button(label=_("Procurar"), valign=Gtk.Align.CENTER)
        scan.add_css_class("pill")
        scan.connect("clicked", lambda *_: self._scan_cast_devices(cast))
        cast.add_suffix(scan)
        devices.add(cast)
        page.add(devices)

    def _together_status(self) -> str:
        if self.together_host:
            return _("Você está compartilhando a reprodução")
        if self.together_client:
            return _("Sincronizado com o anfitrião")
        return _("Nenhuma sessão ativa")

    def _create_together_session(self) -> None:
        self._leave_together_session(refresh=False)
        try:
            self.together_host = TogetherHost()
            self._together_share_url = self.together_host.share_url()
            self.toast_overlay.add_toast(Adw.Toast(title=_("Sessão Listen Together criada")))
            self.show_settings()
        except OSError as exc:
            self.toast_overlay.add_toast(
                Adw.Toast(title=_("Não foi possível criar a sessão: {error}").format(error=exc))
            )

    def _join_together_session(self, url: str) -> None:
        try:
            client = TogetherClient(url)
        except ValueError as exc:
            self.toast_overlay.add_toast(Adw.Toast(title=str(exc)))
            return

        def connected(state, error):
            if error:
                self.toast_overlay.add_toast(
                    Adw.Toast(
                        title=_("Não foi possível entrar na sessão: {error}").format(error=error)
                    )
                )
                return False
            self._leave_together_session(refresh=False)
            self.together_client = client
            self._together_revision = -1
            self._apply_together_state(state)
            self.toast_overlay.add_toast(Adw.Toast(title=_("Listen Together conectado")))
            self.show_settings()
            return False

        self._optional_worker("together-join", client.fetch, connected)

    def _leave_together_session(self, *, refresh: bool = True) -> None:
        if self.together_host:
            self.together_host.close()
        self.together_host = None
        self.together_client = None
        self._together_share_url = ""
        self._together_revision = -1
        self._together_pending_state = None
        if refresh and getattr(self, "main_view", "") == "settings":
            self.show_settings()

    def _optional_tick(self) -> bool:
        if self.together_host:
            self.together_host.update(
                TogetherState(
                    list(self.queue),
                    max(0, self.queue_index),
                    self._playback_position_us() // 1000,
                    self._playback_is_playing(),
                )
            )
        elif self.together_client and not self._together_fetching:
            self._together_fetching = True

            def completed(state, error):
                self._together_fetching = False
                if not error and state.revision > self._together_revision:
                    self._apply_together_state(state)
                return False

            self._optional_worker("together-sync", self.together_client.fetch, completed)
        return GLib.SOURCE_CONTINUE

    def _apply_together_state(self, state: TogetherState) -> None:
        self._together_revision = state.revision
        if not state.queue:
            return
        state.index = min(state.index, len(state.queue) - 1)
        target = state.queue[state.index]
        position_ms = state.corrected_position_ms()
        current = getattr(self, "current_item", None)
        self._together_applying = True
        try:
            if current is None or current.id != target.id:
                self.queue = list(state.queue)
                self.queue_index = state.index
                self._restored_position_ms = position_ms
                self._together_pending_state = state
                self._render_queue()
                self.play_item(target)
                return
            self.queue = list(state.queue)
            self.queue_index = state.index
            if abs(self._playback_position_us() // 1000 - position_ms) > 1_500:
                self._seek_playback(position_ms * 1000)
            if state.playing != self._playback_is_playing():
                self._toggle_player()
        finally:
            self._together_applying = False

    def _optional_stream_started(self) -> None:
        state = self._together_pending_state
        if state:
            self._together_pending_state = None
            if not state.playing and self._playback_is_playing():
                GLib.timeout_add(300, lambda: self._pause() or GLib.SOURCE_REMOVE)

    def _recognize_music(self) -> None:
        token = self.recognition_tokens.load()
        if not token:
            self.toast_overlay.add_toast(Adw.Toast(title=_("Configure o token do AudD primeiro")))
            return
        self.toast_overlay.add_toast(Adw.Toast(title=_("Ouvindo por 12 segundos…"), timeout=4))
        endpoint = (
            self.preferences.recognition_endpoint
            if self.preferences.recognition_provider == "custom"
            else None
        )
        recognizer = MusicRecognizer(AuddRecognitionProvider(token, endpoint=endpoint))

        def completed(result, error):
            if error:
                self.toast_overlay.add_toast(
                    Adw.Toast(title=_("Reconhecimento falhou: {error}").format(error=error))
                )
            elif result is None:
                self.toast_overlay.add_toast(Adw.Toast(title=_("Nenhuma música reconhecida")))
            else:
                self.toast_overlay.add_toast(
                    Adw.Toast(
                        title=_("Encontrada: {title} — {artist}").format(
                            title=result.title, artist=result.artist
                        ),
                        timeout=6,
                    )
                )
                self.search_entry.set_text(f"{result.artist} {result.title}")
                self.search(self.search_entry.get_text())
            return False

        self._optional_worker("recognition", recognizer.recognize, completed)

    def _scan_cast_devices(self, row: Adw.ActionRow) -> None:
        row.set_subtitle(_("Procurando na rede local…"))

        def completed(devices, error):
            if error:
                row.set_subtitle(_("Falha na descoberta: {error}").format(error=error))
                return False
            if not devices:
                row.set_subtitle(_("Nenhum dispositivo encontrado"))
                return False
            dialog = Adw.AlertDialog(
                heading=_("Escolha um dispositivo"),
                body=_("A faixa atual será transferida para o dispositivo selecionado."),
            )
            dialog.add_response("cancel", _("Cancelar"))
            for index, device in enumerate(devices):
                dialog.add_response(f"device-{index}", device.name)

            def selected(_dialog, response: str):
                if response.startswith("device-"):
                    self._connect_cast(devices[int(response.removeprefix("device-"))])

            dialog.connect("response", selected)
            dialog.present(self)
            row.set_subtitle(_("{count} dispositivo(s) encontrado(s)").format(count=len(devices)))
            return False

        self._optional_worker("cast-discovery", UpnpDiscovery().discover, completed)

    def _connect_cast(self, device) -> None:
        if not self._current_stream_url or getattr(self, "current_item", None) is None:
            self.toast_overlay.add_toast(
                Adw.Toast(title=_("Comece a reproduzir uma faixa antes de transmitir"))
            )
            return
        try:
            cast_uri = self._castable_uri(self._current_stream_url)
        except OSError as exc:
            self.toast_overlay.add_toast(
                Adw.Toast(title=_("Não foi possível transmitir: {error}").format(error=exc))
            )
            return
        self.cast_device = device
        renderer = UpnpRenderer(device)
        self.cast_renderer = renderer
        self._cast_position_ms = self.player.position_us // 1000
        self._cast_started = time.monotonic() - self._cast_position_ms / 1000
        self._cast_playing = True
        self.player.stop()
        self._optional_worker(
            "cast-start",
            lambda: renderer.play_uri(cast_uri, self.current_item.title),
            self._cast_started_done,
        )

    def _cast_started_done(self, _result, error):
        if error:
            self._disconnect_cast(resume=True)
            self.toast_overlay.add_toast(
                Adw.Toast(title=_("Não foi possível transmitir: {error}").format(error=error))
            )
        else:
            self._player_state(True, remote=True)
            self.toast_overlay.add_toast(
                Adw.Toast(title=_("Reproduzindo em {device}").format(device=self.cast_device.name))
            )
            if self.main_view == "settings":
                self.show_settings()
        return False

    def _disconnect_cast(self, *, resume: bool = True) -> None:
        renderer = self.cast_renderer
        position_ms = self._playback_position_us() // 1000
        if renderer:
            self._optional_worker("cast-stop", renderer.stop)
        self.cast_renderer = None
        self.cast_device = None
        self._cast_playing = False
        self._close_cast_media_server()
        if resume and self._current_stream_url:
            self.player.play(self._current_stream_url)
            GLib.timeout_add(500, self._apply_pending_seek, self._play_request, position_ms)
        if getattr(self, "main_view", "") == "settings":
            self.show_settings()

    def _optional_start_stream(self, url: str) -> bool:
        self._current_stream_url = url
        if not self.cast_renderer:
            return False
        self._cast_position_ms = 0
        self._cast_started = time.monotonic()
        self._cast_playing = True
        item = self.current_item
        renderer = self.cast_renderer
        try:
            cast_uri = self._castable_uri(url)
        except OSError as exc:
            self.toast_overlay.add_toast(
                Adw.Toast(title=_("Não foi possível transmitir: {error}").format(error=exc))
            )
            self._disconnect_cast(resume=False)
            return False
        self._optional_worker(
            "cast-track",
            lambda: renderer.play_uri(cast_uri, item.title),
            self._cast_started_done,
        )
        return True

    def _optional_toggle_player(self) -> bool:
        if not self.cast_renderer:
            return False
        if self._cast_playing:
            self._cast_position_ms = self._playback_position_us() // 1000
            self._cast_playing = False
            self._optional_worker("cast-pause", self.cast_renderer.pause)
        else:
            self._cast_started = time.monotonic() - self._cast_position_ms / 1000
            self._cast_playing = True
            self._optional_worker("cast-play", self.cast_renderer.play)
        self._player_state(self._cast_playing, remote=True)
        return True

    def _seek_playback(self, position_us: int) -> bool:
        if not self.cast_renderer:
            return self.player.seek(position_us)
        self._cast_position_ms = max(0, position_us // 1000)
        if self._cast_playing:
            self._cast_started = time.monotonic() - self._cast_position_ms / 1000
        self._optional_worker("cast-seek", lambda: self.cast_renderer.seek(self._cast_position_ms))
        return True

    def _playback_position_us(self) -> int:
        if not self.cast_renderer:
            return self.player.position_us
        if self._cast_playing:
            return max(0, int((time.monotonic() - self._cast_started) * 1_000_000))
        return self._cast_position_ms * 1000

    def _playback_is_playing(self) -> bool:
        return self._cast_playing if self.cast_renderer else self.player.playing

    def _optional_ignore_local_state(self) -> bool:
        return self.cast_renderer is not None

    def _optional_stop(self) -> None:
        if self.cast_renderer:
            renderer = self.cast_renderer
            self.cast_renderer = None
            self.cast_device = None
            self._cast_playing = False
            self._optional_worker("cast-stop", renderer.stop)
        self._current_stream_url = ""
        self._close_cast_media_server()

    def _castable_uri(self, uri: str) -> str:
        self._close_cast_media_server()
        if uri.startswith("file:"):
            self._cast_media_server = LocalMediaServer.from_uri(uri)
            return self._cast_media_server.url
        return uri

    def _close_cast_media_server(self) -> None:
        if self._cast_media_server:
            self._cast_media_server.close()
            self._cast_media_server = None

    def _optional_worker(self, name: str, operation, completed=None) -> None:
        def worker():
            try:
                result, error = operation(), None
            except Exception as exc:
                LOGGER.debug("Falha no recurso opcional %s", name, exc_info=True)
                result, error = None, str(exc)
            if completed:
                GLib.idle_add(completed, result, error)

        threading.Thread(target=worker, daemon=True, name=f"optional-{name}").start()

    def _close_optional_services(self, *_args) -> bool:
        self._leave_together_session(refresh=False)
        self._optional_stop()
        return False
