"""Blur behind the window on GNOME, which only Blur my Shell can do.

Mutter lets no application ask for a blur. The Blur my Shell extension blurs
behind the windows of the applications in its list (or of all of them), so
on GNOME the window is translucent and the extension does the blur. Harmonia
reads the extension's settings to know whether it is covered, and can add
itself to the list when the user asks.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import dconf_db

UUID = "blur-my-shell@aunetx"
APPLICATIONS = "/org/gnome/shell/extensions/blur-my-shell/applications/"
EXTENSIONS_BUS = "org.gnome.Shell.Extensions"
# Blur my Shell's defaults, for keys the user never changed.
DEFAULT_BLACKLIST = ["Plank", "com.desktop.ding", "Conky"]


@dataclass(frozen=True, slots=True)
class BlurMyShell:
    enabled: bool  # the extension is installed and on
    blurs_app: bool  # its application blur covers this application


def extension_enabled() -> bool:
    """Whether GNOME Shell has Blur my Shell installed and enabled."""
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = bus.call_sync(
            EXTENSIONS_BUS,
            "/org/gnome/Shell/Extensions",
            EXTENSIONS_BUS,
            "GetExtensionInfo",
            GLib.Variant("(s)", (UUID,)),
            GLib.VariantType("(a{sv})"),
            Gio.DBusCallFlags.NONE,
            1000,
            None,
        )
    except GLib.Error:
        return False
    info = reply.unpack()[0]
    # "state" 1 is enabled (ACTIVE since GNOME 45); newer Shells also say "enabled".
    return bool(info) and (info.get("enabled") is True or info.get("state") == 1)


def covers(values: dict, app_id: str) -> bool:
    """Whether Blur my Shell's application settings blur ``app_id``."""

    def value(key, default):
        return values.get(APPLICATIONS + key, default)

    if not value("blur", False):
        return False
    if value("enable-all", False):
        return app_id not in value("blacklist", DEFAULT_BLACKLIST)
    return app_id in value("whitelist", [])


def state(app_id: str) -> BlurMyShell:
    if not extension_enabled():
        return BlurMyShell(False, False)
    return BlurMyShell(True, covers(dconf_db.read(APPLICATIONS), app_id))


def include(app_id: str) -> bool:
    """Turn the extension's application blur on and add ``app_id`` to its list."""
    from gi.repository import GLib

    values = dconf_db.read(APPLICATIONS)
    changes = {APPLICATIONS + "blur": GLib.Variant("b", True)}
    if values.get(APPLICATIONS + "enable-all", False):
        blacklist = values.get(APPLICATIONS + "blacklist", DEFAULT_BLACKLIST)
        changes[APPLICATIONS + "blacklist"] = GLib.Variant(
            "as", [name for name in blacklist if name != app_id]
        )
    else:
        whitelist = values.get(APPLICATIONS + "whitelist", [])
        if app_id not in whitelist:
            changes[APPLICATIONS + "whitelist"] = GLib.Variant("as", [*whitelist, app_id])
    return dconf_db.write(changes)
