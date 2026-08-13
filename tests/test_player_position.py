from harmonia.player import NativePlayer


class PlaybinStub:
    def __init__(self, query=(False, 0), seek_result=True):
        self.query = query
        self.seek_result = seek_result
        self.seek_target = None

    def query_position(self, _format):
        return self.query

    def seek_simple(self, _format, _flags, target):
        self.seek_target = target
        return self.seek_result


def player_stub(playbin, last_position=0):
    player = NativePlayer.__new__(NativePlayer)
    player._playbin = playbin
    player._last_position_us = last_position
    return player


def test_failed_position_query_preserves_last_valid_value():
    player = player_stub(PlaybinStub(), last_position=42_000_000)

    assert player.position_us == 42_000_000


def test_successful_seek_updates_stable_position_immediately():
    playbin = PlaybinStub(seek_result=True)
    player = player_stub(playbin, last_position=42_000_000)

    assert player.seek(8_500_000)
    assert player._last_position_us == 8_500_000
    assert playbin.seek_target == 8_500_000_000
