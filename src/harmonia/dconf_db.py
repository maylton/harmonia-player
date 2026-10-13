"""Read and write the user's dconf database without the keys' GSettings schema.

Another program's settings (an extension's, say) have no schema Harmonia can
load, so GSettings cannot read them. dconf keeps them in a GVDB file
(~/.config/dconf/user), read here directly, and changes them through the
dconf service on the session bus, as dconf-editor does.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import Any

SIGNATURE = (0x72615647, 0x746E6169)  # "GVariant", little-endian
_ITEM = struct.Struct("<IIIHccII")  # hash, parent, key start, key size, type, -, value
_NO_PARENT = 0xFFFFFFFF


def user_database() -> Path:
    folder = os.environ.get("DCONF_USER_CONFIG_DIR")
    if folder:
        base = Path(folder) if Path(folder).is_absolute() else Path.home() / folder
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "dconf"
    return base / "user"


def read_values(data: bytes, prefix: str) -> dict[str, Any]:
    """The keys under ``prefix`` in a GVDB database, with their values unpacked."""
    from gi.repository import GLib

    if len(data) < 24 or struct.unpack_from("<II", data, 0) != SIGNATURE:
        return {}
    root_start, root_end = struct.unpack_from("<II", data, 16)
    bloom_header, buckets = struct.unpack_from("<II", data, root_start)
    items_start = root_start + 8 + 4 * (bloom_header & 0x7FFFFFF) + 4 * buckets
    count = (root_end - items_start) // _ITEM.size
    items = [_ITEM.unpack_from(data, items_start + index * _ITEM.size) for index in range(count)]

    def name(index: int) -> str:
        parts = []
        while index != _NO_PARENT and len(parts) <= count:
            _hash, parent, start, size, *_rest = items[index]
            parts.append(data[start : start + size].decode("utf-8", "replace"))
            index = parent
        return "".join(reversed(parts))

    values: dict[str, Any] = {}
    for index, (_hash, _parent, _start, _size, kind, _unused, start, end) in enumerate(items):
        if kind != b"v":
            continue
        key = name(index)
        if key.startswith(prefix):
            variant = GLib.Variant.new_from_bytes(
                GLib.VariantType("v"), GLib.Bytes.new(data[start:end]), False
            )
            values[key] = variant.unpack()
    return values


def read(prefix: str) -> dict[str, Any]:
    """The user's values under ``prefix`` ("/org/…/"), {} when there are none."""
    try:
        return read_values(user_database().read_bytes(), prefix)
    except (OSError, ValueError, struct.error):
        return {}


def write(values: dict[str, Any]) -> bool:
    """Change keys through the dconf service; ``values`` maps paths to GLib.Variants."""
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    # The changeset dconf expects: a{smv} (a None value resets the key), serialised.
    changes = GLib.Variant("a{smv}", dict(values))
    blob = GLib.Variant.new_from_bytes(GLib.VariantType("ay"), changes.get_data_as_bytes(), True)
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync(
            "ca.desrt.dconf",
            "/ca/desrt/dconf/Writer/user",
            "ca.desrt.dconf.Writer",
            "Change",
            GLib.Variant.new_tuple(blob),
            GLib.VariantType("(s)"),
            Gio.DBusCallFlags.NONE,
            3000,
            None,
        )
    except GLib.Error:
        return False
    return True
