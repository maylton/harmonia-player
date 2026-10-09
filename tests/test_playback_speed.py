from harmonia.playback_speed import pitch_properties
from harmonia.preferences import Preferences


def test_separate_speed_keeps_the_pitch_in_semitones():
    assert pitch_properties(1.5, 12, False) == {"tempo": 1.5, "pitch": 2.0, "rate": 1.0}
    assert pitch_properties(9, -30, False) == {"tempo": 2.0, "pitch": 0.5, "rate": 1.0}


def test_linked_speed_moves_the_pitch_like_a_record():
    # The pitch setting no longer applies: the rate resamples both.
    assert pitch_properties(1.25, 7, True) == {"tempo": 1.0, "pitch": 1.0, "rate": 1.25}
    assert pitch_properties(0.1, 0, True)["rate"] == 0.5


def test_the_link_is_a_saved_preference():
    values = {}

    class Memory:
        def get_setting(self, key, default=""):
            return values.get(key, default)

        def set_setting(self, key, value):
            values[key] = value

    preferences = Preferences.load(Memory())
    assert preferences.speed_pitch_linked is False
    preferences.speed_pitch_linked = True
    preferences.save(Memory())
    assert Preferences.load(Memory()).speed_pitch_linked is True
