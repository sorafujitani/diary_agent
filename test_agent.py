"""
テストスイート for Discord Daily Report Agent

実行方法:
    pip install pytest pytest-asyncio
    pytest tests/test_agent.py -v
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

JST = timezone(timedelta(hours=9))

# 環境変数をテスト用に設定
os.environ.setdefault("DISCORD_BOT_TOKEN", "dummy_token")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy_key")
os.environ.setdefault("DISCORD_MEMO_CHANNEL_ID", "111111111111111111")
os.environ.setdefault("DISCORD_REPORT_CHANNEL_ID", "222222222222222222")


# ─────────────────────────────────────────────
# ユニットテスト: call_claude
# ─────────────────────────────────────────────

class TestCallClaude:
    """Claude API呼び出しのテスト"""

    def _make_agent(self):
        with patch("discord.Client.__init__", return_value=None):
            from agent import ReportAgent
            agent = ReportAgent.__new__(ReportAgent)
            agent.memo_channel_id = 111111111111111111
            agent.report_channel_id = 222222222222222222
            return agent

    def test_call_claude_returns_text(self):
        """正常なAPIレスポンスからテキストを返す"""
        agent = self._make_agent()

        mock_content = MagicMock()
        mock_content.text = "テスト日報の本文"
        mock_response = MagicMock()
        mock_response.content = [mock_content]

        mock_anthropic = MagicMock()
        mock_anthropic.messages.create.return_value = mock_response
        agent.anthropic = mock_anthropic

        result = agent.call_claude("system prompt", "user prompt")

        assert result == "テスト日報の本文"
        mock_anthropic.messages.create.assert_called_once_with(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            system="system prompt",
            messages=[{"role": "user", "content": "user prompt"}],
        )

    def test_call_claude_propagates_exception(self):
        """APIエラーが伝播する"""
        agent = self._make_agent()

        mock_anthropic = MagicMock()
        mock_anthropic.messages.create.side_effect = Exception("API Error")
        agent.anthropic = mock_anthropic

        with pytest.raises(Exception, match="API Error"):
            agent.call_claude("system", "user")


# ─────────────────────────────────────────────
# 非同期テスト: fetch_today_memos
# ─────────────────────────────────────────────

@pytest.mark.asyncio
class TestFetchTodayMemos:
    """今日のメモ取得のテスト"""

    def _make_agent(self):
        with patch("discord.Client.__init__", return_value=None):
            from agent import ReportAgent
            agent = ReportAgent.__new__(ReportAgent)
            agent.memo_channel_id = 111111111111111111
            agent.report_channel_id = 222222222222222222
            return agent

    def _make_message(self, content: str, is_bot: bool = False, hour: int = 10):
        msg = MagicMock()
        msg.content = content
        msg.author = MagicMock()
        msg.author.bot = is_bot
        msg.created_at = datetime(2025, 6, 1, hour, 0, 0, tzinfo=JST)
        return msg

    async def test_fetch_returns_messages(self):
        """通常メッセージが取得できる"""
        agent = self._make_agent()

        msg1 = self._make_message("タスクAを完了", hour=9)
        msg2 = self._make_message("タスクBを開始", hour=11)

        mock_channel = MagicMock()
        mock_channel.history = MagicMock(return_value=self._async_iter([msg1, msg2]))
        agent.get_channel = MagicMock(return_value=mock_channel)

        result = await agent.fetch_today_memos()

        assert len(result) == 2
        assert "タスクAを完了" in result[0]
        assert "タスクBを開始" in result[1]

    async def test_fetch_excludes_bot_messages(self):
        """Botのメッセージは除外される"""
        agent = self._make_agent()

        human_msg = self._make_message("人間のメモ", is_bot=False)
        bot_msg = self._make_message("Botのメッセージ", is_bot=True)

        mock_channel = MagicMock()
        mock_channel.history = MagicMock(return_value=self._async_iter([human_msg, bot_msg]))
        agent.get_channel = MagicMock(return_value=mock_channel)

        result = await agent.fetch_today_memos()

        assert len(result) == 1
        assert "人間のメモ" in result[0]

    async def test_fetch_returns_empty_when_channel_not_found(self):
        """チャンネルが見つからない場合は空リストを返す"""
        agent = self._make_agent()
        agent.get_channel = MagicMock(return_value=None)

        result = await agent.fetch_today_memos()

        assert result == []

    @staticmethod
    async def _async_iter(items):
        for item in items:
            yield item


# ─────────────────────────────────────────────
# 非同期テスト: generate_daily_report
# ─────────────────────────────────────────────

@pytest.mark.asyncio
class TestGenerateDailyReport:
    """日報生成のテスト"""

    def _make_agent(self):
        with patch("discord.Client.__init__", return_value=None):
            from agent import ReportAgent
            agent = ReportAgent.__new__(ReportAgent)
            agent.memo_channel_id = 111111111111111111
            agent.report_channel_id = 222222222222222222
            return agent

    async def test_posts_report_when_memos_exist(self):
        """メモがある場合、日報が投稿される"""
        agent = self._make_agent()
        agent.fetch_today_memos = AsyncMock(return_value=["[09:00] タスクA完了", "[14:00] PRレビュー"])
        agent.call_claude = MagicMock(return_value="## やったこと\n- タスクA完了\n- PRレビュー")

        mock_channel = MagicMock()
        mock_channel.send = AsyncMock()
        agent.get_channel = MagicMock(return_value=mock_channel)

        await agent.generate_daily_report()

        mock_channel.send.assert_called_once()
        sent_text = mock_channel.send.call_args[0][0]
        assert "📋" in sent_text
        assert "日報" in sent_text

    async def test_posts_no_memo_message_when_empty(self):
        """メモが空の場合、専用メッセージが投稿される"""
        agent = self._make_agent()
        agent.fetch_today_memos = AsyncMock(return_value=[])

        mock_channel = MagicMock()
        mock_channel.send = AsyncMock()
        agent.get_channel = MagicMock(return_value=mock_channel)

        await agent.generate_daily_report()

        mock_channel.send.assert_called_once()
        sent_text = mock_channel.send.call_args[0][0]
        assert "記録されていませんでした" in sent_text

    async def test_posts_error_message_on_api_failure(self):
        """Claude APIがエラーの場合、エラーメッセージが投稿される"""
        agent = self._make_agent()
        agent.fetch_today_memos = AsyncMock(return_value=["[10:00] 作業中"])
        agent.call_claude = MagicMock(side_effect=Exception("API timeout"))

        mock_channel = MagicMock()
        mock_channel.send = AsyncMock()
        agent.get_channel = MagicMock(return_value=mock_channel)

        await agent.generate_daily_report()

        sent_text = mock_channel.send.call_args[0][0]
        assert "⚠️" in sent_text

    async def test_truncates_long_report(self):
        """2000字を超える日報は省略される"""
        agent = self._make_agent()
        agent.fetch_today_memos = AsyncMock(return_value=["[09:00] メモ"])
        agent.call_claude = MagicMock(return_value="a" * 2000)

        mock_channel = MagicMock()
        mock_channel.send = AsyncMock()
        agent.get_channel = MagicMock(return_value=mock_channel)

        await agent.generate_daily_report()

        sent_text = mock_channel.send.call_args[0][0]
        assert len(sent_text) <= 1950
        assert "省略" in sent_text


# ─────────────────────────────────────────────
# 非同期テスト: generate_monthly_report
# ─────────────────────────────────────────────

@pytest.mark.asyncio
class TestGenerateMonthlyReport:
    """月次サマリー生成のテスト"""

    def _make_agent(self):
        with patch("discord.Client.__init__", return_value=None):
            from agent import ReportAgent
            agent = ReportAgent.__new__(ReportAgent)
            agent.memo_channel_id = 111111111111111111
            agent.report_channel_id = 222222222222222222
            return agent

    async def test_posts_monthly_summary(self):
        """日報がある場合、月次サマリーが投稿される"""
        agent = self._make_agent()
        agent.fetch_month_reports = AsyncMock(return_value=[
            "📋 **6月1日の日報**\n\n## やったこと\n- タスクA",
            "📋 **6月2日の日報**\n\n## やったこと\n- タスクB",
        ])
        agent.call_claude = MagicMock(return_value="## 今月のハイライト\n- タスクA, Bを完了")

        mock_channel = MagicMock()
        mock_channel.send = AsyncMock()
        agent.get_channel = MagicMock(return_value=mock_channel)

        await agent.generate_monthly_report(2025, 6)

        mock_channel.send.assert_called()
        sent_text = mock_channel.send.call_args[0][0]
        assert "📊" in sent_text
        assert "月次振り返り" in sent_text

    async def test_posts_no_report_message_when_no_reports(self):
        """日報がない場合、専用メッセージが投稿される"""
        agent = self._make_agent()
        agent.fetch_month_reports = AsyncMock(return_value=[])

        mock_channel = MagicMock()
        mock_channel.send = AsyncMock()
        agent.get_channel = MagicMock(return_value=mock_channel)

        await agent.generate_monthly_report(2025, 6)

        sent_text = mock_channel.send.call_args[0][0]
        assert "見つかりませんでした" in sent_text
