from harmonia.preferences import Preferences


class SettingsMemory:
    def __init__(self, values=None):
        self.values = values or {}

    def get_setting(self, key, default=""):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value


def test_preferences_roundtrip_and_bounds():
    storage = SettingsMemory({"speed": "9", "pitch": "-30", "quality": "invalid"})
    preferences = Preferences.load(storage)
    assert (preferences.speed, preferences.pitch, preferences.quality) == (2.0, -12, "high")
    preferences.language = "en-US"
    preferences.region = "US"
    preferences.quality = "medium"
    preferences.normalization = True
    preferences.background_blur = True
    preferences.icon_style = "material"
    preferences.lastfm_enabled = True
    preferences.lastfm_api_key = "lastfm-key"
    preferences.discord_enabled = True
    preferences.discord_client_id = "discord-id"
    preferences.recognition_provider = "custom"
    preferences.recognition_endpoint = "https://recognize.example/"
    preferences.save(storage)
    restored = Preferences.load(storage)
    assert (restored.language, restored.region, restored.max_bitrate) == ("en-US", "US", 160_000)
    assert restored.normalization is True
    assert restored.background_blur is True
    assert restored.icon_style == "material"
    assert restored.lastfm_enabled is True
    assert restored.lastfm_api_key == "lastfm-key"
    assert restored.discord_enabled is True
    assert restored.discord_client_id == "discord-id"
    assert restored.recognition_provider == "custom"
    assert restored.recognition_endpoint == "https://recognize.example/"


def test_removed_ios_icon_style_migrates_to_gtk():
    preferences = Preferences.load(SettingsMemory({"icon_style": "ios"}))

    assert preferences.icon_style == "gtk"


def test_audio_processing_graph_applies_all_controls():
    from harmonia.player import NativePlayer

    player = NativePlayer()
    player.apply_audio_settings(
        normalization=True, equalizer="bass", speed=1.25, pitch=12, skip_silence=True
    )
    assert player._audio_elements["pitch"].get_property("tempo") == 1.25
    assert round(player._audio_elements["pitch"].get_property("pitch"), 2) == 2.0
    assert player._audio_elements["equalizer"].get_property("band0") == 6.0
    assert player._audio_elements["replaygain"].get_property("fallback-gain") == -6.0
    assert player._audio_elements["silence"].get_property("remove") is True
    player.stop()
