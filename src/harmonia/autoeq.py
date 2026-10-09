"""AutoEQ headphone profiles turned into the 10 bands of GStreamer's equalizer.

AutoEQ (github.com/jaakkopasanen/AutoEq) publishes, per headphone model,
text files Equalizer APO reads:

- ParametricEQ.txt and FixedBandEQ.txt: ``Preamp: -6.4 dB`` and lines such
  as ``Filter 1: ON PK Fc 105 Hz Gain -2.1 dB Q 0.70`` (peaking, low and high
  shelves);
- GraphicEQ.txt: ``GraphicEQ: 20 -6.4; 21 -6.4; ...`` (Hz and dB pairs).

The profile's response is evaluated (the filters with the RBJ cookbook
biquads at 48 kHz, the graphic curve interpolated on a log scale), averaged
over each band of equalizer-10bands, and lowered by the preamp so boosts do
not clip.
"""

from __future__ import annotations

import cmath
import math
import re
from dataclasses import dataclass
from itertools import pairwise

BANDS_HZ = (30.0, 59.8, 119.2, 237.9, 474.7, 947.2, 1889.9, 3770.8, 7523.8, 15011.9)
MIN_GAIN, MAX_GAIN = -24.0, 12.0
SAMPLE_RATE = 48_000
SAMPLES_PER_BAND = 9
FILE_SUFFIXES = (" ParametricEQ", " FixedBandEQ", " GraphicEQ")

_PREAMP = re.compile(r"^\s*Preamp:\s*(-?[\d.]+)\s*dB", re.IGNORECASE | re.MULTILINE)
_FILTER = re.compile(
    r"^\s*Filter\s*\d*:\s*ON\s+(?P<type>[A-Z]+)(?:\s+\d+\s*dB)?\s+Fc\s+(?P<fc>[\d.]+)\s*Hz"
    r"(?:\s+Gain\s+(?P<gain>-?[\d.]+)\s*dB)?(?:\s+Q\s+(?P<q>[\d.]+))?",
    re.IGNORECASE | re.MULTILINE,
)
_GRAPHIC = re.compile(r"^\s*GraphicEQ:(.*)$", re.IGNORECASE | re.MULTILINE)
_KINDS = {"PK": "peak", "PEQ": "peak", "LSC": "low", "LS": "low", "HSC": "high", "HS": "high"}


@dataclass(frozen=True, slots=True)
class Filter:
    kind: str  # "peak", "low" (shelf) or "high" (shelf)
    frequency: float
    gain: float
    q: float = 0.707


def profile_name(filename: str) -> str:
    """ "Sennheiser HD 600 ParametricEQ.txt" -> "Sennheiser HD 600"."""
    stem = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    stem = stem[:-4] if stem.lower().endswith(".txt") else stem
    for suffix in FILE_SUFFIXES:
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    return stem.strip() or "AutoEQ"


def parse_parametric(text: str) -> tuple[float, list[Filter]]:
    preamp = _PREAMP.search(text)
    filters = [
        Filter(
            _KINDS[match["type"].upper()],
            float(match["fc"]),
            float(match["gain"] or 0),
            float(match["q"] or 0.707),
        )
        for match in _FILTER.finditer(text)
        if match["type"].upper() in _KINDS
    ]
    return (float(preamp[1]) if preamp else 0.0), filters


def parse_graphic(text: str) -> list[tuple[float, float]]:
    match = _GRAPHIC.search(text)
    if not match:
        return []
    points = []
    for pair in match[1].split(";"):
        values = pair.split()
        if len(values) == 2:
            try:
                points.append((float(values[0]), float(values[1])))
            except ValueError:
                continue
    return sorted(point for point in points if point[0] > 0)


def filter_response_db(filters: list[Filter], frequency: float) -> float:
    total = 0.0
    for item in filters:
        b, a = _biquad(item)
        z = cmath.exp(-1j * 2 * math.pi * frequency / SAMPLE_RATE)
        response = (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)
        total += 20 * math.log10(max(abs(response), 1e-9))
    return total


def _biquad(item: Filter) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """RBJ Audio EQ Cookbook coefficients."""
    amplitude = 10 ** (item.gain / 40)
    w0 = 2 * math.pi * min(item.frequency, SAMPLE_RATE / 2 - 1) / SAMPLE_RATE
    cos, alpha = math.cos(w0), math.sin(w0) / (2 * max(item.q, 0.01))
    if item.kind == "peak":
        return (
            (1 + alpha * amplitude, -2 * cos, 1 - alpha * amplitude),
            (1 + alpha / amplitude, -2 * cos, 1 - alpha / amplitude),
        )
    root = 2 * math.sqrt(amplitude) * alpha
    a, plus, minus = amplitude, amplitude + 1, amplitude - 1
    if item.kind == "low":
        return (
            (
                a * (plus - minus * cos + root),
                2 * a * (minus - plus * cos),
                a * (plus - minus * cos - root),
            ),
            (plus + minus * cos + root, -2 * (minus + plus * cos), plus + minus * cos - root),
        )
    return (
        (
            a * (plus + minus * cos + root),
            -2 * a * (minus + plus * cos),
            a * (plus + minus * cos - root),
        ),
        (plus - minus * cos + root, 2 * (minus - plus * cos), plus - minus * cos - root),
    )


def graphic_response_db(points: list[tuple[float, float]], frequency: float) -> float:
    if frequency <= points[0][0]:
        return points[0][1]
    if frequency >= points[-1][0]:
        return points[-1][1]
    for (low_f, low_db), (high_f, high_db) in pairwise(points):
        if low_f <= frequency <= high_f:
            span = math.log(high_f / low_f) or 1.0
            return low_db + (high_db - low_db) * math.log(frequency / low_f) / span
    return 0.0


def band_gains(response, preamp: float = 0.0) -> tuple[float, ...]:
    """Each band's gain: the response averaged over the band, plus the preamp."""
    gains = []
    for center in BANDS_HZ:
        samples = [
            center * 2 ** (offset / (SAMPLES_PER_BAND - 1) - 0.5)
            for offset in range(SAMPLES_PER_BAND)
        ]
        average = sum(response(frequency) for frequency in samples) / len(samples)
        gains.append(round(max(MIN_GAIN, min(MAX_GAIN, average + preamp)), 1))
    return tuple(gains)


def parse_profile(text: str) -> tuple[float, ...]:
    """The 10 band gains of an AutoEQ file; ValueError if it is not one."""
    points = parse_graphic(text)
    if points:
        return band_gains(lambda frequency: graphic_response_db(points, frequency))
    preamp, filters = parse_parametric(text)
    if filters:
        return band_gains(lambda frequency: filter_response_db(filters, frequency), preamp)
    raise ValueError("not an AutoEQ ParametricEQ, FixedBandEQ or GraphicEQ file")
