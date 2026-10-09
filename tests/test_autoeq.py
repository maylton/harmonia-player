import math

import pytest

from harmonia.autoeq import (
    BANDS_HZ,
    Filter,
    filter_response_db,
    parse_parametric,
    parse_profile,
    profile_name,
)
from harmonia.equalizer import PRESETS, equalizer_gains, profile_key, profile_of

# The start of AutoEQ's Sennheiser HD 600 ParametricEQ.txt.
HD600 = """Preamp: -6.4 dB
Filter 1: ON LSC Fc 105 Hz Gain 6.0 dB Q 0.70
Filter 2: ON PK Fc 214 Hz Gain -1.3 dB Q 0.58
Filter 3: ON PK Fc 2016 Hz Gain 2.9 dB Q 2.46
Filter 4: ON PK Fc 3220 Hz Gain -2.4 dB Q 3.19
Filter 5: ON HSC Fc 10000 Hz Gain -1.1 dB Q 0.70
Filter 6: OFF PK Fc 4000 Hz Gain 9.0 dB Q 1.00
"""


def test_parametric_files_are_read_with_preamp_and_filter_types():
    preamp, filters = parse_parametric(HD600)
    assert preamp == -6.4
    assert [item.kind for item in filters] == ["low", "peak", "peak", "peak", "high"]
    assert filters[0] == Filter("low", 105.0, 6.0, 0.70)  # the OFF filter is left out


def test_filters_follow_the_cookbook_responses():
    peak = [Filter("peak", 1000, 6.0, 1.0)]
    assert math.isclose(filter_response_db(peak, 1000), 6.0, abs_tol=0.01)
    assert abs(filter_response_db(peak, 50)) < 0.1
    shelf = [Filter("low", 105, 6.0, 0.7)]
    assert math.isclose(filter_response_db(shelf, 20), 6.0, abs_tol=0.2)
    assert abs(filter_response_db(shelf, 5000)) < 0.1


def test_profiles_become_the_ten_bands_lowered_by_the_preamp():
    gains = parse_profile(HD600)
    assert len(gains) == len(BANDS_HZ) == 10
    # The bass shelf lifts the lowest band; the preamp keeps everything below 0 dB.
    assert gains[0] > gains[5] and max(gains) <= 0.0
    graphic = parse_profile("GraphicEQ: 20 -3.0; 1000 -3.0; 20000 -3.0")
    assert graphic == (-3.0,) * 10
    boosted = parse_profile("Filter 1: ON PK Fc 1000 Hz Gain 40 dB Q 0.3")
    assert max(boosted) == 12.0  # the equalizer's range
    with pytest.raises(ValueError):
        parse_profile("not a profile")


def test_profile_names_drop_the_file_kind():
    assert profile_name("Sennheiser HD 600 ParametricEQ.txt") == "Sennheiser HD 600"
    assert profile_name("C:\\perfis\\AKG K371 GraphicEQ.txt") == "AKG K371"
    assert profile_name("meu fone.txt") == "meu fone"


def test_the_preference_resolves_presets_and_profiles():
    profiles = {"HD 600": (1.0,) * 10}
    assert equalizer_gains("bass", profiles) == PRESETS["bass"]
    assert equalizer_gains(profile_key("HD 600"), profiles) == (1.0,) * 10
    assert equalizer_gains(profile_key("removed"), profiles) == PRESETS["flat"]
    assert profile_of(profile_key("HD 600")) == "HD 600" and profile_of("flat") is None


def test_profiles_are_stored_by_name(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    from harmonia.storage import Storage

    storage = Storage()
    storage.save_eq_profile("HD 600", (1.5,) * 10)
    storage.save_eq_profile("HD 600", (2.0,) * 10)  # importing again replaces it
    assert storage.eq_profiles() == {"HD 600": (2.0,) * 10}
    storage.delete_eq_profile("HD 600")
    assert storage.eq_profiles() == {}
