# Discord Daily Report Agent

Discordの雑記チャンネル（times）を読んで、Claude APIで日報・月次振り返りを自動生成するBotです。

## できること

- **毎日 23:59 JST** に雑記チャンネルのメッセージを取得し、日報を生成して日報チャンネルに投稿
- **月末 23:59 JST** にその月の日報をまとめて月次サマリーを投稿

```
#times（雑記）          #daily-report（日報チャンネル）
────────────────        ──────────────────────────────
[09:00] PRレビュー  →   📋 2025年6月1日の日報
[11:00] バグ修正        ## やったこと
[14:30] MTG             - PRレビューとバグ修正
[16:00] ドキュメント    ## 気づき・メモ
                        - ...
                        ## 明日やること
                        - ...

                        （月末）
                        📊 2025年6月の月次振り返り
                        ## 今月のハイライト
                        - ...
```

---

## セットアップ

### 1. Discord Bot を作成する

1. [Discord Developer Portal](https://discord.com/developers/applications) を開く
2. **New Application** → 名前をつけて作成
3. **Bot** タブ → **Add Bot**
4. **Token** をコピー（後で使用）
5. **Privileged Gateway Intents** で以下を有効化：
   - `MESSAGE CONTENT INTENT`
6. **OAuth2 → URL Generator** で以下を選択してBotをサーバーに招待：
   - Scopes: `bot`
   - Bot Permissions: `Read Messages/View Channels`, `Send Messages`, `Read Message History`

### 2. チャンネルIDを取得する

Discordの設定で **開発者モード** を有効にする（設定 → 詳細設定 → 開発者モード）。

チャンネルを右クリック → **IDをコピー** で取得。

### 3. 環境変数を設定する

```bash
cp .env.example .env
```

`.env` を編集：

```env
DISCORD_BOT_TOKEN=取得したBotトークン
ANTHROPIC_API_KEY=AnthropicのAPIキー
DISCORD_MEMO_CHANNEL_ID=雑記チャンネルのID
DISCORD_REPORT_CHANNEL_ID=日報チャンネルのID
```

### 4. 依存パッケージをインストールする

```bash
pip install -r requirements.txt
```

### 5. 起動する

```bash
# .envを読み込んで起動
export $(cat .env | xargs) && python src/agent.py
```

またはdotenvを使う場合：

```bash
pip install python-dotenv
python -c "from dotenv import load_dotenv; load_dotenv()" && python src/agent.py
```

---

## 常駐起動（本番運用）

### systemd（Linux サーバー）

`/etc/systemd/system/discord-report-agent.service` を作成：

```ini
[Unit]
Description=Discord Daily Report Agent
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/discord-agent
EnvironmentFile=/path/to/discord-agent/.env
ExecStart=/usr/bin/python /path/to/discord-agent/src/agent.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable discord-report-agent
sudo systemctl start discord-report-agent
sudo systemctl status discord-report-agent
```

### screen / tmux（簡易）

```bash
screen -S discord-agent
export $(cat .env | xargs) && python src/agent.py
# Ctrl+A → D でデタッチ
```

---

## テスト

```bash
pip install pytest pytest-asyncio
pytest tests/test_agent.py -v
```

テスト項目（11件）：

| テスト                                            | 内容                              |
| ------------------------------------------------- | --------------------------------- |
| `test_call_claude_returns_text`                   | Claude APIが正常レスポンスを返す  |
| `test_call_claude_propagates_exception`           | APIエラーが伝播する               |
| `test_fetch_returns_messages`                     | 雑記メッセージが取得できる        |
| `test_fetch_excludes_bot_messages`                | BotのメッセージはScoped           |
| `test_fetch_returns_empty_when_channel_not_found` | チャンネル未発見時は空リスト      |
| `test_posts_report_when_memos_exist`              | メモありで日報が投稿される        |
| `test_posts_no_memo_message_when_empty`           | メモなしで専用メッセージ投稿      |
| `test_posts_error_message_on_api_failure`         | APIエラー時にエラーメッセージ投稿 |
| `test_truncates_long_report`                      | 長文日報が省略される              |
| `test_posts_monthly_summary`                      | 月次サマリーが投稿される          |
| `test_posts_no_report_message_when_no_reports`    | 日報なしで専用メッセージ投稿      |

---

## ファイル構成

```
discord-agent/
├── src/
│   └── agent.py          # メインのBot実装
├── tests/
│   └── test_agent.py     # テストスイート
├── requirements.txt      # 依存パッケージ
├── .env.example          # 環境変数テンプレート
└── README.md
```

---

## カスタマイズ

### 実行時刻を変更する

`agent.py` の `daily_report_task` デコレータを編集：

```python
# 例: 毎日22:00 JSTに変更（UTC 13:00）
@tasks.loop(time=discord.utils.utcnow().replace(hour=13, minute=0, ...).timetz())
```

### 日報フォーマットを変更する

`generate_daily_report` 内の `system_prompt` を編集してフォーマットを自由に変更できます。

### 月次レポートのトリガーを変更する

デフォルトは「翌日が別の月になる日」に自動実行されます。特定の日付に変えたい場合は `monthly_report_task` 内の条件を編集してください。
