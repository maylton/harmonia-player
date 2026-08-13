from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

XML = """<node>
<interface name="org.mpris.MediaPlayer2">
  <method name="Raise"/><method name="Quit"/>
  <property name="CanQuit" type="b" access="read"/><property name="CanRaise" type="b" access="read"/>
  <property name="HasTrackList" type="b" access="read"/><property name="Identity" type="s" access="read"/>
  <property name="DesktopEntry" type="s" access="read"/><property name="SupportedUriSchemes" type="as" access="read"/>
  <property name="SupportedMimeTypes" type="as" access="read"/>
</interface>
<interface name="org.mpris.MediaPlayer2.Player">
  <method name="Next"/><method name="Previous"/><method name="Pause"/><method name="PlayPause"/>
  <method name="Stop"/><method name="Play"/><method name="Seek"><arg direction="in" type="x" name="Offset"/></method>
  <method name="SetPosition"><arg direction="in" type="o" name="TrackId"/><arg direction="in" type="x" name="Position"/></method>
  <method name="OpenUri"><arg direction="in" type="s" name="Uri"/></method>
  <signal name="Seeked"><arg type="x" name="Position"/></signal>
  <property name="PlaybackStatus" type="s" access="read"/><property name="LoopStatus" type="s" access="readwrite"/>
  <property name="Rate" type="d" access="readwrite"/><property name="Shuffle" type="b" access="readwrite"/>
  <property name="Metadata" type="a{sv}" access="read"/><property name="Volume" type="d" access="readwrite"/>
  <property name="Position" type="x" access="read"/><property name="MinimumRate" type="d" access="read"/>
  <property name="MaximumRate" type="d" access="read"/><property name="CanGoNext" type="b" access="read"/>
  <property name="CanGoPrevious" type="b" access="read"/><property name="CanPlay" type="b" access="read"/>
  <property name="CanPause" type="b" access="read"/><property name="CanSeek" type="b" access="read"/>
  <property name="CanControl" type="b" access="read"/>
</interface></node>"""


class MprisService:
    def __init__(
        self,
        app,
        player,
        callbacks: dict[str, Callable[..., object]],
        state: dict[str, Callable[[], object]] | None = None,
    ):
        self.app, self.player, self.callbacks = app, player, callbacks
        self.state = state or {}
        self.item = None
        self.duration_us = 0
        self.connection = None
        self.registrations = []
        self.node = Gio.DBusNodeInfo.new_for_xml(XML)
        self.owner = Gio.bus_own_name(
            Gio.BusType.SESSION,
            "org.mpris.MediaPlayer2.Harmonia",
            Gio.BusNameOwnerFlags.NONE,
            self._bus_acquired,
            None,
            None,
        )

    def _bus_acquired(self, connection, _name):
        self.connection = connection
        for interface in self.node.interfaces:
            reg = connection.register_object(
                "/org/mpris/MediaPlayer2",
                interface,
                self._method,
                self._get_property,
                self._set_property,
            )
            self.registrations.append(reg)

    def _method(self, _conn, _sender, _path, _iface, method, params, invocation):
        actions = {
            "Next": "next",
            "Previous": "previous",
            "Pause": "pause",
            "PlayPause": "toggle",
            "Stop": "stop",
            "Play": "play",
        }
        if method == "Raise":
            window = self.app.get_active_window()
            if window:
                window.present()
        elif method == "Quit":
            self.app.quit()
        elif method in actions and actions[method] in self.callbacks:
            self.callbacks[actions[method]]()
        elif method == "Seek":
            self.player.seek(self.player.position_us + params.unpack()[0])
        elif method == "SetPosition":
            self.player.seek(params.unpack()[1])
        invocation.return_value(None)

    def _get_property(self, _conn, _sender, _path, interface, prop):
        if interface == "org.mpris.MediaPlayer2":
            values = {
                "CanQuit": True,
                "CanRaise": True,
                "HasTrackList": False,
                "Identity": "Harmonia",
                "DesktopEntry": "io.github.harmonia.Harmonia",
                "SupportedUriSchemes": [],
                "SupportedMimeTypes": [],
            }
        else:
            values = {
                "PlaybackStatus": "Playing" if self.player.playing else "Paused",
                "LoopStatus": "Track" if self._state("repeat", False) else "None",
                "Rate": 1.0,
                "Shuffle": bool(self._state("shuffle", False)),
                "Metadata": self._metadata(),
                "Volume": self.player.volume,
                "Position": self.player.position_us,
                "MinimumRate": 1.0,
                "MaximumRate": 1.0,
                "CanGoNext": True,
                "CanGoPrevious": True,
                "CanPlay": True,
                "CanPause": True,
                "CanSeek": True,
                "CanControl": True,
            }
        return self._variant(values[prop])

    def _set_property(self, _conn, _sender, _path, interface, prop, value):
        if interface != "org.mpris.MediaPlayer2.Player":
            return False
        unpacked = value.unpack()
        if prop == "Volume":
            self.player.volume = float(unpacked)
        elif prop == "Shuffle" and "shuffle" in self.callbacks:
            self.callbacks["shuffle"](bool(unpacked))
        elif prop == "LoopStatus" and "repeat" in self.callbacks:
            self.callbacks["repeat"](unpacked == "Track")
        elif prop == "Rate" and float(unpacked) == 1.0:
            pass
        else:
            return False
        self.update()
        return True

    def _state(self, name: str, default):
        getter = self.state.get(name)
        return getter() if getter else default

    def _variant(self, value):
        if isinstance(value, bool):
            return GLib.Variant("b", value)
        if isinstance(value, float):
            return GLib.Variant("d", value)
        if isinstance(value, int):
            return GLib.Variant("x", value)
        if isinstance(value, list):
            return GLib.Variant("as", value)
        if isinstance(value, dict):
            return GLib.Variant("a{sv}", value)
        return GLib.Variant("s", value)

    def _metadata(self):
        if not self.item:
            return {}
        track_id = "/io/github/harmonia/track/" + "".join(
            c if c.isalnum() else "_" for c in self.item.id
        )
        data = {
            "mpris:trackid": GLib.Variant("o", track_id),
            "xesam:title": GLib.Variant("s", self.item.title),
            "xesam:artist": GLib.Variant("as", [self.item.subtitle or "YouTube Music"]),
        }
        if self.duration_us:
            data["mpris:length"] = GLib.Variant("x", self.duration_us)
        if self.item.thumbnail:
            data["mpris:artUrl"] = GLib.Variant("s", self.item.thumbnail)
        return data

    def update(self, item=None, duration_us=None):
        if item is not None:
            self.item = item
        if duration_us is not None:
            self.duration_us = duration_us
        if self.connection:
            changed = {
                "PlaybackStatus": GLib.Variant("s", "Playing" if self.player.playing else "Paused"),
                "Metadata": GLib.Variant("a{sv}", self._metadata()),
            }
            self.connection.emit_signal(
                None,
                "/org/mpris/MediaPlayer2",
                "org.freedesktop.DBus.Properties",
                "PropertiesChanged",
                GLib.Variant("(sa{sv}as)", ("org.mpris.MediaPlayer2.Player", changed, [])),
            )

    def clear(self) -> None:
        self.item = None
        self.duration_us = 0
        self.update()
