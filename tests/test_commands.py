import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

from discord_bot.bot import LifeAssistantBot
from discord_bot.cogs.ai import AiCog
from discord_bot.cogs.community import CommunityCog
from discord_bot.cogs.general import GeneralCog
from discord_bot.cogs.maps import MapsCog
from discord_bot.cogs.minecraft import MinecraftCog
from discord_bot.cogs.social_sports import SocialSportsCog
from discord_bot.cogs.transport import TransportCog
from discord_bot.cogs.weather import WeatherCog
from discord_bot.config import Settings


class CommandRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_public_commands_register_without_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            settings = Settings(
                discord_token="test-token",
                discord_test_guild_id=None,
                openweather_api_key=None,
                google_maps_api_key=None,
                gemini_api_key=None,
                tdx_client_id=None,
                tdx_client_secret=None,
                twitter_bearer_token=None,
                balldontlie_api_key=None,
                weather_push_channel_id=None,
                weather_push_city="Kaohsiung",
                weather_push_hour=8,
                timezone=ZoneInfo("Asia/Taipei"),
                data_dir=path,
                resource_links_file=path / "resources.json",
            )
            bot = LifeAssistantBot(settings)
            for cog in (
                GeneralCog(bot),
                TransportCog(bot),
                WeatherCog(bot),
                SocialSportsCog(bot),
                MapsCog(bot),
                AiCog(bot),
                MinecraftCog(bot),
                CommunityCog(bot),
            ):
                await bot.add_cog(cog)

            commands = [command.qualified_name for command in bot.tree.walk_commands()]
            self.assertEqual(len(commands), 38)
            self.assertEqual(len(commands), len(set(commands)))
            for expected in {
                "bus",
                "weather",
                "route_map",
                "ask_gemini",
                "mcmod",
                "response add",
                "ranking",
            }:
                self.assertIn(expected, commands)
            await bot.close()


if __name__ == "__main__":
    unittest.main()

