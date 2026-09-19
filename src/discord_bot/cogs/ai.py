from __future__ import annotations

import asyncio
from collections import defaultdict, deque

import discord
from discord import app_commands
from discord.ext import commands
from google import genai

from discord_bot.utils import EMBED_COLOR, chunk_text


class AiCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.history: dict[int, deque[tuple[str, str]]] = defaultdict(lambda: deque(maxlen=6))

    async def _generate(self, prompt: str) -> str:
        key = self.bot.settings.gemini_api_key
        if not key:
            raise RuntimeError("尚未設定 GEMINI_API_KEY")

        def request() -> str:
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            return response.text or "模型未回傳文字內容。"

        return await asyncio.to_thread(request)

    @app_commands.command(name="ask_gemini", description="向 Gemini 提問並保留近期對話脈絡")
    @app_commands.describe(question="想詢問的問題")
    @app_commands.checks.cooldown(2, 30, key=lambda interaction: interaction.user.id)
    async def ask_gemini(self, interaction: discord.Interaction, question: str) -> None:
        await interaction.response.defer(ephemeral=True)
        conversation = self.history[interaction.user.id]
        context = "\n".join(
            f"使用者：{user}\n助理：{assistant}" for user, assistant in conversation
        )
        prompt = f"{context}\n使用者：{question}\n助理：" if context else question
        try:
            answer = await self._generate(prompt[-12_000:])
        except Exception as exc:
            await interaction.followup.send(f"Gemini 查詢失敗：{exc}", ephemeral=True)
            return
        conversation.append((question, answer))
        chunks = chunk_text(answer, 1_000)[:20]
        for page_start in range(0, len(chunks), 5):
            page = page_start // 5 + 1
            embed = discord.Embed(
                title="Gemini 回覆" if page == 1 else f"Gemini 回覆（續 {page}）",
                description=f"**問題：** {question[:500]}" if page == 1 else None,
                color=EMBED_COLOR,
            )
            for index, chunk in enumerate(chunks[page_start : page_start + 5], page_start + 1):
                embed.add_field(
                    name="回覆" if index == 1 else f"回覆（續 {index}）",
                    value=chunk,
                    inline=False,
                )
            if len(answer) > 20_000 and page_start + 5 >= len(chunks):
                embed.set_footer(text="回覆內容過長，已顯示前 20,000 個字元。")
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="reset_ai", description="清除自己的 Gemini 近期對話脈絡")
    async def reset_ai(self, interaction: discord.Interaction) -> None:
        self.history.pop(interaction.user.id, None)
        await interaction.response.send_message("已清除近期對話脈絡。", ephemeral=True)
