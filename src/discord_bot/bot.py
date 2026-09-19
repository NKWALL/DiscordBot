from __future__ import annotations

import logging
import os

import aiohttp
import certifi
import discord
from discord import app_commands
from discord.ext import commands

from discord_bot.config import Settings
from discord_bot.storage import JsonStore

LOGGER = logging.getLogger(__name__)


class LifeAssistantBot(commands.Bot):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.presences = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.settings = settings
        self.store = JsonStore(settings.data_dir / "bot_data.json")
        self.web_session: aiohttp.ClientSession | None = None

    async def setup_hook(self) -> None:
        from discord_bot.cogs.ai import AiCog
        from discord_bot.cogs.community import CommunityCog
        from discord_bot.cogs.general import GeneralCog
        from discord_bot.cogs.maps import MapsCog
        from discord_bot.cogs.minecraft import MinecraftCog
        from discord_bot.cogs.social_sports import SocialSportsCog
        from discord_bot.cogs.transport import TransportCog
        from discord_bot.cogs.weather import WeatherCog

        timeout = aiohttp.ClientTimeout(total=20)
        self.web_session = aiohttp.ClientSession(timeout=timeout)
        for cog in (
            GeneralCog(self),
            TransportCog(self),
            WeatherCog(self),
            SocialSportsCog(self),
            MapsCog(self),
            AiCog(self),
            MinecraftCog(self),
            CommunityCog(self),
        ):
            await self.add_cog(cog)

        self.tree.on_error = self.on_app_command_error

        if self.settings.discord_test_guild_id:
            guild = discord.Object(id=self.settings.discord_test_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            LOGGER.info("已同步 %s 個測試伺服器指令", len(synced))
        else:
            synced = await self.tree.sync()
            LOGGER.info("已同步 %s 個全域指令", len(synced))

    async def close(self) -> None:
        if self.web_session and not self.web_session.closed:
            await self.web_session.close()
        await super().close()

    async def on_ready(self) -> None:
        LOGGER.info("Bot 已上線：%s（%s 個伺服器）", self.user, len(self.guilds))

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "你沒有執行此管理指令所需的權限。"
        elif isinstance(error, app_commands.CommandOnCooldown):
            message = f"請在 {error.retry_after:.1f} 秒後再試。"
        else:
            LOGGER.exception("斜線指令執行失敗", exc_info=error)
            message = "執行指令時發生錯誤，請稍後再試。"
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    settings = Settings.from_env()
    LifeAssistantBot(settings).run(settings.discord_token, log_handler=None)
