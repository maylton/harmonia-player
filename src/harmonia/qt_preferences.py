from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from .backup import BackupManager
from .downloads import DownloadManager
from .equalizer import equalizer_gains
from .i18n import _
from .preferences import Preferences
from .qt_playback import QtPlaybackController
from .services import YouTubeMusicService
from .storage import Storage

LOGGER = logging.getLogger(__name__)


class QtPreferencesController(QObject):
    """Shared preference values with Qt-specific interaction plumbing."""

    changed = Signal()
    cacheChanged = Signal()
    _operationReady = Signal(str, bool, str)

    def __init__(
        self,
        storage: Storage,
        youtube: YouTubeMusicService,
        downloads: DownloadManager,
        playback: QtPlaybackController,
        executor: ThreadPoolExecutor,
        set_status: Callable[..., None],
        refresh_after_restore: Callable[[], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.storage = storage
        self.youtube = youtube
        self.downloads = downloads
        self.playback = playback
        self.executor = executor
        self.set_status = set_status
        self.refresh_after_restore = refresh_after_restore
        self.values = Preferences.load(self.storage)
        self._sleep_timer = QTimer(self)
        self._sleep_timer.setSingleShot(True)
        self._sleep_timer.timeout.connect(self._sleep_elapsed)
        self._operationReady.connect(self._operation_finished)
        self.apply_audio()

    @Property(bool, notify=changed)
    def backgroundBlur(self) -> bool:
        return self.values.background_blur

    @Slot(bool)
    def setBackgroundBlur(self, enabled: bool) -> None:
        self.set_background_blur(enabled)

    def reload(self) -> None:
        self.values = Preferences.load(self.storage)
        self.apply_audio()
        self.changed.emit()
        self.cacheChanged.emit()

    def save(self) -> None:
        self.values.save(self.storage)
        self.changed.emit()

    def apply_audio(self) -> None:
        self.playback.apply_audio_settings(
            normalization=self.values.normalization,
            normalization_level=self.values.normalization_level,
            equalizer=equalizer_gains(self.values.equalizer, self.storage.eq_profiles()),
            speed=self.values.speed,
            pitch=self.values.pitch,
            skip_silence=self.values.skip_silence,
            speed_pitch_linked=self.values.speed_pitch_linked,
            crossfade=self.values.crossfade,
        )

    def set_quality(self, value: str) -> None:
        if value not in Preferences.QUALITY_BITRATES or value == self.values.quality:
            return
        self.values.quality = value
        self.save()
        self.set_status(_("Qualidade de áudio atualizada."))

    def set_locale(self, language: str, region: str) -> None:
        language = language.strip() or "pt-BR"
        region = region.strip().upper() or "BR"
        if language == self.values.language and region == self.values.region:
            return
        self.values.language = language
        self.values.region = region
        self.save()
        self.set_status(_("Idioma e região salvos. Sincronize para atualizar o conteúdo."))

    def set_proxy(self, value: str) -> None:
        value = value.strip()
        if value == self.values.proxy:
            return
        self.values.proxy = value
        self.save()
        self.set_status(_("Proxy salvo. A próxima conexão usará esta configuração."))

    def set_background_blur(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self.values.background_blur:
            return
        self.values.background_blur = enabled
        self.save()
        self.set_status(
            _("Fundo ambiente desfocado ativado.")
            if enabled
            else _("Fundo ambiente desfocado desativado.")
        )

    def set_audio_value(self, name: str, value) -> None:
        if name == "normalization":
            self.values.normalization = bool(value)
        elif name == "equalizer":
            if value not in {"flat", "bass", "vocal", "treble"}:
                return
            self.values.equalizer = str(value)
        elif name == "speed":
            self.values.speed = max(0.5, min(2.0, float(value)))
        elif name == "pitch":
            self.values.pitch = max(-12.0, min(12.0, float(value)))
        elif name == "skip_silence":
            self.values.skip_silence = bool(value)
        else:
            return
        self.save()
        self.apply_audio()

    @property
    def cache_bytes(self) -> int:
        try:
            return sum(
                path.stat().st_size for path in self.storage.artwork_dir.iterdir() if path.is_file()
            )
        except OSError:
            return 0

    @staticmethod
    def format_bytes(value: int) -> str:
        size = float(max(0, value))
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.0f} {unit}" if unit in {"B", "KB"} else f"{size:.1f} {unit}"
            size /= 1024
        return "0 B"

    def clear_cache(self) -> None:
        removed = self.storage.clear_cache()
        self.cacheChanged.emit()
        self.set_status(
            _("Cache limpo · {size} removidos.").format(size=self.format_bytes(removed))
        )

    def validate_account(self) -> None:
        self.set_status(_("Validando sessão…"))

        def worker() -> None:
            try:
                valid = self.youtube.validate_account()
                self._operationReady.emit(
                    "account",
                    bool(valid),
                    "" if valid else _("Sessão inválida ou expirada"),
                )
            except Exception as exc:
                LOGGER.exception("Qt account validation failed")
                self._operationReady.emit("account", False, str(exc))

        self.executor.submit(worker)

    def validate_downloads(self) -> None:
        self.set_status(_("Validando conta dos downloads…"))

        def worker() -> None:
            try:
                self.downloads.validate_account()
                self._operationReady.emit("downloads", True, "")
            except Exception as exc:
                LOGGER.exception("Qt download validation failed")
                self._operationReady.emit("downloads", False, str(exc))

        self.executor.submit(worker)

    def export_backup(self, path: str) -> None:
        if not path:
            return
        target = Path(path)
        self.set_status(_("Exportando backup…"))

        def worker() -> None:
            try:
                BackupManager(self.storage).export_to(target)
                self._operationReady.emit("backup-export", True, str(target))
            except Exception as exc:
                LOGGER.exception("Qt backup export failed")
                self._operationReady.emit("backup-export", False, str(exc))

        self.executor.submit(worker)

    def restore_backup(self, path: str) -> None:
        if not path:
            return
        source = Path(path)
        self.set_status(_("Restaurando backup…"))

        def worker() -> None:
            try:
                BackupManager(self.storage).restore_from(source)
                self._operationReady.emit("backup-restore", True, str(source))
            except Exception as exc:
                LOGGER.exception("Qt backup restore failed")
                self._operationReady.emit("backup-restore", False, str(exc))

        self.executor.submit(worker)

    def set_sleep_timer(self, minutes: int) -> None:
        self._sleep_timer.stop()
        if minutes <= 0:
            self.set_status(_("Temporizador desligado."))
            return
        self._sleep_timer.start(minutes * 60 * 1000)
        self.set_status(_("Temporizador definido para {minutes} minutos.").format(minutes=minutes))

    def _sleep_elapsed(self) -> None:
        if self.playback.playing:
            self.playback.toggle_playback()
        self.set_status(_("Reprodução pausada pelo temporizador."))

    def _operation_finished(self, operation: str, ok: bool, detail: str) -> None:
        if not ok:
            labels = {
                "account": _("Não foi possível validar a conta"),
                "downloads": _("Não foi possível validar os downloads"),
                "backup-export": _("Não foi possível exportar o backup"),
                "backup-restore": _("Não foi possível restaurar o backup"),
            }
            label = labels.get(operation, _("Não foi possível concluir a operação"))
            self.set_status(_("{label}: {error}").format(label=label, error=detail), error=True)
            return
        if operation == "account":
            self.set_status(_("Conta conectada e válida."))
        elif operation == "downloads":
            self.set_status(_("Conta dos downloads validada."))
        elif operation == "backup-export":
            self.set_status(_("Backup exportado para {path}.").format(path=detail))
        elif operation == "backup-restore":
            self.reload()
            self.refresh_after_restore()
            self.set_status(_("Backup restaurado."))
