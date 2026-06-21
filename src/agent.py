"""
Discord Daily Report Agent
- 毎日23:59に雑記チャンネルを取得してClaude APIで日報を生成、日報チャンネルへ投稿
- 月末に日報チャンネルの内容を集約して月次サマリーを生成
"""

import os
import asyncio
from datetime import datetime, timedelta, timezone
import logging

import discord
from discord.ext import tasks
import anthropic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


def now_jst() -> datetime:
    return datetime.now(JST)


class ReportAgent(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)

        self.anthropic = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.memo_channel_id = int(os.environ["DISCORD_MEMO_CHANNEL_ID"])
        self.report_channel_id = int(os.environ["DISCORD_REPORT_CHANNEL_ID"])

    async def on_ready(self):
        logger.info(f"Bot ready: {self.user}")
        self.daily_report_task.start()
        self.monthly_report_task.start()

    async def on_message(self, message: discord.Message):
        """手動トリガー（テスト用）
        !daily_report   → 今日の日報を今すぐ生成
        !monthly_report → 今月の月次サマリーを今すぐ生成
        """
        if message.author.bot:
            return
        if message.content == "!daily_report":
            logger.info("手動トリガー: 日報生成")
            await message.reply("日報を生成中...")
            await self.generate_daily_report()
        elif message.content == "!monthly_report":
            logger.info("手動トリガー: 月次サマリー生成")
            today = now_jst()
            await message.reply("月次サマリーを生成中...")
            await self.generate_monthly_report(today.year, today.month)

    @tasks.loop(time=discord.utils.utcnow().replace(hour=14, minute=59, second=0, microsecond=0).timetz())
    async def daily_report_task(self):
        """毎日23:59 JST（UTC 14:59）に日報を生成"""
        logger.info("日報生成タスク開始")
        await self.generate_daily_report()

    @tasks.loop(hours=24)
    async def monthly_report_task(self):
        """月末最終日の23:59に月次サマリーを生成"""
        today = now_jst()
        tomorrow = today + timedelta(days=1)
        if tomorrow.month != today.month:
            logger.info("月次サマリー生成タスク開始")
            await self.generate_monthly_report(today.year, today.month)

    async def fetch_today_memos(self) -> list[str]:
        """今日の雑記チャンネルのメッセージを取得"""
        channel = self.get_channel(self.memo_channel_id)
        if not channel:
            logger.error(f"雑記チャンネルが見つかりません: {self.memo_channel_id}")
            return []

        today = now_jst().date()
        after = datetime.combine(today, datetime.min.time()).replace(tzinfo=JST)

        messages = []
        async for msg in channel.history(after=after, oldest_first=True):
            if msg.author.bot:
                continue
            ts = msg.created_at.astimezone(JST).strftime("%H:%M")
            messages.append(f"[{ts}] {msg.content}")

        logger.info(f"今日のメモ取得件数: {len(messages)}")
        return messages

    async def fetch_month_reports(self, year: int, month: int) -> list[str]:
        """指定月の日報チャンネルからBot投稿（日報）を取得"""
        channel = self.get_channel(self.report_channel_id)
        if not channel:
            logger.error(f"日報チャンネルが見つかりません: {self.report_channel_id}")
            return []

        start = datetime(year, month, 1, tzinfo=JST)
        if month == 12:
            end = datetime(year + 1, 1, 1, tzinfo=JST)
        else:
            end = datetime(year, month + 1, 1, tzinfo=JST)

        reports = []
        async for msg in channel.history(after=start, before=end, oldest_first=True):
            if msg.author == self.user and msg.content.startswith("📋"):
                reports.append(msg.content)

        logger.info(f"{year}/{month} の日報取得件数: {len(reports)}")
        return reports

    def call_claude(self, system: str, user: str) -> str:
        """Claude APIを呼び出して結果を返す"""
        response = self.anthropic.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text

    async def generate_daily_report(self):
        memos = await self.fetch_today_memos()
        report_channel = self.get_channel(self.report_channel_id)
        if not report_channel:
            logger.error("日報チャンネルが見つかりません")
            return

        today_str = now_jst().strftime("%Y年%m月%d日")

        if not memos:
            await report_channel.send(
                f"📋 **{today_str}の日報**\n\n今日は雑記が記録されていませんでした。"
            )
            return

        memo_text = "\n".join(memos)

        system_prompt = """あなたは日報作成アシスタントです。
Discordの雑記（times）から、簡潔でわかりやすい日報を生成してください。

出力フォーマット（Markdown）:
## やったこと
- 箇条書きで具体的な作業内容

## 気づき・メモ
- 作業中に感じたことや残しておきたいこと（なければ省略）

## 明日やること
- 雑記から読み取れる次のアクション（明確でなければ「未定」）

ルール:
- 敬語不要、簡潔に
- 重複をまとめる
- 時刻は参考程度に使い、時系列の羅列にしない
"""

        user_prompt = f"{today_str}の雑記:\n\n{memo_text}"

        try:
            report_body = self.call_claude(system_prompt, user_prompt)
            message = f"📋 **{today_str}の日報**\n\n{report_body}"
            # Discordの2000字制限に対応
            if len(message) > 1900:
                message = message[:1900] + "\n\n...(省略)"
            await report_channel.send(message)
            logger.info("日報を投稿しました")
        except Exception as e:
            logger.error(f"日報生成エラー: {e}")
            await report_channel.send(f"⚠️ 日報の生成中にエラーが発生しました: {e}")

    async def generate_monthly_report(self, year: int, month: int):
        reports = await self.fetch_month_reports(year, month)
        report_channel = self.get_channel(self.report_channel_id)
        if not report_channel:
            return

        month_str = f"{year}年{month}月"

        if not reports:
            await report_channel.send(
                f"📊 **{month_str}の月次振り返り**\n\nこの月の日報が見つかりませんでした。"
            )
            return

        combined = "\n\n---\n\n".join(reports)

        system_prompt = """あなたは月次振り返りアシスタントです。
1ヶ月分の日報をもとに、月次の振り返りレポートを生成してください。

出力フォーマット（Markdown）:
## 今月のハイライト
- 特に重要だった成果や出来事（3〜5個）

## やったことまとめ
- カテゴリ別に分類して整理

## 気づき・学び
- 月を通して気づいたこと、学んだこと

## 来月に向けて
- 継続すること、改善したいこと

ルール:
- 全日報を横断して重複をまとめる
- 細かすぎる作業は統合して書く
- ポジティブかつ具体的に
"""

        user_prompt = f"{month_str}の日報一覧:\n\n{combined[:6000]}"  # トークン節約

        try:
            summary = self.call_claude(system_prompt, user_prompt)
            message = f"📊 **{month_str}の月次振り返り**\n\n{summary}"
            if len(message) > 1900:
                # 長い場合は複数メッセージに分割
                chunks = [message[i:i+1900] for i in range(0, len(message), 1900)]
                for chunk in chunks:
                    await report_channel.send(chunk)
            else:
                await report_channel.send(message)
            logger.info(f"{month_str}の月次サマリーを投稿しました")
        except Exception as e:
            logger.error(f"月次サマリー生成エラー: {e}")
            await report_channel.send(f"⚠️ 月次サマリーの生成中にエラーが発生しました: {e}")


def main():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise ValueError("DISCORD_BOT_TOKEN が設定されていません")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("ANTHROPIC_API_KEY が設定されていません")
    if not os.environ.get("DISCORD_MEMO_CHANNEL_ID"):
        raise ValueError("DISCORD_MEMO_CHANNEL_ID が設定されていません")
    if not os.environ.get("DISCORD_REPORT_CHANNEL_ID"):
        raise ValueError("DISCORD_REPORT_CHANNEL_ID が設定されていません")

    client = ReportAgent()
    client.run(token)


if __name__ == "__main__":
    main()