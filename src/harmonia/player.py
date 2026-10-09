from __future__ import annotations

import logging
import urllib.parse
import urllib.request
from itertools import pairwise
from typing import ClassVar

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst

from . import loudness
from .i18n import _
from .stream_relay import StreamRelay

LOGGER = logging.getLogger(__name__)


class NativePlayer:
    """Thin GStreamer playbin wrapper kept independent from the GTK widgets."""

    EQ_PRESETS: ClassVar[dict[str, tuple[int, ...]]] = {
        "flat": (0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        "bass": (6, 5, 3, 1, 0, 0, -1, -1, 0, 0),
        "vocal": (-2, -1, 0, 2, 4, 4, 2, 1, 0, -1),
        "treble": (-2, -1, 0, 0, 1, 2, 3, 4, 5, 6),
    }

    def __init__(self, on_state=None, on_error=None, on_eos=None):
        Gst.init(None)
        self._playbin = Gst.ElementFactory.make("playbin", "harmonia-player")
        if self._playbin is None:
            raise RuntimeError(_("O elemento GStreamer playbin não está disponível"))
        self._audio_elements: dict[str, Gst.Element] = {}
        self._normalization: tuple[bool, str] = (False, loudness.DEFAULT_LEVEL)
        self._track_loudness: float | None = None
        self._video_sink: Gst.Element | None = None
        self._replace_generation = 0
        self._install_audio_filter()
        self.on_state = on_state
        self.on_error = on_error
        self.on_eos = on_eos
        self._last_position_us = 0
        self._relay = StreamRelay()
        self._bus = self._playbin.get_bus()
        self._bus.add_signal_watch()
        self._bus.connect("message", self._on_message)

    def _install_audio_filter(self) -> None:
        """Attach one reusable native processing graph to playbin."""
        factories = (
            ("convert-in", "audioconvert"),
            ("pitch", "pitch"),
            ("equalizer", "equalizer-10bands"),
            ("replaygain", "rgvolume"),
            ("limiter", "rglimiter"),
            ("convert-mid", "audioconvert"),
            ("silence", "removesilence"),
            ("convert-out", "audioconvert"),
        )
        elements: list[Gst.Element] = []
        audio_filter = Gst.Bin.new("harmonia-audio-filter")
        for key, factory in factories:
            element = Gst.ElementFactory.make(factory, f"harmonia-{key}")
            if element is None:
                return
            audio_filter.add(element)
            self._audio_elements[key] = element
            elements.append(element)
        for previous, following in pairwise(elements):
            if not previous.link(following):
                self._audio_elements.clear()
                return
        audio_filter.add_pad(Gst.GhostPad.new("sink", elements[0].get_static_pad("sink")))
        audio_filter.add_pad(Gst.GhostPad.new("src", elements[-1].get_static_pad("src")))
        self._playbin.set_property("audio-filter", audio_filter)
        self.apply_audio_settings()

    def apply_audio_settings(
        self,
        *,
        normalization: bool = False,
        normalization_level: str = loudness.DEFAULT_LEVEL,
        equalizer: str = "flat",
        speed: float = 1.0,
        pitch: float = 0.0,
        skip_silence: bool = False,
    ) -> None:
        """Apply processing atomically; safe when optional plugins are absent."""
        self._normalization = (normalization, normalization_level)
        self._apply_normalization()
        pitch_filter = self._audio_elements.get("pitch")
        if pitch_filter:
            pitch_filter.set_property("tempo", max(0.5, min(2.0, speed)))
            pitch_filter.set_property("pitch", 2 ** (max(-12, min(12, pitch)) / 12))
        equalizer_filter = self._audio_elements.get("equalizer")
        if equalizer_filter:
            bands = self.EQ_PRESETS.get(equalizer, self.EQ_PRESETS["flat"])
            for index, gain in enumerate(bands):
                equalizer_filter.set_property(f"band{index}", float(gain))
        silence = self._audio_elements.get("silence")
        if silence:
            silence.set_property("remove", skip_silence)
            silence.set_property("squash", skip_silence)
            silence.set_property("minimum-silence-time", 1_500_000_000 if skip_silence else 0)

    def set_track_loudness(self, loudness_db: float | None) -> None:
        """The loudness of the track about to play, None when unknown."""
        self._track_loudness = loudness_db
        self._apply_normalization()

    def _apply_normalization(self) -> None:
        settings = loudness.replaygain_settings(*self._normalization, self._track_loudness)
        replaygain = self._audio_elements.get("replaygain")
        if replaygain:
            replaygain.set_property("album-mode", False)
            replaygain.set_property("pre-amp", settings.pre_amp)
            replaygain.set_property("fallback-gain", settings.fallback_gain)
            replaygain.set_property("headroom", settings.headroom)
        limiter = self._audio_elements.get("limiter")
        if limiter:
            limiter.set_property("enabled", settings.limiter)

    @property
    def video_sink(self) -> Gst.Element | None:
        return self._video_sink

    def play(self, uri: str) -> None:
        self._replace_generation += 1
        self._playbin.set_state(Gst.State.NULL)
        self._last_position_us = 0
        self._playbin.set_property("uri", self._source_uri(uri))
        self._playbin.set_state(Gst.State.PLAYING)

    def replace(
        self,
        uri: str,
        position_us: int = 0,
        playing: bool | None = None,
        request_headers: dict[str, str] | None = None,
    ) -> None:
        """Replace only the media source while preserving transport state/position.

        This is intentionally separate from :meth:`play`: callers use it for
        Music <-> Video switching inside the same logical track, so queue,
        MPRIS, history and scrobble generation stay untouched.
        """
        should_play = self.playing if playing is None else bool(playing)
        target = max(0, int(position_us))
        self._replace_generation += 1
        generation = self._replace_generation
        self._playbin.set_state(Gst.State.NULL)
        self._last_position_us = target
        self._playbin.set_property("uri", self._source_uri(uri, request_headers))
        # Preroll paused first; seeking before preroll is unreliable for remote
        # MP4 streams and can briefly play from 0 before the requested position.
        self._playbin.set_state(Gst.State.PAUSED)
        GLib.timeout_add(40, self._finish_replace, generation, target, should_play, 0)

    def _finish_replace(
        self,
        generation: int,
        target: int,
        should_play: bool,
        attempt: int,
    ) -> bool:
        if generation != self._replace_generation:
            return GLib.SOURCE_REMOVE
        _result, state, _pending = self._playbin.get_state(0)
        ready = state in (Gst.State.PAUSED, Gst.State.PLAYING)
        if not ready and attempt < 50:
            GLib.timeout_add(40, self._finish_replace, generation, target, should_play, attempt + 1)
            return GLib.SOURCE_REMOVE
        if target:
            self.seek(target)
        self._playbin.set_state(Gst.State.PLAYING if should_play else Gst.State.PAUSED)
        return GLib.SOURCE_REMOVE

    def _source_uri(
        self,
        uri: str,
        request_headers: dict[str, str] | None = None,
    ) -> str:
        scheme = urllib.parse.urlsplit(uri).scheme
        if scheme == "file" or (scheme == "http" and "googlevideo.com" not in uri):
            return uri
        dash_uri = self._relay.dash_uri_for(uri, request_headers)
        if dash_uri is not None:
            return dash_uri
        return self._relay.uri_for(uri, request_headers)

    def toggle(self) -> None:
        _result, state, _pending = self._playbin.get_state(0)
        self._playbin.set_state(
            Gst.State.PAUSED if state == Gst.State.PLAYING else Gst.State.PLAYING
        )

    def stop(self) -> None:
        self._replace_generation += 1
        self._playbin.set_state(Gst.State.NULL)
        self._last_position_us = 0

    def close(self) -> None:
        self.stop()
        self._bus.remove_signal_watch()
        self._relay.close()

    @property
    def volume(self) -> float:
        return float(self._playbin.get_property("volume"))

    @volume.setter
    def volume(self, value: float) -> None:
        self._playbin.set_property("volume", max(0.0, min(1.0, value)))

    @property
    def playing(self) -> bool:
        _result, state, _pending = self._playbin.get_state(0)
        return state == Gst.State.PLAYING

    @property
    def position_us(self) -> int:
        ok, value = self._playbin.query_position(Gst.Format.TIME)
        if ok:
            self._last_position_us = int(value // 1000)
        return self._last_position_us

    @property
    def duration_us(self) -> int:
        ok, value = self._playbin.query_duration(Gst.Format.TIME)
        return int(value // 1000) if ok else 0

    def seek(self, position_us: int) -> bool:
        target = max(0, position_us)
        accepted = self._playbin.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
            target * 1000,
        )
        if accepted:
            self._last_position_us = target
        return accepted

    def _on_message(self, _bus, message) -> None:
        if message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            try:
                source = message.src.get_path_string() if message.src is not None else "unknown"
            except Exception:
                source = "unknown"
            LOGGER.error(
                "GStreamer playback error from %s: %s (%s)",
                source,
                error,
                debug or "sem debug",
            )
            if self.on_error:
                GLib.idle_add(self.on_error, str(error))
        elif message.type == Gst.MessageType.EOS:
            position, duration = self.position_us, self.duration_us
            self.stop()
            if duration > 0 and position + 2_000_000 < duration:
                if self.on_error:
                    GLib.idle_add(
                        self.on_error,
                        _(
                            "O fluxo de áudio terminou antes do esperado "
                            "({position}s de {duration}s)"
                        ).format(
                            position=position // 1_000_000,
                            duration=duration // 1_000_000,
                        ),
                    )
            elif self.on_eos:
                GLib.idle_add(self.on_eos)
        elif message.type == Gst.MessageType.STATE_CHANGED and message.src == self._playbin:
            _old, new, _pending = message.parse_state_changed()
            if self.on_state:
                GLib.idle_add(self.on_state, new == Gst.State.PLAYING)
