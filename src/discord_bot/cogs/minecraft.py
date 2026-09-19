from __future__ import annotations

import html
import json
import re

import discord
from discord import app_commands
from discord.ext import commands

from discord_bot.utils import EMBED_COLOR

MODRINTH_TYPES = [
    app_commands.Choice(name="模組", value="mod"),
    app_commands.Choice(name="模組包", value="modpack"),
    app_commands.Choice(name="資源包", value="resourcepack"),
    app_commands.Choice(name="光影", value="shader"),
]


class MinecraftCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _modrinth(self, params: dict) -> list[dict]:
        assert self.bot.web_session is not None
        headers = {"User-Agent": "DiscordLifeAssistant/1.0 (portfolio project)"}
        async with self.bot.web_session.get(
            "https://api.modrinth.com/v2/search", params=params, headers=headers
        ) as response:
            payload = await response.json()
            if response.status != 200:
                raise RuntimeError(f"Modrinth 查詢失敗（HTTP {response.status}）")
            return payload.get("hits", [])

    @app_commands.command(name="mcmod", description="搜尋 Minecraft 模組與資源")
    @app_commands.describe(query="搜尋關鍵字", project_type="資源類型", loader="模組載入器")
    @app_commands.choices(
        project_type=MODRINTH_TYPES,
        loader=[
            app_commands.Choice(name="全部", value=""),
            app_commands.Choice(name="Forge", value="forge"),
            app_commands.Choice(name="Fabric", value="fabric"),
            app_commands.Choice(name="NeoForge", value="neoforge"),
            app_commands.Choice(name="Quilt", value="quilt"),
        ],
    )
    async def mcmod(
        self,
        interaction: discord.Interaction,
        query: str,
        project_type: app_commands.Choice[str],
        loader: app_commands.Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        facets = [[f"project_type:{project_type.value}"]]
        if loader and loader.value:
            facets.append([f"categories:{loader.value}"])
        try:
            hits = await self._modrinth(
                {"query": query, "limit": 5, "facets": json.dumps(facets)}
            )
        except RuntimeError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        if not hits:
            await interaction.followup.send("找不到符合條件的項目。", ephemeral=True)
            return
        embed = discord.Embed(
            title=f"Minecraft {project_type.name}搜尋結果",
            description=f"關鍵字：`{query}`",
            color=EMBED_COLOR,
        )
        for item in hits:
            slug = item.get("slug", "")
            embed.add_field(
                name=item.get("title", "未命名項目"),
                value=(
                    f"{item.get('description', '沒有說明')[:150]}\n"
                    f"下載：{item.get('downloads', 0):,}｜追蹤：{item.get('follows', 0):,}\n"
                    f"[前往 Modrinth](https://modrinth.com/{project_type.value}/{slug})"
                ),
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="mctrending", description="查看熱門或近期 Minecraft 資源")
    @app_commands.choices(
        sort=[
            app_commands.Choice(name="最相關", value="relevance"),
            app_commands.Choice(name="下載最多", value="downloads"),
            app_commands.Choice(name="追蹤最多", value="follows"),
            app_commands.Choice(name="最新上傳", value="newest"),
            app_commands.Choice(name="最近更新", value="updated"),
        ],
        project_type=MODRINTH_TYPES,
    )
    async def mctrending(
        self,
        interaction: discord.Interaction,
        sort: app_commands.Choice[str],
        project_type: app_commands.Choice[str],
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        facets = f'[["project_type:{project_type.value}"]]'
        try:
            hits = await self._modrinth(
                {"limit": 5, "index": sort.value, "facets": facets}
            )
        except RuntimeError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        embed = discord.Embed(
            title=f"{sort.name}的 Minecraft {project_type.name}", color=EMBED_COLOR
        )
        for index, item in enumerate(hits, 1):
            slug = item.get("slug", "")
            embed.add_field(
                name=f"{index}. {item.get('title', '未命名項目')}",
                value=(
                    f"{item.get('description', '沒有說明')[:120]}\n"
                    f"[前往 Modrinth](https://modrinth.com/{project_type.value}/{slug})"
                ),
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="mc_player", description="查詢 Minecraft 玩家 UUID、造型與披風")
    async def mc_player(self, interaction: discord.Interaction, player: str) -> None:
        await interaction.response.defer(ephemeral=True)
        assert self.bot.web_session is not None
        async with self.bot.web_session.get(
            f"https://api.mojang.com/users/profiles/minecraft/{player}"
        ) as response:
            if response.status in {204, 404}:
                await interaction.followup.send("找不到該玩家。", ephemeral=True)
                return
            data = await response.json()
        player_uuid = data["id"]
        name = data["name"]
        cape_url = f"https://crafatar.com/capes/{player_uuid}"
        async with self.bot.web_session.get(cape_url) as cape_response:
            has_cape = cape_response.status == 200
        embed = discord.Embed(title=f"Minecraft 玩家：{name}", color=EMBED_COLOR)
        embed.set_thumbnail(
            url=f"https://crafatar.com/avatars/{player_uuid}?size=256&overlay"
        )
        embed.add_field(name="UUID", value=player_uuid, inline=False)
        embed.add_field(
            name="造型",
            value=f"[下載 Skin](https://crafatar.com/skins/{player_uuid})",
            inline=False,
        )
        embed.add_field(
            name="披風",
            value=f"[下載 Cape]({cape_url})" if has_cape else "此玩家沒有公開披風。",
            inline=False,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="mc_wiki", description="搜尋 Minecraft Wiki")
    async def mc_wiki(self, interaction: discord.Interaction, keyword: str) -> None:
        await interaction.response.defer(ephemeral=True)
        assert self.bot.web_session is not None
        headers = {"User-Agent": "DiscordLifeAssistant/1.0 (portfolio project)"}
        params = {
            "action": "query",
            "list": "search",
            "srsearch": keyword,
            "format": "json",
            "srlimit": 5,
        }
        async with self.bot.web_session.get(
            "https://minecraft.wiki/api.php", params=params, headers=headers
        ) as response:
            data = await response.json()
        results = data.get("query", {}).get("search", [])
        if not results:
            await interaction.followup.send("找不到相關條目。", ephemeral=True)
            return
        top = results[0]
        title = top["title"]
        summary = html.unescape(re.sub(r"<.*?>", "", top.get("snippet", "")))
        wiki_url = f"https://minecraft.wiki/w/{title.replace(' ', '_')}"
        embed = discord.Embed(
            title=title,
            url=wiki_url,
            description=summary[:500],
            color=EMBED_COLOR,
        )
        if len(results) > 1:
            others = [
                f"• [{item['title']}](https://minecraft.wiki/w/{item['title'].replace(' ', '_')})"
                for item in results[1:4]
            ]
            embed.add_field(name="其他結果", value="\n".join(others), inline=False)
        embed.set_footer(text="資料來源：Minecraft Wiki")
        await interaction.followup.send(embed=embed, ephemeral=True)
