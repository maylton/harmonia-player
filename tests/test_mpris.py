from gi.repository import GLib

from harmonia.mpris import MprisService


class PlayerStub:
    playing = False
    position_us = 0
    volume = 0.35


def service_stub():
    service = MprisService.__new__(MprisService)
    service.player = PlayerStub()
    service.callbacks = {}
    service.state = {}
    service.item = None
    service.duration_us = 0
    service.connection = None
    return service


def test_mpris_reports_live_volume_shuffle_and_repeat_state():
    service = service_stub()
    service.state = {"shuffle": lambda: True, "repeat": lambda: True}

    get = service._get_property
    args = (None, None, None, "org.mpris.MediaPlayer2.Player")
    assert get(*args, "Volume").unpack() == 0.35
    assert get(*args, "Shuffle").unpack() is True
    assert get(*args, "LoopStatus").unpack() == "Track"


def test_mpris_writable_properties_update_the_player_and_application():
    service = service_stub()
    changes = {}
    service.callbacks = {
        "shuffle": lambda value: changes.__setitem__("shuffle", value),
        "repeat": lambda value: changes.__setitem__("repeat", value),
    }

    args = (None, None, None, "org.mpris.MediaPlayer2.Player")
    assert service._set_property(*args, "Volume", GLib.Variant("d", 0.7))
    assert service._set_property(*args, "Shuffle", GLib.Variant("b", True))
    assert service._set_property(*args, "LoopStatus", GLib.Variant("s", "Track"))
    assert service.player.volume == 0.7
    assert changes == {"shuffle": True, "repeat": True}


def test_mpris_can_clear_stale_track_duration():
    service = service_stub()
    service.duration_us = 42_000_000

    service.update(duration_us=0)

    assert service.duration_us == 0


def test_mpris_clear_removes_stale_track_metadata():
    service = service_stub()
    service.item = object()
    service.duration_us = 42_000_000

    service.clear()

    assert service.item is None
    assert service.duration_us == 0
