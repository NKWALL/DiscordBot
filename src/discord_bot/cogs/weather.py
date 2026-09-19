from __future__ import annotations

from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

from discord_bot.utils import EMBED_COLOR

WEATHER_TRANSLATIONS = {
    "clear sky": "晴朗",
    "few clouds": "少雲",
    "scattered clouds": "零散雲",
    "broken clouds": "多雲",
    "overcast clouds": "陰天",
    "light rain": "小雨",
    "moderate rain": "中雨",
    "heavy intensity rain": "大雨",
    "very heavy rain": "豪雨",
    "thunderstorm": "雷雨",
    "mist": "薄霧",
    "haze": "霾",
    "fog": "霧",
}


class WeatherCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._last_push_date = None

    async def cog_load(self) -> None:
        self.weather_scheduler.start()

    async def cog_unload(self) -> None:
        self.weather_scheduler.cancel()

    async def _current_weather(self, city: str) -> dict:
        key = self.bot.settings.openweather_api_key
        if not key:
            raise RuntimeError("尚未設定 OPENWEATHER_API_KEY")
        assert self.bot.web_session is not None
        params = {"q": city, "appid": key, "units": "metric", "lang": "zh_tw"}
        async with self.bot.web_session.get(
            "https://api.openweathermap.org/data/2.5/weather", params=params
        ) as response:
            data = await response.json()
            if response.status != 200:
                raise RuntimeError(data.get("message", f"HTTP {response.status}"))
            return data

    @staticmethod
    def _weather_message(data: dict) -> str:
        description = data["weather"][0].get("description", "未知")
        description = WEATHER_TRANSLATIONS.get(description, description)
        temperature = float(data["main"]["temp"])
        humidity = data["main"]["humidity"]
        rain = data.get("rain", {}).get("1h", 0)
        if temperature < 18:
            clothing = "建議攜帶外套"
        elif temperature < 25:
            clothing = "建議穿著長袖或薄外套"
        else:
            clothing = "天氣較暖，可穿著短袖"
        return (
            f"**{data.get('name', '查詢地點')}**\n"
            f"天氣：{description}\n"
            f"溫度：{temperature:.1f}°C\n"
            f"濕度：{humidity}%\n"
            f"近一小時降雨量：{rain} mm\n"
            f"提醒：{clothing}"
        )

    @app_commands.command(name="weather", description="查詢目前天氣")
    @app_commands.describe(city="城市或地區名稱，例如 Kaohsiung")
    async def weather(self, interaction: discord.Interaction, city: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            data = await self._current_weather(city)
        except RuntimeError as exc:
            await interaction.followup.send(f"天氣查詢失敗：{exc}", ephemeral=True)
            return
        embed = discord.Embed(
            title="目前天氣",
            description=self._weather_message(data),
            color=EMBED_COLOR,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="forecast", description="查詢未來三天天氣預報")
    @app_commands.describe(city="城市或地區名稱，例如 Kaohsiung")
    async def forecast(self, interaction: discord.Interaction, city: str) -> None:
        await interaction.response.defer(ephemeral=True)
        key = self.bot.settings.openweather_api_key
        if not key:
            await interaction.followup.send(
                "尚未設定 OPENWEATHER_API_KEY。", ephemeral=True
            )
            return
        assert self.bot.web_session is not None
        params = {"q": city, "appid": key, "units": "metric", "lang": "zh_tw"}
        async with self.bot.web_session.get(
            "https://api.openweathermap.org/data/2.5/forecast", params=params
        ) as response:
            data = await response.json()
        if response.status != 200:
            await interaction.followup.send(
                f"預報查詢失敗：{data.get('message', response.status)}", ephemeral=True
            )
            return

        by_date: dict[str, list[dict]] = {}
        for item in data.get("list", []):
            date = item["dt_txt"].split()[0]
            by_date.setdefault(date, []).append(item)
        embed = discord.Embed(
            title=f"{data.get('city', {}).get('name', city)}三日天氣預報",
            color=EMBED_COLOR,
        )
        for date, items in list(by_date.items())[:3]:
            representative = min(
                items,
                key=lambda item: abs(int(item["dt_txt"].split()[1].split(":")[0]) - 12),
            )
            temperatures = [float(item["main"]["temp"]) for item in items]
            description = representative["weather"][0].get("description", "未知")
            embed.add_field(
                name=date,
                value=(
                    f"{description}\n"
                    f"{min(temperatures):.1f}°C～{max(temperatures):.1f}°C\n"
                    f"濕度 {representative['main']['humidity']}%"
                ),
                inline=True,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="set_weather_channel", description="設定每日天氣推播頻道")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_weather_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        await self.bot.store.set_channel("weather_push_channel_id", channel.id)
        await interaction.response.send_message(
            f"已將每日天氣推播頻道設為 {channel.mention}。", ephemeral=True
        )

    @tasks.loop(minutes=1)
    async def weather_scheduler(self) -> None:
        now = datetime.now(self.bot.settings.timezone)
        if now.hour != self.bot.settings.weather_push_hour or now.minute != 0:
            return
        if self._last_push_date == now.date():
            return
        channel_id = (
            self.bot.store.data.get("weather_push_channel_id")
            or self.bot.settings.weather_push_channel_id
        )
        if not channel_id:
            return
        channel = self.bot.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            data = await self._current_weather(self.bot.settings.weather_push_city)
            await channel.send(self._weather_message(data))
            self._last_push_date = now.date()
        except RuntimeError:
            return

    @weather_scheduler.before_loop
    async def before_weather_scheduler(self) -> None:
        await self.bot.wait_until_ready()
