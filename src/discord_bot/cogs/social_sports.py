from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import discord
import tweepy
from discord import app_commands
from discord.ext import commands

from discord_bot.utils import EMBED_COLOR


class SocialSportsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _nba_headers(self) -> dict[str, str]:
        key = self.bot.settings.balldontlie_api_key
        return {"Authorization": key} if key else {}

    async def _nba_games(self, dates: list[str]) -> list[dict]:
        assert self.bot.web_session is not None
        params: list[tuple[str, str | int]] = [("per_page", 100)]
        params.extend(("dates[]", date) for date in dates)
        async with self.bot.web_session.get(
            "https://api.balldontlie.io/v1/games",
            params=params,
            headers=self._nba_headers(),
        ) as response:
            payload = await response.json()
            if response.status != 200:
                raise RuntimeError(f"NBA 資料查詢失敗（HTTP {response.status}）")
            return payload.get("data", [])

    @staticmethod
    def _team_name(team: dict) -> str:
        return team.get("full_name") or team.get("name") or "未知球隊"

    def _games_embed(self, title: str, games: list[dict]) -> discord.Embed:
        embed = discord.Embed(title=title, color=EMBED_COLOR)
        if not games:
            embed.description = "目前沒有比賽資料。"
            return embed
        for game in games[:20]:
            home = self._team_name(game.get("home_team", {}))
            visitor = self._team_name(game.get("visitor_team", {}))
            status = str(game.get("status", "時間未定"))
            home_score = game.get("home_team_score", 0)
            visitor_score = game.get("visitor_team_score", 0)
            embed.add_field(
                name=f"{visitor} vs. {home}",
                value=(
                    f"日期：{str(game.get('date', '未知'))[:10]}\n"
                    f"比分：{visitor_score}－{home_score}\n"
                    f"狀態：{status}"
                ),
                inline=False,
            )
        embed.set_footer(text="資料來源：balldontlie API")
        return embed

    @app_commands.command(name="nba", description="查詢 NBA 近期比賽結果")
    async def nba(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        today = datetime.now(self.bot.settings.timezone).date()
        dates = [(today - timedelta(days=offset)).isoformat() for offset in range(7)]
        try:
            games = await self._nba_games(dates)
        except RuntimeError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        games.sort(key=lambda game: str(game.get("date", "")), reverse=True)
        await interaction.followup.send(
            embed=self._games_embed("NBA 近期賽事", games), ephemeral=True
        )

    @app_commands.command(name="nba_today", description="查詢 NBA 今日賽程")
    async def nba_today(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        today = datetime.now(self.bot.settings.timezone).date().isoformat()
        try:
            games = await self._nba_games([today])
        except RuntimeError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(
            embed=self._games_embed(f"NBA 今日賽程（{today}）", games), ephemeral=True
        )

    @app_commands.command(name="nba_date", description="查詢指定日期的 NBA 賽程")
    @app_commands.describe(date="日期格式：YYYY-MM-DD")
    async def nba_date(self, interaction: discord.Interaction, date: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            await interaction.followup.send("日期格式必須是 YYYY-MM-DD。", ephemeral=True)
            return
        try:
            games = await self._nba_games([date])
        except RuntimeError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(
            embed=self._games_embed(f"NBA 賽程（{date}）", games), ephemeral=True
        )

    @app_commands.command(name="nba_player", description="查詢 NBA 球員基本資料")
    @app_commands.describe(name="球員英文姓名，例如 LeBron James")
    async def nba_player(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True)
        assert self.bot.web_session is not None
        async with self.bot.web_session.get(
            "https://api.balldontlie.io/v1/players",
            params={"search": name, "per_page": 10},
            headers=self._nba_headers(),
        ) as response:
            payload = await response.json()
        if response.status != 200:
            await interaction.followup.send(
                f"球員查詢失敗（HTTP {response.status}）。", ephemeral=True
            )
            return
        players = payload.get("data", [])
        if not players:
            await interaction.followup.send("找不到該球員。", ephemeral=True)
            return
        player = players[0]
        full_name = f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
        team = player.get("team", {})
        embed = discord.Embed(title=full_name, color=EMBED_COLOR)
        embed.add_field(name="位置", value=player.get("position") or "未提供", inline=True)
        embed.add_field(name="球隊", value=self._team_name(team), inline=True)
        embed.add_field(name="身高", value=player.get("height") or "未提供", inline=True)
        embed.add_field(name="體重", value=player.get("weight") or "未提供", inline=True)
        embed.add_field(name="國籍", value=player.get("country") or "未提供", inline=True)
        embed.add_field(name="大學", value=player.get("college") or "未提供", inline=True)
        embed.set_footer(text="資料來源：balldontlie API")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="tweet", description="查詢指定 X／Twitter 帳號的最新貼文")
    async def tweet(self, interaction: discord.Interaction, username: str) -> None:
        await interaction.response.defer(ephemeral=True)
        token = self.bot.settings.twitter_bearer_token
        if not token:
            await interaction.followup.send(
                "尚未設定 TWITTER_BEARER_TOKEN。", ephemeral=True
            )
            return

        def fetch_latest() -> tuple[str, str] | None:
            client = tweepy.Client(bearer_token=token)
            user = client.get_user(username=username)
            if not user.data:
                return None
            tweets = client.get_users_tweets(id=user.data.id, max_results=5)
            if not tweets.data:
                return None
            latest = next((tweet for tweet in tweets.data if tweet.text), None)
            if not latest:
                return None
            return latest.text, f"https://x.com/{username}/status/{latest.id}"

        try:
            result = await asyncio.to_thread(fetch_latest)
        except tweepy.TooManyRequests:
            await interaction.followup.send("請求次數已達限制，請稍後再試。", ephemeral=True)
            return
        except tweepy.TweepyException:
            await interaction.followup.send("無法取得該帳號的貼文。", ephemeral=True)
            return
        if not result:
            await interaction.followup.send("找不到可顯示的貼文。", ephemeral=True)
            return
        text, url = result
        embed = discord.Embed(
            title=f"@{username} 最新貼文",
            description=f"{text[:500]}\n\n[在 X 開啟]({url})",
            color=EMBED_COLOR,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
