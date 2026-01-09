# Links2RSS Telegram Bot

A lightweight Telegram bot that automatically extracts links from your group messages and transforms them into a personal RSS feed. Perfect for keeping track of shared articles, news, and resources without getting lost in the chat history.

## 🚀 Features

- **Automatic Link Extraction**: Captures URLs from text messages and media captions.
- **Rich Metadata**: Automatically fetches Open Graph tags (title, description, image) to make your RSS feed look great in any reader.
- **Per-Chat Feeds**: Each group or private chat gets its own unique, token-authenticated RSS feed.
- **SQLite Backend**: Durable storage for links using SQLite with WAL mode for performance.
- **FastAPI Powered**: High-performance RSS delivery.
- **Easy Setup**: Minimal configuration required.

## 🛠️ Technology Stack

- [Python 3.14+](https://www.python.org/)
- [python-telegram-bot](https://python-telegram-bot.org/) - For Telegram interaction.
- [FastAPI](https://fastapi.tiangolo.com/) - To serve the RSS XML.
- [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) - For scraping link metadata.
- [SQLite](https://www.sqlite.org/) - For lightweight, reliable data storage.
- [uv](https://docs.astral.sh/uv/) - For ultra-fast Python package management.

## 📋 Prerequisites

- A Telegram Bot Token (get one from [@BotFather](https://t.me/BotFather))
- [uv](https://docs.astral.sh/uv/getting-started/installation/) installed on your system.

## ⚙️ Configuration

The bot is configured via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Your Telegram Bot Token (**Required**) | - |
| `APP_URL` | The base URL where your RSS feed is hosted | `http://localhost:8080` |
| `HTTP_PORT` | Port for the FastAPI server | `8080` |
| `DB_PATH` | Path to the SQLite database file | `links.db` |

## 🚀 Installation & Running

Since this project uses `uv`, setup is near-instant:

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd links2rss-telegram-bot
   ```

2. **Set up your environment:**
   Create a `.env` file or export your token:
   ```bash
   export TELEGRAM_BOT_TOKEN="your_token_here"
   export APP_URL="https://your-public-domain.com"
   ```

3. **Run the bot:**
   `uv` will automatically handle environment creation and dependency installation:
   ```bash
   uv run main.py
   ```

## 📖 Usage

1. **Add the bot** to your Telegram group or start a private chat with it.
2. **Share links**: Just post any URL in the chat. The bot will automatically scrape metadata and save it.
3. **Get your feed**: Send the `/rssfeed` command to the bot. It will reply with your unique RSS URL.
4. **Subscribe**: Copy the URL and add it to your favorite RSS reader (e.g., Feedly, NetNewsWire, Reeder).

## 📄 License

This project is open-source and available under the AGPLv3 License.
