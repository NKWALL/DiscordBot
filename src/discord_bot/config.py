from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


def _optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} 必須是整數") from exc


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    discord_test_guild_id: int | None
    openweather_api_key: str | None
    google_maps_api_key: str | None
    gemini_api_key: str | None
    tdx_client_id: str | None
    tdx_client_secret: str | None
    twitter_bearer_token: str | None
    balldontlie_api_key: str | None
    weather_push_channel_id: int | None
    weather_push_city: str
    weather_push_hour: int
    timezone: ZoneInfo
    data_dir: Path
    resource_links_file: Path

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise ValueError("缺少 DISCORD_TOKEN，請先建立 .env 並填入 Bot Token")

        try:
            push_hour = int(os.getenv("WEATHER_PUSH_HOUR", "8"))
        except ValueError as exc:
            raise ValueError("WEATHER_PUSH_HOUR 必須是 0 到 23 的整數") from exc
        if not 0 <= push_hour <= 23:
            raise ValueError("WEATHER_PUSH_HOUR 必須介於 0 到 23")

        timezone_name = os.getenv("BOT_TIMEZONE", "Asia/Taipei").strip()
        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"無法辨認時區：{timezone_name}") from exc

        data_dir = Path(os.getenv("BOT_DATA_DIR", "data")).expanduser()
        links_file = Path(
            os.getenv("RESOURCE_LINKS_FILE", str(data_dir / "resources.json"))
        ).expanduser()

        def optional(name: str) -> str | None:
            return os.getenv(name, "").strip() or None

        return cls(
            discord_token=token,
            discord_test_guild_id=_optional_int("DISCORD_TEST_GUILD_ID"),
            openweather_api_key=optional("OPENWEATHER_API_KEY"),
            google_maps_api_key=optional("GOOGLE_MAPS_API_KEY"),
            gemini_api_key=optional("GEMINI_API_KEY"),
            tdx_client_id=optional("TDX_CLIENT_ID"),
            tdx_client_secret=optional("TDX_CLIENT_SECRET"),
            twitter_bearer_token=optional("TWITTER_BEARER_TOKEN"),
            balldontlie_api_key=optional("BALLDONTLIE_API_KEY"),
            weather_push_channel_id=_optional_int("WEATHER_PUSH_CHANNEL_ID"),
            weather_push_city=os.getenv("WEATHER_PUSH_CITY", "Kaohsiung").strip(),
            weather_push_hour=push_hour,
            timezone=timezone,
            data_dir=data_dir,
            resource_links_file=links_file,
        )
