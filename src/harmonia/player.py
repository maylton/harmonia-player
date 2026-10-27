from __future__ import annotations

import logging
import urllib.parse
import urllib.request
from collections.abc import Sequence
from itertools import pairwise

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst

from . import loudness
from .equalizer import equalizer_gains
from .i18n import _
from .playback_speed import pitch_properties
from .playback_state import StreamEndedEarly
from .stream_relay import StreamRelay

LOGGER = logging.getLogger(__name__)


def error_source(message: Gst.Message) -> str:
    """The path of the element that posted a GStreamer error, for the log."""
    try:
        return message.src.get_path_string() if message.src is not None else "unknown"
    except Exception:
        return "unknown"


class NativePlayer:
    """Thin GStreamer playbin wrapper kept independent from the GTK widgets."""

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
        # Skipping silence retimes the sound earlier by what it removed; this
        # is how much, to keep positions on the track's own timeline.
        self._removed_us = 0
        self._silence_probes: tuple[int, int] = ()
        self._silence_input_pts = Gst.CLOCK_TIME_NONE
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
        equalizer: str | Sequence[float] = "flat",
        speed: float = 1.0,
        pitch: float = 0.0,
        skip_silence: bool = False,
        speed_pitch_linked: bool = False,
    ) -> None:
        """Apply processing atomically; safe when optional plugins are absent.

        ``equalizer`` is a preset key or the 10 band gains themselves
        (equalizer.equalizer_gains resolves imported AutoEQ profiles).
        """
        self._normalization = (normalization, normalization_level)
        self._apply_normalization()
        pitch_filter = self._audio_elements.get("pitch")
        if pitch_filter:
            for name, value in pitch_properties(speed, pitch, speed_pitch_linked).items():
                pitch_filter.set_property(name, value)
        equalizer_filter = self._audio_elements.get("equalizer")
        if equalizer_filter:
            bands = equalizer_gains(equalizer, {}) if isinstance(equalizer, str) else equalizer
            for index, gain in enumerate(bands):
                equalizer_filter.set_property(f"band{index}", float(gain))
        silence = self._audio_elements.get("silence")
        if silence:
            silence.set_property("remove", skip_silence)
            silence.set_property("squash", skip_silence)
            silence.set_property("minimum-silence-time", 1_500_000_000 if skip_silence else 0)
            self._measure_removed_silence(silence, skip_silence)

    def _measure_removed_silence(self, silence: Gst.Element, enabled: bool) -> None:
        """Compare each buffer's time before and after removesilence.

        Squashing moves every later buffer back by the silence removed, so the
        sink's position falls behind the track's: a track whose silences add
        up to more than two seconds seemed to end early, and was resumed there
        to play its last seconds again.
        """
        sink, src = silence.get_static_pad("sink"), silence.get_static_pad("src")
        if enabled == bool(self._silence_probes):
            return
        if not enabled:
            sink.remove_probe(self._silence_probes[0])
            src.remove_probe(self._silence_probes[1])
            self._silence_probes = ()
            self._removed_us = 0
            return

        def arriving(_pad, info):
            self._silence_input_pts = info.get_buffer().pts
            return Gst.PadProbeReturn.OK

        def leaving(_pad, info):
            pts, original = info.get_buffer().pts, self._silence_input_pts
            if Gst.CLOCK_TIME_NONE not in (pts, original):
                self._removed_us = max(0, (original - pts) // 1000)
            return Gst.PadProbeReturn.OK

        self._silence_probes = (
            sink.add_probe(Gst.PadProbeType.BUFFER, arriving),
            src.add_probe(Gst.PadProbeType.BUFFER, leaving),
        )

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
        self._removed_us = 0
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
        self._removed_us = 0
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
        segment_base: tuple[tuple[int, int], tuple[int, int]] | None = None,
    ) -> str:
        """The local URI GStreamer opens for ``uri``.

        Without ``segment_base`` an indexed MP4 video is probed over the
        network: call it from a worker thread then, not the main loop.
        """
        scheme = urllib.parse.urlsplit(uri).scheme
        if scheme == "file" or (scheme == "http" and "googlevideo.com" not in uri):
            return uri
        dash_uri = self._relay.dash_uri_for(uri, request_headers, segment_base)
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
        self._removed_us = 0

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
            self._last_position_us = int(value // 1000) + self._removed_us
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
        # Deferred at default priority, not idle: idle callbacks wait behind
        # every frame, and while Windows' software renderer kept drawing, the
        # end of a track went unhandled (ui.deliver_to_main does the same).
        if message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            source = error_source(message)
            LOGGER.error(
                "GStreamer playback error from %s: %s (%s)",
                source,
                error,
                debug or "sem debug",
            )
            if self.on_error:
                GLib.idle_add(self.on_error, str(error), priority=GLib.PRIORITY_DEFAULT)
        elif message.type == Gst.MessageType.EOS:
            position, duration = self.position_us, self.duration_us
            self.stop()
            if duration > 0 and position + 2_000_000 < duration:
                if self.on_error:
                    message_text = _(
                        "O fluxo de áudio terminou antes do esperado ({position}s de {duration}s)"
                    ).format(position=position // 1_000_000, duration=duration // 1_000_000)
                    GLib.idle_add(
                        self.on_error,
                        StreamEndedEarly(message_text, position, duration),
                        priority=GLib.PRIORITY_DEFAULT,
                    )
            elif self.on_eos:
                GLib.idle_add(self.on_eos, priority=GLib.PRIORITY_DEFAULT)
        elif message.type == Gst.MessageType.STATE_CHANGED and message.src == self._playbin:
            _old, new, _pending = message.parse_state_changed()
            if self.on_state:
                GLib.idle_add(
                    self.on_state, new == Gst.State.PLAYING, priority=GLib.PRIORITY_DEFAULT
                )
