import asyncio
import os
import re
import sqlite3
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime

import httpx
import uvicorn
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters


@dataclass
class OGData:
    """Open Graph metadata"""

    title: str | None = None
    description: str | None = None
    image: str | None = None


@dataclass
class LinkData:
    """Link data with metadata"""

    url: str
    title: str
    description: str
    date: datetime
    image: str | None = None
    message_id: int | None = None


# Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
HTTP_PORT = int(os.getenv("HTTP_PORT", "8080"))
APP_URL = os.getenv("APP_URL", f"http://localhost:{HTTP_PORT}")
DB_PATH = os.getenv("DB_PATH", "links.local.db")

# Store links in memory (use database for production)
links = []

# Database connection
db_conn: sqlite3.Connection | None = None

# URL regex pattern
URL_PATTERN = re.compile(r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+")

# FastAPI app
app = FastAPI(title="Telegram RSS Feed")


def init_database() -> None:
    """Initialize SQLite database"""
    global db_conn
    # Use timeout for concurrent access
    db_conn = sqlite3.connect(DB_PATH, timeout=10.0, check_same_thread=False)
    db_conn.row_factory = sqlite3.Row
    cursor = db_conn.cursor()

    # Enable WAL mode for better concurrent access
    cursor.execute("PRAGMA journal_mode=WAL")

    # Set busy timeout for concurrent access (5 seconds)
    cursor.execute("PRAGMA busy_timeout=5000")

    # Balance between safety and performance
    cursor.execute("PRAGMA synchronous=NORMAL")

    # Increase cache size for better performance
    cursor.execute("PRAGMA cache_size=-64000")

    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys=ON")

    # Create groups table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS groups (
            chat_id TEXT PRIMARY KEY,
            token TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # Create links table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            url TEXT NOT NULL,
            title TEXT,
            description TEXT,
            image TEXT,
            message_id INTEGER,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (chat_id) REFERENCES groups(chat_id)
        )
        """
    )

    db_conn.commit()


def get_group_token(chat_id: int | str) -> str:
    """Get or create token for a group"""
    if not db_conn:
        return ""

    chat_id_str = str(chat_id)
    cursor = db_conn.cursor()

    # Check if group exists
    cursor.execute("SELECT token FROM groups WHERE chat_id = ?", (chat_id_str,))
    result = cursor.fetchone()

    if result:
        return result[0]

    # Create new token for group
    token = str(uuid.uuid4())
    cursor.execute("INSERT INTO groups (chat_id, token) VALUES (?, ?)", (chat_id_str, token))
    db_conn.commit()

    return token


def save_link(chat_id: int | str, link_data: LinkData) -> None:
    """Save link to database"""
    if not db_conn:
        return

    chat_id_str = str(chat_id)
    cursor = db_conn.cursor()

    cursor.execute(
        """
        INSERT INTO links (chat_id, url, title, description, image, message_id, date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chat_id_str,
            link_data.url,
            link_data.title,
            link_data.description,
            link_data.image,
            link_data.message_id,
            link_data.date,
        ),
    )
    db_conn.commit()


def get_links(chat_id: int | str, limit: int = 50) -> list[LinkData]:
    """Get links for a group from database"""
    if not db_conn:
        return []

    chat_id_str = str(chat_id)
    cursor = db_conn.cursor()

    cursor.execute(
        """
        SELECT url, title, description, image, message_id, date FROM links
        WHERE chat_id = ? ORDER BY date DESC LIMIT ?
        """,
        (chat_id_str, limit),
    )

    links_list = []
    for row in cursor.fetchall():
        link = LinkData(
            url=row[0],
            title=row[1],
            description=row[2],
            image=row[3],
            message_id=row[4],
            date=datetime.fromisoformat(row[5]),
        )
        links_list.append(link)

    return links_list


def delete_group_links(chat_id: int | str, message_id: int) -> None:
    """Delete links for a specific message"""
    if not db_conn:
        return

    chat_id_str = str(chat_id)
    cursor = db_conn.cursor()

    cursor.execute("DELETE FROM links WHERE chat_id = ? AND message_id = ?", (chat_id_str, message_id))
    db_conn.commit()


