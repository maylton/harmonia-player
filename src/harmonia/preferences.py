from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(slots=True)
class Preferences:
    language: str = "pt-BR"
    region: str = "BR"
    quality: str = "high"
    proxy: str = ""
    normalization: bool = False
    equalizer: str = "flat"
    speed: float = 1.0
    pitch: float = 0.0
    skip_silence: bool = False
    background_blur: bool = False
    icon_style: str = "gtk"
    lastfm_enabled: bool = False
    lastfm_api_key: str = ""
    discord_enabled: bool = False
    discord_client_id: str = ""
    recognition_provider: str = "audd"
    recognition_endpoint: str = "https://api.audd.io/"

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
        return cls(
            language=storage.get_setting("language", "pt-BR"),
            region=storage.get_setting("region", "BR"),
            quality=quality if quality in cls.QUALITY_BITRATES else "high",
            proxy=storage.get_setting("proxy", ""),
            normalization=boolean("normalization", False),
            equalizer=equalizer,
            speed=max(0.5, min(2.0, number("speed", 1.0))),
            pitch=max(-12, min(12, number("pitch", 0.0))),
            skip_silence=boolean("skip_silence", False),
            background_blur=boolean("background_blur", False),
            icon_style=icon_style if icon_style in {"gtk", "material"} else "gtk",
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
            "equalizer": self.equalizer,
            "speed": str(self.speed),
            "pitch": str(self.pitch),
            "skip_silence": "1" if self.skip_silence else "0",
            "background_blur": "1" if self.background_blur else "0",
            "icon_style": self.icon_style,
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
