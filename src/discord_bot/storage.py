from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_DATA: dict[str, Any] = {
    "message_counts": {},
    "blocked_terms": {},
    "keyword_responses": {},
    "game_broadcast_channel_id": None,
    "weather_push_channel_id": None,
}


class JsonStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = asyncio.Lock()
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return deepcopy(DEFAULT_DATA)
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return deepcopy(DEFAULT_DATA)
        merged = deepcopy(DEFAULT_DATA)
        if isinstance(loaded, dict):
            merged.update(loaded)
        return merged

    async def save(self) -> None:
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            payload = json.dumps(self.data, ensure_ascii=False, indent=2)
            await asyncio.to_thread(temporary.write_text, payload, encoding="utf-8")
            await asyncio.to_thread(temporary.replace, self.path)

    async def increment_message_count(self, user_id: int) -> None:
        counts = self.data["message_counts"]
        key = str(user_id)
        counts[key] = int(counts.get(key, 0)) + 1
        await self.save()

    async def set_channel(self, key: str, channel_id: int | None) -> None:
        if key not in {"game_broadcast_channel_id", "weather_push_channel_id"}:
            raise KeyError(key)
        self.data[key] = channel_id
        await self.save()