async def fetch_og_tags(url: str) -> OGData:
    """Fetch Open Graph tags from a URL"""
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(
                url, headers={"User-Agent": "Mozilla/5.0 (compatible; TelegramRSSBot/1.0)"}
            )
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # Extract OG tags
            og_data = OGData()

            # Try og:title
            og_title = soup.find("meta", property="og:title")
            if og_title:
                og_data.title = str(og_title.get("content"))

            # Fallback to title tag
            if not og_data.title:
                title_tag = soup.find("title")
                if title_tag:
                    og_data.title = str(title_tag.string) if title_tag.string else None

            # Try og:description
            og_desc = soup.find("meta", property="og:description")
            if og_desc:
                og_data.description = str(og_desc.get("content"))

            # Fallback to meta description
            if not og_data.description:
                meta_desc = soup.find("meta", attrs={"name": "description"})
                if meta_desc:
                    og_data.description = str(meta_desc.get("content"))

            # Try og:image
            og_image = soup.find("meta", property="og:image")
            if og_image:
                og_data.image = str(og_image.get("content"))

            return og_data

    except Exception as e:
        print(f"Error fetching OG tags for {url}: {e}")
        return OGData()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Extract and store links from messages"""
    message = update.message or update.edited_message
    if not message:
        return

    text = message.text or message.caption or ""
    urls = URL_PATTERN.findall(text)
    if not urls:
        return

    message_id = message.message_id
    user_name = message.from_user.first_name if message.from_user else "Unknown"

    # Remove existing links from this message (for edited messages)
    delete_group_links(message.chat_id, message_id)

    for url in urls:
        # Fetch OG tags
        og_data = await fetch_og_tags(url)

        # Use OG data or fallback to URL
        title = og_data.title if og_data.title else url
        description = og_data.description if og_data.description else ""

        # Add "Shared by" prefix to description
        shared_by = f"Shared by {user_name}"
        if description:
            full_description = f"{shared_by} - {description}"
        else:
            full_description = shared_by

        link_data = LinkData(
            url=url,
            title=title,
            description=full_description,
            date=datetime.now(),
            image=og_data.image,
            message_id=message_id,
        )
        save_link(message.chat_id, link_data)

    print(f"Found {len(urls)} link(s) in message from {user_name} in chat {message.chat_id}")


async def handle_rssfeed_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /rssfeed command to get RSS feed link"""
    print("Received /rssfeed command")
    print(f"Update: {update}")

    if not update.message or not update.message.chat_id:
        return

    chat_id = update.message.chat_id
    token = get_group_token(chat_id)

    # Build RSS feed URL
    rss_url = f"{APP_URL}/rss?token={token}"

    message = f"Your RSS feed link, use it in your RSS reader:\n{rss_url}"
    await update.message.reply_text(message, parse_mode="Markdown")


def generate_rss(chat_id: int | str) -> str:
    """Generate RSS feed XML for a specific group"""
    links_list = get_links(chat_id, limit=50)

    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = "Telegram Group Links"
    ET.SubElement(channel, "link").text = f"{APP_URL}/rss/{chat_id}"
    ET.SubElement(channel, "description").text = "Links shared in Telegram group"
    ET.SubElement(channel, "lastBuildDate").text = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")

    for link in links_list:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = link.title
        ET.SubElement(item, "link").text = link.url
        ET.SubElement(item, "description").text = link.description
        ET.SubElement(item, "pubDate").text = link.date.strftime("%a, %d %b %Y %H:%M:%S +0000")
        ET.SubElement(item, "guid").text = f"{link.url}_{link.date.timestamp()}"

        # Add enclosure for image if available
        if link.image:
            ET.SubElement(item, "enclosure", url=link.image, type="image/jpeg")

    return ET.tostring(rss, encoding="unicode", method="xml")


@app.get("/")
async def root():
    """Root endpoint with usage instructions"""
    return {
        "message": "Telegram RSS Feed Server",
        "usage": "Access RSS feed at /rss?token=YOUR_TOKEN",
        "links_count": 0,
    }


@app.get("/rss")
async def rss_feed(token: str = Query(..., description="Group authentication token")):
    """RSS feed endpoint with token-based authentication"""
    if not db_conn:
        raise HTTPException(status_code=500, detail="Database not initialized")

    cursor = db_conn.cursor()
    cursor.execute("SELECT chat_id FROM groups WHERE token = ?", (token,))
    result = cursor.fetchone()

    if not result:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid token")

    chat_id = result[0]
    rss_content = generate_rss(chat_id)

    from fastapi.responses import Response

    return Response(content=rss_content, media_type="application/rss+xml")


@app.get("/health")
async def health():
    """Health check endpoint"""
    if not db_conn:
        return {"status": "error", "message": "Database not initialized"}

    cursor = db_conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM links")
    link_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM groups")
    group_count = cursor.fetchone()[0]

    return {
        "status": "ok",
        "links_count": link_count,
        "groups_count": group_count,
    }


async def run_fastapi_server() -> None:
    """Run FastAPI server using uvicorn.Server"""
    print(f"FastAPI server starting on port {HTTP_PORT}")
    print(f"APP_URL: {APP_URL}")
    config = uvicorn.Config(app, host="0.0.0.0", port=HTTP_PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def run_telegram_bot() -> None:
    """Run the Telegram bot"""
    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN environment variable not set")
        return

    # Create and configure bot
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Add /rssfeed command handler
    application.add_handler(CommandHandler("rssfeed", handle_rssfeed_command))

    # Add message handler for new messages and edits
    application.add_handler(MessageHandler(filters.TEXT | filters.CAPTION, handle_message))

    print("Bot started. Listening for messages in all chats")
    print("Press Ctrl+C to stop")

    # Initialize and start bot
    await application.initialize()
    await application.start()

    if not application.updater:
        print("Error: Updater not initialized")
        return

    await application.updater.start_polling()


async def main() -> None:
    """Main function to run both servers concurrently"""
    # Initialize database
    init_database()

    print("Configuration:")
    print(f"  TELEGRAM_BOT_TOKEN: {'***' if TELEGRAM_TOKEN else 'Not Set'}")
    print(f"  HTTP_PORT: {HTTP_PORT}")
    print(f"  APP_URL: {APP_URL}")
    print(f"  DB_PATH: {DB_PATH}")

    try:
        # Run FastAPI and Telegram bot concurrently in the same event loop
        await asyncio.gather(
            run_fastapi_server(),
            run_telegram_bot(),
        )
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        if db_conn:
            db_conn.close()


if __name__ == "__main__":
    asyncio.run(main())
