# Telegram Summary Bot

A Telegram bot that stores group messages and generates AI-powered summaries of new, unsummarized messages. Supports threads and customizable AI endpoints.

## Features

- 📝 Stores group messages in SQLite database
- 🧵 Full support for Telegram threads/topics
- 🤖 AI-powered summaries using Chat Completions API
- ⚙️ Customizable AI endpoint, model, and API key
- 🔄 Tracks which messages have been summarized
- 📊 Configurable message limit for summaries
- 👤 Includes usernames in summaries

## Requirements

- Python 3.8+
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))
- AI API key (OpenAI or compatible endpoint)

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd tg-summary-bot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create `.env` file from template:
```bash
cp .env.example .env
```

4. Edit `.env` and configure your settings:
```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
AI_API_ENDPOINT=https://api.openai.com/v1/chat/completions
AI_API_KEY=your_api_key_here
AI_MODEL=gpt-3.5-turbo
MESSAGE_LIMIT=100
AI_MAX_TOKENS=1500
AI_MAX_INPUT_CHARS=60000
AI_REQUEST_TIMEOUT=120
SIMPLE_AI_BOT_ENABLED=false
SIMPLE_AI_BOT_USERNAME=
SIMPLE_AI_MAX_TOKENS=250
TELEGRAM_MESSAGE_LIMIT=3900
DATABASE_PATH=bot_data.db
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Your Telegram bot token | Required |
| `AI_API_ENDPOINT` | Chat Completions API endpoint | Required |
| `AI_API_KEY` | API key for AI service | Required |
| `AI_MODEL` | Model name to use | `gpt-3.5-turbo` |
| `MESSAGE_LIMIT` | Max messages to include in summary | `100` |
| `AI_MAX_TOKENS` | Max tokens to request for generated summaries | `1500` |
| `AI_MAX_INPUT_CHARS` | Max formatted conversation characters allowed in one AI request | `60000` |
| `AI_REQUEST_TIMEOUT` | Timeout in seconds for one AI API request, including streaming responses | `120` |
| `SIMPLE_AI_BOT_ENABLED` | Enable one-shot AI replies when a message mentions the bot username | `false` |
| `SIMPLE_AI_BOT_USERNAME` | Bot username used for mention matching; fetched from Telegram when empty | Optional |
| `SIMPLE_AI_MAX_TOKENS` | Max tokens to request for simple mention replies | `250` |
| `TELEGRAM_MESSAGE_LIMIT` | Max characters per Telegram summary chunk | `3900` |
| `DATABASE_PATH` | SQLite database file path | `bot_data.db` |
| `THREADED_SEPARATED` | Summarize only current thread when `true`, or all threads grouped when `false` | `true` |
| `AUTO_SUMMARY_ENABLED` | Enable daily automatic summaries | `false` |
| `AUTO_SUMMARY_TIME` | Daily automatic summary time in `HH:MM` format | `09:00` |
| `AUTO_SUMMARY_CHAT_ID` | Chat ID for automatic summaries | Optional |
| `ALLOWED_CHAT_ID` | Restrict the bot to a single chat ID | Optional |

Automatic summaries require the JobQueue extra from `python-telegram-bot`. It is included in `requirements.txt`; reinstall dependencies after updating.

## Usage

1. Start the bot:
```bash
python bot.py
```

2. Add the bot to your Telegram group

3. Grant the bot permission to read messages

4. Available commands:
   - `/start` - Show welcome message and help
   - `/summary` - Generate summary of new unsummarized messages

5. Optional simple AI replies:
   - Set `SIMPLE_AI_BOT_ENABLED=true`
   - Mention the bot in a regular message, for example `@my_bot_name что ты умеешь?`
   - The bot removes `@my_bot_name` before sending the request to the AI endpoint
   - Each mention is answered independently, without chat history

## How It Works

The bot tracks which messages have been summarized:
- When you run `/summary`, it only includes messages that haven't been summarized yet
- After generating a summary, those messages are marked as summarized
- Next time you run `/summary`, only new messages since the last summary will be included
- Each summary includes the username of who sent each message
- Long summaries are split into multiple Telegram messages to stay below Telegram message length limits
- If the formatted AI input exceeds `AI_MAX_INPUT_CHARS`, the bot summarizes the largest fitting batch and keeps the remaining messages for the next summary

## Thread Support

The bot automatically detects if a message or command is sent in a thread (topic) and handles it accordingly:
- Messages in threads are stored with their thread ID
- `/summary` in a thread will summarize only that thread's unsummarized messages
- `/summary` in the main chat will summarize main chat's unsummarized messages
- Each thread maintains its own summarization state

## Database

The bot uses SQLite to store messages with the following schema:
- `chat_id`: Telegram chat identifier
- `message_id`: Telegram message identifier
- `thread_id`: Thread/topic identifier (null for main chat)
- `user_id`: User identifier
- `username`: Username or first name
- `text`: Message text
- `timestamp`: Message timestamp
- `summarized`: Flag indicating if message has been included in a summary (0 or 1)

## Custom AI Endpoints

The bot supports any Chat Completions API compatible endpoint. Examples:
- OpenAI: `https://api.openai.com/v1/chat/completions`
- Azure OpenAI: `https://<resource>.openai.azure.com/openai/deployments/<deployment>/chat/completions?api-version=2024-02-15-preview`
- Local LLM servers (Ollama, LM Studio, etc.)

## License

MIT
