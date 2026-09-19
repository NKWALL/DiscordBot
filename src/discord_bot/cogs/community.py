from __future__ import annotations

from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands
from discord.utils import utcnow

from discord_bot.utils import EMBED_COLOR
from discord_bot.utils import chunk_text


class ResponseGroup(app_commands.Group):
    def __init__(self, cog: "CommunityCog"):
        super().__init__(name="response", description="管理動態關鍵字回覆")
        self.cog = cog

    @app_commands.command(name="add", description="新增關鍵字回覆")
    @app_commands.checks.has_permissions(administrator=True)
    async def add(self, interaction: discord.Interaction, keyword: str, response: str) -> None:
        self.cog.bot.store.data["keyword_responses"][keyword] = response
        await self.cog.bot.store.save()
        await interaction.response.send_message(
            f"已設定 `{keyword}` 的回覆內容。", ephemeral=True
        )

    @app_commands.command(name="remove", description="移除關鍵字回覆")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove(self, interaction: discord.Interaction, keyword: str) -> None:
        responses = self.cog.bot.store.data["keyword_responses"]
        if keyword not in responses:
            await interaction.response.send_message("找不到該關鍵字。", ephemeral=True)
            return
        del responses[keyword]
        await self.cog.bot.store.save()
        await interaction.response.send_message(f"已移除 `{keyword}`。", ephemeral=True)

    @app_commands.command(name="list", description="列出關鍵字回覆")
    async def list_responses(self, interaction: discord.Interaction) -> None:
        responses = self.cog.bot.store.data["keyword_responses"]
        text = "\n".join(f"- `{key}` → {value}" for key, value in responses.items())
        chunks = chunk_text(text, 1_900) if text else ["目前沒有關鍵字回覆。"]
        await interaction.response.send_message(chunks[0], ephemeral=True)
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk, ephemeral=True)


class CommunityCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.member_games: dict[int, set[str]] = {}
        self.bot.tree.add_command(ResponseGroup(self))

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command("response")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        await self.bot.store.increment_message_count(message.author.id)

        for keyword, duration in self.bot.store.data["blocked_terms"].items():
            if keyword not in message.content:
                continue
            try:
                until = utcnow() + timedelta(seconds=int(duration))
                await message.author.timeout(until, reason="觸發伺服器禁語規則")
                await message.channel.send(
                    f"{message.author.mention} 已依伺服器規則暫停發言。",
                    delete_after=10,
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
            except (discord.Forbidden, discord.HTTPException):
                await message.channel.send("無法執行禁言，請檢查 Bot 權限。", delete_after=10)
            break

        for keyword, response in self.bot.store.data["keyword_responses"].items():
            if keyword in message.content:
                await message.channel.send(
                    response,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                break

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member) -> None:
        if after.bot:
            return
        before_games = {
            activity.name
            for activity in before.activities
            if activity.type == discord.ActivityType.playing
        }
        after_games = {
            activity.name
            for activity in after.activities
            if activity.type == discord.ActivityType.playing
        }
        if after_games:
            self.member_games[after.id] = after_games
        else:
            self.member_games.pop(after.id, None)

        channel_id = self.bot.store.data.get("game_broadcast_channel_id")
        if not channel_id:
            return
        channel = self.bot.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            return
        for game in after_games - before_games:
            await channel.send(
                f"{after.display_name} 開始玩 **{game}**。",
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @app_commands.command(name="add_blocked_term", description="新增禁語與禁言時間")
    @app_commands.describe(keyword="禁語", minutes="禁言分鐘數")
    @app_commands.checks.has_permissions(administrator=True)
    async def add_blocked_term(
        self,
        interaction: discord.Interaction,
        keyword: str,
        minutes: app_commands.Range[int, 1, 10_080],
    ) -> None:
        self.bot.store.data["blocked_terms"][keyword] = int(minutes) * 60
        await self.bot.store.save()
        await interaction.response.send_message(
            f"已新增禁語 `{keyword}`，禁言時間為 {minutes} 分鐘。", ephemeral=True
        )

    @app_commands.command(name="remove_blocked_term", description="移除禁語")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_blocked_term(
        self, interaction: discord.Interaction, keyword: str
    ) -> None:
        terms = self.bot.store.data["blocked_terms"]
        if keyword not in terms:
            await interaction.response.send_message("找不到該禁語。", ephemeral=True)
            return
        del terms[keyword]
        await self.bot.store.save()
        await interaction.response.send_message(f"已移除 `{keyword}`。", ephemeral=True)

    @app_commands.command(name="list_blocked_terms", description="列出禁語與禁言時間")
    @app_commands.checks.has_permissions(administrator=True)
    async def list_blocked_terms(self, interaction: discord.Interaction) -> None:
        terms = self.bot.store.data["blocked_terms"]
        text = "\n".join(
            f"- `{term}`：{int(seconds) // 60} 分鐘" for term, seconds in terms.items()
        )
        await interaction.response.send_message(text or "目前沒有設定禁語。", ephemeral=True)

    @app_commands.command(name="set_game_broadcast", description="設定遊戲狀態廣播頻道")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_game_broadcast(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        await self.bot.store.set_channel("game_broadcast_channel_id", channel.id)
        await interaction.response.send_message(
            f"已將遊戲狀態廣播頻道設為 {channel.mention}。", ephemeral=True
        )

    @app_commands.command(name="game_status", description="查看目前成員公開的遊戲狀態")
    async def game_status(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("此指令只能在伺服器使用。", ephemeral=True)
            return
        embed = discord.Embed(title="目前遊戲狀態", color=EMBED_COLOR)
        for member_id, games in self.member_games.items():
            member = interaction.guild.get_member(member_id)
            if member:
                embed.add_field(
                    name=member.display_name,
                    value="\n".join(f"• {game}" for game in sorted(games)),
                    inline=False,
                )
        if not embed.fields:
            embed.description = "目前沒有可顯示的遊戲狀態。"
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ranking", description="查看伺服器訊息數排行榜")
    async def ranking(
        self, interaction: discord.Interaction, top: app_commands.Range[int, 1, 25] = 10
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("此指令只能在伺服器使用。", ephemeral=True)
            return
        counts = self.bot.store.data["message_counts"]
        ranking = sorted(counts.items(), key=lambda item: int(item[1]), reverse=True)[:top]
        lines = []
        for index, (user_id, count) in enumerate(ranking, 1):
            member = interaction.guild.get_member(int(user_id))
            name = member.display_name if member else "已離開的成員"
            lines.append(f"{index}. {name} — {count} 則")
        embed = discord.Embed(
            title="訊息活躍度排行榜",
            description="\n".join(lines) or "目前尚無統計資料。",
            color=EMBED_COLOR,
        )
        await interaction.response.send_message(embed=embed)
