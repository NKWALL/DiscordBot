from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from urllib.parse import quote

import discord
from discord import app_commands
from discord.ext import commands

from discord_bot.utils import EMBED_COLOR, chunk_lines

TDX_BASE = "https://tdx.transportdata.tw/api/basic/v2"


def normalize_route_name(route: str) -> str:
    value = route.strip()
    colors = {
        "red": "紅",
        "green": "綠",
        "blue": "藍",
        "orange": "橘",
        "yellow": "黃",
        "brown": "棕",
        "purple": "紫",
    }
    lowered = value.lower()
    for english, chinese in colors.items():
        if lowered.startswith(english):
            return chinese + value[len(english) :]
    return value


def station_matches(item: dict, query: str) -> bool:
    name = item.get("StationName", {})
    if isinstance(name, dict):
        name = name.get("Zh_tw", "")
    station_id = str(item.get("StationID", ""))
    query = query.strip().lower()
    return query in str(name).lower() or query == station_id.lower()


class TdxClient:
    def __init__(self, bot):
        self.bot = bot
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def headers(self) -> dict[str, str]:
        client_id = self.bot.settings.tdx_client_id
        client_secret = self.bot.settings.tdx_client_secret
        if not client_id or not client_secret:
            raise RuntimeError("尚未設定 TDX_CLIENT_ID 與 TDX_CLIENT_SECRET")
        async with self._lock:
            if self._token and time.time() < self._expires_at:
                return {"Authorization": f"Bearer {self._token}"}
            assert self.bot.web_session is not None
            data = {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }
            async with self.bot.web_session.post(
                "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token",
                data=data,
            ) as response:
                payload = await response.json()
                if response.status != 200 or "access_token" not in payload:
                    raise RuntimeError(f"TDX 驗證失敗（HTTP {response.status}）")
            self._token = payload["access_token"]
            self._expires_at = time.time() + int(payload.get("expires_in", 300)) - 60
            return {"Authorization": f"Bearer {self._token}"}

    async def get(self, path: str, params: dict | None = None) -> list[dict]:
        assert self.bot.web_session is not None
        headers = await self.headers()
        query = {"$format": "JSON", **(params or {})}
        async with self.bot.web_session.get(
            f"{TDX_BASE}/{path}", headers=headers, params=query
        ) as response:
            payload = await response.json()
            if response.status != 200:
                raise RuntimeError(f"TDX 查詢失敗（HTTP {response.status}）")
            return payload if isinstance(payload, list) else []


class TransportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.tdx = TdxClient(bot)

    @app_commands.command(name="bus", description="查詢高雄公車各站即時到站資訊")
    @app_commands.describe(route="路線名稱，例如紅28、橘1或50", direction="0為去程，1為返程")
    async def bus(
        self, interaction: discord.Interaction, route: str, direction: int | None = None
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if direction not in {None, 0, 1}:
            await interaction.followup.send("方向只能填入 0 或 1。", ephemeral=True)
            return
        try:
            routes = await self.tdx.get("Bus/Route/City/Kaohsiung")
            normalized = normalize_route_name(route)
            matches = [
                item
                for item in routes
                if normalized == item.get("RouteName", {}).get("Zh_tw")
            ]
            if not matches:
                matches = [
                    item
                    for item in routes
                    if normalized in item.get("RouteName", {}).get("Zh_tw", "")
                ]
            if not matches:
                await interaction.followup.send("找不到該公車路線。", ephemeral=True)
                return
            route_data = matches[0]
            route_uid = route_data["RouteUID"]
            route_name = route_data["RouteName"]["Zh_tw"]
            query = {"$filter": f"RouteUID eq '{route_uid}'"}
            stops_data, eta_data = await asyncio.gather(
                self.tdx.get("Bus/StopOfRoute/City/Kaohsiung", query),
                self.tdx.get("Bus/EstimatedTimeOfArrival/City/Kaohsiung", query),
            )
        except RuntimeError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        eta_by_direction: dict[int, dict[str, list[tuple[str, int | None]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for item in eta_data:
            stop_name = item.get("StopName", {}).get("Zh_tw")
            if not stop_name or item.get("StopStatus") in {1, 3, 4}:
                continue
            eta_by_direction[int(item.get("Direction", 0))][stop_name].append(
                (str(item.get("PlateNumb") or "未提供車號"), item.get("EstimateTime"))
            )

        sequences: dict[int, list[tuple[int, str]]] = defaultdict(list)
        for subroute in stops_data:
            route_direction = int(subroute.get("Direction", 0))
            seen: set[str] = set()
            for stop in subroute.get("Stops", []):
                name = stop.get("StopName", {}).get("Zh_tw")
                if name and name not in seen:
                    seen.add(name)
                    sequences[route_direction].append((int(stop.get("StopSequence", 999)), name))

        directions = [direction] if direction is not None else sorted(sequences)
        for route_direction in directions:
            lines = []
            for _, stop_name in sorted(sequences.get(route_direction, [])):
                arrivals = sorted(
                    eta_by_direction[route_direction].get(stop_name, []),
                    key=lambda value: value[1] if value[1] is not None else 10**9,
                )[:2]
                if not arrivals:
                    lines.append(f"**{stop_name}** — 暫無即時車輛")
                    continue
                values = []
                for plate, seconds in arrivals:
                    if seconds is None:
                        eta = "時間未知"
                    elif seconds < 60:
                        eta = "進站中"
                    else:
                        eta = f"約 {seconds // 60} 分鐘"
                    values.append(f"{plate}／{eta}")
                lines.append(f"**{stop_name}** — {'、'.join(values)}")

            chunks = chunk_lines(lines, 1_000)
            embed = discord.Embed(
                title=f"{route_name}－{'去程' if route_direction == 0 else '返程'}",
                color=EMBED_COLOR,
            )
            for index, chunk in enumerate(chunks[:5], 1):
                embed.add_field(name=f"站點資訊 {index}", value=chunk, inline=False)
            if not embed.fields:
                embed.description = "目前沒有可顯示的站點資料。"
            elif len(chunks) > 5:
                embed.description = "站點較多，回覆顯示前段即時資訊。"
            embed.set_footer(text="資料來源：TDX 運輸資料流通服務")
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="metro", description="查詢高雄捷運車站資訊")
    @app_commands.describe(station="站名或站碼，例如美麗島、R10或O5")
    async def metro(self, interaction: discord.Interaction, station: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            data = await self.tdx.get("Rail/Metro/Station/KRTC")
        except RuntimeError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        matches = [item for item in data if station_matches(item, station)]
        if not matches:
            await interaction.followup.send("找不到該捷運站。", ephemeral=True)
            return
        info = matches[0]
        name = info.get("StationName", {}).get("Zh_tw", station)
        position = info.get("StationPosition", {})
        latitude = position.get("PositionLat")
        longitude = position.get("PositionLon")
        embed = discord.Embed(title=f"高雄捷運－{name}", color=EMBED_COLOR)
        embed.add_field(name="站碼", value=info.get("StationID", "未知"), inline=True)
        embed.add_field(name="地址", value=info.get("StationAddress", "未知"), inline=False)
        if latitude is not None and longitude is not None:
            embed.add_field(
                name="地圖",
                value=f"[在 Google Maps 開啟](https://www.google.com/maps?q={latitude},{longitude})",
                inline=False,
            )
        embed.add_field(
            name="相關資料",
            value=f"[搜尋維基百科](https://zh.wikipedia.org/wiki/{quote(name)})",
            inline=False,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="metro_liveboard", description="查詢高雄捷運即時到離站資訊")
    async def metro_liveboard(
        self, interaction: discord.Interaction, station: str
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            data = await self.tdx.get("Rail/Metro/LiveBoard/KRTC")
        except RuntimeError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        matches = [item for item in data if station_matches(item, station)]
        if not matches:
            await interaction.followup.send("找不到該站的即時資訊。", ephemeral=True)
            return
        embed = discord.Embed(title=f"{station} 即時到站資訊", color=EMBED_COLOR)
        for item in matches[:10]:
            destination = item.get("TripHeadSign") or item.get(
                "DestinationStationName", {}
            ).get("Zh_tw", "未知方向")
            estimate = item.get("EstimateTime")
            estimate_text = f"約 {estimate} 分鐘" if estimate is not None else "時間未知"
            embed.add_field(name=str(destination), value=estimate_text, inline=False)
        embed.set_footer(text="資料來源：TDX 運輸資料流通服務")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="metro_first_last", description="查詢高雄捷運首末班車")
    async def metro_first_last(
        self, interaction: discord.Interaction, station: str
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            data = await self.tdx.get("Rail/Metro/FirstLastTimetable/KRTC")
        except RuntimeError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        matches = [item for item in data if station_matches(item, station)]
        if not matches:
            await interaction.followup.send("找不到該站的首末班車資料。", ephemeral=True)
            return
        embed = discord.Embed(title=f"{station} 首末班車", color=EMBED_COLOR)
        for item in matches[:10]:
            destination = item.get("TripHeadSign") or item.get(
                "DestinationStationName", {}
            ).get("Zh_tw", "未知方向")
            embed.add_field(
                name=str(destination),
                value=(
                    f"首班車：{item.get('FirstTrainTime', '未知')}\n"
                    f"末班車：{item.get('LastTrainTime', '未知')}"
                ),
                inline=False,
            )
        embed.set_footer(text="資料來源：TDX 運輸資料流通服務")
        await interaction.followup.send(embed=embed, ephemeral=True)
