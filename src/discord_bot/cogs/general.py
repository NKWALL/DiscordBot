from __future__ import annotations

import json
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from discord_bot.utils import EMBED_COLOR, safe_calculate


class HelpView(discord.ui.View):
    def __init__(self, pages: list[discord.Embed]):
        super().__init__(timeout=180)
        self.pages = pages
        self.index = 0

    async def _show(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="上一頁", style=discord.ButtonStyle.secondary)
    async def previous(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        self.index = max(0, self.index - 1)
        await self._show(interaction)

    @discord.ui.button(label="下一頁", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.index = min(len(self.pages) - 1, self.index + 1)
        await self._show(interaction)


class GeneralCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="hello", description="測試機器人是否在線")
    async def hello(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Hello! Bot 目前在線。", ephemeral=True)

    @app_commands.command(name="calc", description="安全計算數學表達式")
    @app_commands.describe(expression="支援 + - * / ^ %、括號及 sqrt/sin/cos/tan/log/ln")
    async def calculate(self, interaction: discord.Interaction, expression: str) -> None:
        try:
            result = safe_calculate(expression)
        except (SyntaxError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
            await interaction.response.send_message(f"無法計算：{exc}", ephemeral=True)
            return
        embed = discord.Embed(
            title="計算結果",
            description=f"**表達式：** `{expression}`\n**結果：** `{result}`",
            color=EMBED_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="links", description="列出自訂的常用資源連結")
    async def links(self, interaction: discord.Interaction) -> None:
        path: Path = self.bot.settings.resource_links_file
        if not path.exists():
            await interaction.response.send_message(
                "尚未建立資源連結檔。請複製 `data/resources.example.json` 為 "
                "`data/resources.json` 後再修改。",
                ephemeral=True,
            )
            return
        try:
            resources = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            await interaction.response.send_message("資源連結檔格式錯誤。", ephemeral=True)
            return
        if not isinstance(resources, dict) or not resources:
            await interaction.response.send_message("目前沒有設定資源連結。", ephemeral=True)
            return
        embed = discord.Embed(title="常用資源連結", color=EMBED_COLOR)
        for name, url in list(resources.items())[:25]:
            embed.add_field(name=str(name), value=f"[開啟連結]({url})", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="help", description="顯示所有可用的斜線指令")
    async def help_command(self, interaction: discord.Interaction) -> None:
        commands_list = sorted(self.bot.tree.walk_commands(), key=lambda item: item.qualified_name)
        entries = [
            (f"/{command.qualified_name}", command.description or "沒有說明")
            for command in commands_list
            if not isinstance(command, app_commands.Group)
        ]
        pages: list[discord.Embed] = []
        page_size = 12
        for start in range(0, len(entries), page_size):
            page_entries = entries[start : start + page_size]
            embed = discord.Embed(title="指令列表", color=EMBED_COLOR)
            for name, description in page_entries:
                embed.add_field(name=name, value=description, inline=False)
            embed.set_footer(
                text=f"第 {start // page_size + 1}/{(len(entries) - 1) // page_size + 1} 頁"
            )
            pages.append(embed)
        if len(pages) == 1:
            await interaction.response.send_message(embed=pages[0], ephemeral=True)
        else:
            await interaction.response.send_message(
                embed=pages[0], view=HelpView(pages), ephemeral=True
            )

