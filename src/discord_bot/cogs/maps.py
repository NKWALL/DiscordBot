from __future__ import annotations

import io
from typing import Any
from urllib.parse import urlencode

import discord
from discord import app_commands
from discord.ext import commands

from discord_bot.utils import EMBED_COLOR, chunk_lines, first_list, haversine_km

GOOGLE_API_BASE = "https://maps.googleapis.com/maps/api"
UBIKE_API_URL = "https://api.kcg.gov.tw/api/service/Get/b4dd9c40-9027-4125-8666-06bef1756092"


class MapsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _google_key(self) -> str:
        key = self.bot.settings.google_maps_api_key
        if not key:
            raise RuntimeError("尚未設定 GOOGLE_MAPS_API_KEY")
        return key

    async def _google_json(self, endpoint: str, params: dict[str, Any]) -> dict:
        assert self.bot.web_session is not None
        query = {**params, "key": self._google_key()}
        async with self.bot.web_session.get(
            f"{GOOGLE_API_BASE}/{endpoint}", params=query
        ) as response:
            data = await response.json()
            if response.status != 200:
                raise RuntimeError(f"Google Maps 查詢失敗（HTTP {response.status}）")
            status = data.get("status")
            if status not in {None, "OK"}:
                raise RuntimeError(f"Google Maps 查詢失敗（{status}）")
            return data

    async def _static_map(
        self, params: list[tuple[str, str]], filename: str = "map.png"
    ) -> discord.File:
        assert self.bot.web_session is not None
        query = [*params, ("key", self._google_key())]
        async with self.bot.web_session.get(
            f"{GOOGLE_API_BASE}/staticmap", params=query
        ) as response:
            if response.status != 200:
                raise RuntimeError(f"靜態地圖產生失敗（HTTP {response.status}）")
            image = await response.read()
        return discord.File(io.BytesIO(image), filename=filename)

    async def _geocode(self, query: str) -> tuple[float, float, str]:
        data = await self._google_json(
            "geocode/json", {"address": query, "language": "zh-TW"}
        )
        results = data.get("results", [])
        if not results:
            raise RuntimeError("找不到指定地點")
        result = results[0]
        location = result["geometry"]["location"]
        return float(location["lat"]), float(location["lng"]), result["formatted_address"]

    @app_commands.command(name="route_map", description="比較不同交通方式並繪製最快路線")
    @app_commands.describe(origin="起點地址或地標", destination="終點地址或地標")
    async def route_map(
        self, interaction: discord.Interaction, origin: str, destination: str
    ) -> None:
        await interaction.response.defer()
        modes = {
            "driving": "開車",
            "transit": "大眾運輸",
            "walking": "步行",
            "bicycling": "自行車",
        }
        results: dict[str, dict] = {}
        for mode, label in modes.items():
            try:
                data = await self._google_json(
                    "directions/json",
                    {
                        "origin": origin,
                        "destination": destination,
                        "mode": mode,
                        "language": "zh-TW",
                    },
                )
            except RuntimeError:
                continue
            route = data["routes"][0]
            leg = route["legs"][0]
            results[mode] = {
                "label": label,
                "duration": leg["duration"]["text"],
                "seconds": int(leg["duration"]["value"]),
                "distance": leg["distance"]["text"],
                "start": leg["start_address"],
                "end": leg["end_address"],
                "polyline": route["overview_polyline"]["points"],
            }
        if not results:
            await interaction.followup.send("找不到可用路線，請確認起訖地點。")
            return

        fastest_mode = min(results, key=lambda mode: results[mode]["seconds"])
        fastest = results[fastest_mode]
        try:
            map_file = await self._static_map(
                [
                    ("size", "700x400"),
                    ("scale", "2"),
                    ("path", f"color:0x6f42c1ff|weight:5|enc:{fastest['polyline']}"),
                ],
                "route-map.png",
            )
        except RuntimeError as exc:
            await interaction.followup.send(str(exc))
            return

        comparisons = []
        for mode, label in modes.items():
            if mode not in results:
                comparisons.append(f"**{label}：** 無可用路線")
                continue
            result = results[mode]
            marker = "（最快）" if mode == fastest_mode else ""
            comparisons.append(
                f"**{label}{marker}：** {result['duration']}／{result['distance']}"
            )
        maps_url = "https://www.google.com/maps/dir/?" + urlencode(
            {
                "api": 1,
                "origin": origin,
                "destination": destination,
                "travelmode": fastest_mode,
            }
        )
        embed = discord.Embed(
            title="Google Maps 路線比較",
            description=(
                f"**起點：** {fastest['start']}\n"
                f"**終點：** {fastest['end']}\n\n"
                + "\n".join(comparisons)
                + f"\n\n[開啟 Google Maps 導航]({maps_url})"
            ),
            color=EMBED_COLOR,
        )
        embed.set_image(url="attachment://route-map.png")
        await interaction.followup.send(embed=embed, file=map_file)

    @app_commands.command(name="food_search", description="搜尋指定地點附近的餐飲店家")
    @app_commands.describe(
        location="地區或地標",
        category="餐飲類別",
        limit="顯示數量",
        min_rating="最低評分",
        open_only="只顯示營業中店家",
    )
    @app_commands.choices(
        category=[
            app_commands.Choice(name="餐廳", value="restaurant"),
            app_commands.Choice(name="飲料／咖啡", value="cafe"),
            app_commands.Choice(name="點心／烘焙", value="bakery"),
            app_commands.Choice(name="甜點", value="dessert"),
        ]
    )
    async def food_search(
        self,
        interaction: discord.Interaction,
        location: str,
        category: app_commands.Choice[str],
        limit: app_commands.Range[int, 1, 10] = 5,
        min_rating: app_commands.Range[float, 0, 5] = 0,
        open_only: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            center_lat, center_lng, _ = await self._geocode(location)
            data = await self._google_json(
                "place/textsearch/json",
                {
                    "query": f"{location} {category.name}",
                    "type": category.value if category.value != "dessert" else "bakery",
                    "language": "zh-TW",
                },
            )
        except RuntimeError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        places = []
        for place in data.get("results", []):
            if float(place.get("rating", 0)) < float(min_rating):
                continue
            if open_only and not place.get("opening_hours", {}).get("open_now", False):
                continue
            places.append(place)
            if len(places) >= limit:
                break
        if not places:
            await interaction.followup.send("沒有符合篩選條件的店家。", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"{location}附近的{category.name}", color=EMBED_COLOR
        )
        map_params: list[tuple[str, str]] = [
            ("center", f"{center_lat},{center_lng}"),
            ("zoom", "14"),
            ("size", "640x640"),
            ("scale", "2"),
            ("markers", f"color:red|label:C|{center_lat},{center_lng}"),
        ]
        for index, place in enumerate(places, 1):
            point = place["geometry"]["location"]
            distance = haversine_km(
                center_lat, center_lng, float(point["lat"]), float(point["lng"])
            )
            place_id = place.get("place_id", "")
            open_now = place.get("opening_hours", {}).get("open_now")
            status = "營業中" if open_now else "未營業或狀態未知"
            embed.add_field(
                name=f"{index}. {place.get('name', '未知店家')}",
                value=(
                    f"{place.get('formatted_address', '地址未知')}\n"
                    f"距離約 {distance:.2f} km｜評分 {place.get('rating', '無')}｜{status}\n"
                    f"[在 Google Maps 開啟](https://www.google.com/maps/place/?q=place_id:{place_id})"
                ),
                inline=False,
            )
            map_params.append(
                ("markers", f"color:blue|label:{index}|{point['lat']},{point['lng']}")
            )
        try:
            map_file = await self._static_map(map_params, "food-map.png")
            embed.set_image(url="attachment://food-map.png")
            await interaction.followup.send(embed=embed, file=map_file, ephemeral=True)
        except RuntimeError:
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="find_place", description="搜尋地點並標示於地圖")
    async def find_place(
        self,
        interaction: discord.Interaction,
        query: str,
        limit: app_commands.Range[int, 1, 10] = 5,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            data = await self._google_json(
                "place/textsearch/json", {"query": query, "language": "zh-TW"}
            )
        except RuntimeError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        places = data.get("results", [])[:limit]
        if not places:
            await interaction.followup.send("找不到該地點。", ephemeral=True)
            return
        latitudes = [float(item["geometry"]["location"]["lat"]) for item in places]
        longitudes = [float(item["geometry"]["location"]["lng"]) for item in places]
        center_lat = sum(latitudes) / len(latitudes)
        center_lng = sum(longitudes) / len(longitudes)
        embed = discord.Embed(title=f"地點搜尋：{query}", color=EMBED_COLOR)
        map_params: list[tuple[str, str]] = [
            ("center", f"{center_lat},{center_lng}"),
            ("zoom", "14"),
            ("size", "640x640"),
            ("scale", "2"),
        ]
        for index, place in enumerate(places, 1):
            point = place["geometry"]["location"]
            place_id = place.get("place_id", "")
            embed.add_field(
                name=f"{index}. {place.get('name', '未知地點')}",
                value=(
                    f"{place.get('formatted_address', '地址未知')}\n"
                    f"[在 Google Maps 開啟](https://www.google.com/maps/place/?q=place_id:{place_id})"
                ),
                inline=False,
            )
            map_params.append(
                ("markers", f"color:blue|label:{index}|{point['lat']},{point['lng']}")
            )
        try:
            map_file = await self._static_map(map_params, "places-map.png")
            embed.set_image(url="attachment://places-map.png")
            await interaction.followup.send(embed=embed, file=map_file, ephemeral=True)
        except RuntimeError:
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _ubike_stations(self) -> list[dict]:
        assert self.bot.web_session is not None
        async with self.bot.web_session.get(UBIKE_API_URL) as response:
            payload = await response.json()
            if response.status != 200:
                raise RuntimeError(f"YouBike 資料查詢失敗（HTTP {response.status}）")
        stations = payload.get("data", {}).get("data", {}).get("retVal")
        if isinstance(stations, list):
            return [item for item in stations if isinstance(item, dict)]
        stations = first_list(payload)
        if not stations:
            raise RuntimeError("YouBike API 未回傳站點資料")
        return stations

    @staticmethod
    def _station_location(station: dict) -> tuple[float, float] | None:
        try:
            return float(station["lat"]), float(station["lng"])
        except (KeyError, TypeError, ValueError):
            return None

    async def _send_ubike_map(
        self,
        interaction: discord.Interaction,
        title: str,
        stations: list[dict],
        center: tuple[float, float],
    ) -> None:
        if not stations:
            await interaction.followup.send("找不到符合條件的站點。", ephemeral=True)
            return
        lines = []
        map_params: list[tuple[str, str]] = [
            ("center", f"{center[0]},{center[1]}"),
            ("zoom", "14"),
            ("size", "640x640"),
            ("scale", "2"),
            ("markers", f"color:red|label:C|{center[0]},{center[1]}"),
        ]
        for index, station in enumerate(stations[:10], 1):
            location = self._station_location(station)
            if not location:
                continue
            distance = haversine_km(center[0], center[1], location[0], location[1])
            name = str(station.get("sna", "未知站名")).removeprefix("YouBike2.0_")
            lines.append(
                f"**{index}. {name}**－約 {distance:.2f} km｜"
                f"可借 {station.get('sbi', '?')}／可還 {station.get('bemp', '?')}\n"
                f"{station.get('ar', '地址未知')}"
            )
            map_params.append(
                ("markers", f"color:blue|label:{index}|{location[0]},{location[1]}")
            )
        embed = discord.Embed(title=title, color=EMBED_COLOR)
        for index, chunk in enumerate(chunk_lines(lines, 1_000), 1):
            embed.add_field(name=f"站點資訊 {index}", value=chunk, inline=False)
        try:
            map_file = await self._static_map(map_params, "ubike-map.png")
            embed.set_image(url="attachment://ubike-map.png")
            await interaction.followup.send(embed=embed, file=map_file, ephemeral=True)
        except RuntimeError:
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="ubike_map", description="查詢高雄指定行政區的 YouBike 站點")
    async def ubike_map(self, interaction: discord.Interaction, area: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            stations = await self._ubike_stations()
        except RuntimeError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        filtered = [station for station in stations if area in str(station.get("sarea", ""))]
        valid = [(station, self._station_location(station)) for station in filtered]
        valid = [(station, location) for station, location in valid if location]
        if not valid:
            await interaction.followup.send("找不到該行政區的站點。", ephemeral=True)
            return
        center = (
            sum(location[0] for _, location in valid) / len(valid),
            sum(location[1] for _, location in valid) / len(valid),
        )
        nearest = sorted(
            [station for station, _ in valid],
            key=lambda station: haversine_km(
                center[0], center[1], *self._station_location(station)
            ),
        )[:10]
        await self._send_ubike_map(
            interaction, f"{area} YouBike 站點（顯示鄰近中心的 10 站）", nearest, center
        )

    @app_commands.command(name="ubike_near", description="查詢高雄指定地標附近的 YouBike 站點")
    async def ubike_near(self, interaction: discord.Interaction, landmark: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            latitude, longitude, address = await self._geocode(f"高雄 {landmark}")
            stations = await self._ubike_stations()
        except RuntimeError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        stations = [station for station in stations if self._station_location(station)]
        nearest = sorted(
            stations,
            key=lambda station: haversine_km(
                latitude, longitude, *self._station_location(station)
            ),
        )[:10]
        await self._send_ubike_map(
            interaction, f"{address}附近的 YouBike 站點", nearest, (latitude, longitude)
        )

    @app_commands.command(name="ubike_nsysu", description="查詢中山大學附近的 YouBike 站點")
    async def ubike_nsysu(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        center = (22.6273, 120.2644)
        try:
            stations = await self._ubike_stations()
        except RuntimeError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        stations = [station for station in stations if self._station_location(station)]
        nearest = sorted(
            stations,
            key=lambda station: haversine_km(*center, *self._station_location(station)),
        )[:10]
        await self._send_ubike_map(
            interaction, "國立中山大學附近的 YouBike 站點", nearest, center
        )
