import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from discord_bot.storage import JsonStore


class StorageTests(unittest.TestCase):
    def test_store_persists_message_count_and_channel(self):
        async def scenario(path: Path):
            store = JsonStore(path)
            await store.increment_message_count(123)
            await store.set_channel("weather_push_channel_id", 456)

            reloaded = JsonStore(path)
            self.assertEqual(reloaded.data["message_counts"], {"123": 1})
            self.assertEqual(reloaded.data["weather_push_channel_id"], 456)
            json.loads(path.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory) / "bot_data.json"))


if __name__ == "__main__":
    unittest.main()
