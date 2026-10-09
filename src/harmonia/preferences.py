from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from .crossfade import clamp_seconds
from .loudness import DEFAULT_LEVEL, LEVELS
from .playlist_position import DEFAULT_POSITION, POSITIONS
from .theming import ACCENTS, DEFAULT_THEME, VARIANTS, builtin_themes


@dataclass(slots=True)
class Preferences:
    language: str = "pt-BR"
    region: str = "BR"
    quality: str = "high"
    proxy: str = ""
    normalization: bool = False
    normalization_level: str = DEFAULT_LEVEL
    equalizer: str = "flat"
    speed: float = 1.0
    pitch: float = 0.0
    # The speed changes the pitch too, like a record; see playback_speed.py.
    speed_pitch_linked: bool = False
    skip_silence: bool = False
    crossfade: int = 0  # seconds; 0 is off
    playlist_add_position: str = DEFAULT_POSITION  # "end" or "start"
    background_blur: bool = False
    icon_style: str = "gtk"
    theme: str = DEFAULT_THEME
    theme_variant: str = "theme"
    accent: str = "theme"
    # Window material for themes that support one (Windows 11 only).
    backdrop: str = "mica"
    # Blurred cover behind the expanded player while a material is on;
    # off, the expanded player shows the material too.
    expanded_cover: bool = False
    lastfm_enabled: bool = False
    lastfm_api_key: str = ""
    discord_enabled: bool = False
    discord_client_id: str = ""
    recognition_provider: str = "audd"
    recognition_endpoint: str = "https://api.audd.io/"

    BACKDROPS: ClassVar[tuple[str, ...]] = ("mica", "acrylic", "none")
    # "gtk" follows the desktop (on Windows, the bundled Fluent icons); the
    # others are icon themes bundled with Harmonia.
    ICON_STYLES: ClassVar[dict[str, str]] = {
        "gtk": "",
        "material": "HarmoniaMaterial",
        "fluent": "HarmoniaFluent",
    }
    QUALITY_BITRATES: ClassVar[dict[str, int]] = {
        "low": 70_000,
        "medium": 160_000,
        "high": 10_000_000,
    }

    @classmethod
    def load(cls, storage) -> Preferences:
        def boolean(key: str, default: bool) -> bool:
            return storage.get_setting(key, "1" if default else "0") == "1"

        def number(key: str, default: float) -> float:
            try:
                return float(storage.get_setting(key, str(default)))
            except ValueError:
                return default

        quality = storage.get_setting("quality", "high")
        equalizer = storage.get_setting("equalizer", "flat")
        icon_style = storage.get_setting("icon_style", "gtk")
        theme = storage.get_setting("theme", DEFAULT_THEME)
        theme_variant = storage.get_setting("theme_variant", "theme")
        accent = storage.get_setting("accent", "theme")
        backdrop = storage.get_setting("backdrop", "mica")
        normalization_level = storage.get_setting("normalization_level", DEFAULT_LEVEL)
        position = storage.get_setting("playlist_add_position", DEFAULT_POSITION)
        return cls(
            language=storage.get_setting("language", "pt-BR"),
            region=storage.get_setting("region", "BR"),
            quality=quality if quality in cls.QUALITY_BITRATES else "high",
            proxy=storage.get_setting("proxy", ""),
            normalization=boolean("normalization", False),
            normalization_level=(
                normalization_level if normalization_level in LEVELS else DEFAULT_LEVEL
            ),
            equalizer=equalizer,
            speed=max(0.5, min(2.0, number("speed", 1.0))),
            pitch=max(-12, min(12, number("pitch", 0.0))),
            speed_pitch_linked=boolean("speed_pitch_linked", False),
            skip_silence=boolean("skip_silence", False),
            crossfade=clamp_seconds(storage.get_setting("crossfade", "0")),
            playlist_add_position=position if position in POSITIONS else DEFAULT_POSITION,
            background_blur=boolean("background_blur", False),
            icon_style=icon_style if icon_style in cls.ICON_STYLES else "gtk",
            theme=theme if theme in builtin_themes() else DEFAULT_THEME,
            theme_variant=theme_variant if theme_variant in VARIANTS else "theme",
            accent=accent if accent in ACCENTS else "theme",
            backdrop=backdrop if backdrop in cls.BACKDROPS else "mica",
            expanded_cover=boolean("expanded_cover", False),
            lastfm_enabled=boolean("lastfm_enabled", False),
            lastfm_api_key=storage.get_setting("lastfm_api_key", ""),
            discord_enabled=boolean("discord_enabled", False),
            discord_client_id=storage.get_setting("discord_client_id", ""),
            recognition_provider=(
                storage.get_setting("recognition_provider", "audd")
                if storage.get_setting("recognition_provider", "audd") in {"audd", "custom"}
                else "audd"
            ),
            recognition_endpoint=storage.get_setting(
                "recognition_endpoint", "https://api.audd.io/"
            ),
        )

    def save(self, storage) -> None:
        values = {
            "language": self.language,
            "region": self.region,
            "quality": self.quality,
            "proxy": self.proxy,
            "normalization": "1" if self.normalization else "0",
            "normalization_level": self.normalization_level,
            "equalizer": self.equalizer,
            "speed": str(self.speed),
            "pitch": str(self.pitch),
            "speed_pitch_linked": "1" if self.speed_pitch_linked else "0",
            "skip_silence": "1" if self.skip_silence else "0",
            "crossfade": str(self.crossfade),
            "playlist_add_position": self.playlist_add_position,
            "background_blur": "1" if self.background_blur else "0",
            "icon_style": self.icon_style,
            "theme": self.theme,
            "theme_variant": self.theme_variant,
            "accent": self.accent,
            "backdrop": self.backdrop,
            "expanded_cover": "1" if self.expanded_cover else "0",
            "lastfm_enabled": "1" if self.lastfm_enabled else "0",
            "lastfm_api_key": self.lastfm_api_key,
            "discord_enabled": "1" if self.discord_enabled else "0",
            "discord_client_id": self.discord_client_id,
            "recognition_provider": self.recognition_provider,
            "recognition_endpoint": self.recognition_endpoint,
        }
        for key, value in values.items():
            storage.set_setting(key, value)

    @property
    def max_bitrate(self) -> int:
        return self.QUALITY_BITRATES[self.quality]
