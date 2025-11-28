import os
import shutil
import logging
from flask import Flask, request

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from yt_dlp import YoutubeDL
from mega import Mega
from config import TELEGRAM_BOT_TOKEN, MEGA_EMAIL, MEGA_PASSWORD, DOWNLOAD_DIR

# ----------------------------
# LOGGING
# ----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ----------------------------
# FLASK APP (Webhook Host)
# ----------------------------
app = Flask(__name__)

# ----------------------------
# TELEGRAM + WEBHOOK SETUP
# ----------------------------
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Provided by Choreo deployment

telegram_app = (
    Application.builder()
    .token(TELEGRAM_BOT_TOKEN)
    .concurrent_updates(True)
    .build()
)


# ----------------------------
# YOUTUBE → MP3 Downloader (Webhook Safe)
# ----------------------------
def download_mp3(url: str) -> str:
    source_cookies = "cookies.txt"
    writable_cookies = os.path.join(DOWNLOAD_DIR, "cookies.txt")

    cookie_arg = None

    # COPY COOKIES SAFELY (binary mode)
    if os.path.exists(source_cookies):
        try:
            with open(source_cookies, "rb") as src, open(writable_cookies, "wb") as dst:
                dst.write(src.read())
            cookie_arg = writable_cookies
            logger.info(f"Cookies copied (binary) to {writable_cookies}")
        except Exception as e:
            logger.error(f"Error binary copying cookies: {e}")
    else:
        logger.warning("cookies.txt not found — download may be restricted.")

    # yt-dlp options
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
        "quiet": False,
        "noplaylist": True,
        "ignoreerrors": True,

        "cookiefile": cookie_arg,
        "no_write_cookies": True,
        "no_check_certificate": True,

        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }

    # Download
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    # Find MP3
    mp3_files = [
        os.path.join(DOWNLOAD_DIR, f)
        for f in os.listdir(DOWNLOAD_DIR)
        if f.lower().endswith(".mp3")
    ]

    if not mp3_files:
        raise RuntimeError("MP3 file not found after download")

    mp3_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    return mp3_files[0]


# ----------------------------
# MEGA UPLOAD
# ----------------------------
def upload_to_mega(filepath):
    mega = Mega()
    m = mega.login(MEGA_EMAIL, MEGA_PASSWORD)
    uploaded = m.upload(filepath)
    link = m.get_upload_link(uploaded)
    return link


# ----------------------------
# TELEGRAM HANDLERS
# ----------------------------
async def start(update, context):
    await update.message.reply_text("Send me a YouTube link to convert → upload to MEGA.")


async def handle_message(update, context):
    url = update.message.text.strip()

    if "youtube.com" not in url and "youtu.be" not in url:
        await update.message.reply_text("Send a valid YouTube link.")
        return

    await update.message.reply_text("🔄 Downloading MP3…")

    try:
        mp3_path = download_mp3(url)
        await update.message.reply_text("📤 Uploading to MEGA…")

        mega_link = upload_to_mega(mp3_path)

        await update.message.reply_text(f"✅ Uploaded!\n\n🔗 {mega_link}")

    except Exception as e:
        logger.error(f"ERROR: {e}")
        await update.message.reply_text(f"❌ Failed: {e}")


# Register handlers
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


# ----------------------------
# WEBHOOK ENDPOINT (Telegram → Our Service)
# ----------------------------
@app.post("/webhook")
def webhook():
    try:
        update = request.get_json(force=True)
        telegram_app.update_queue.put_nowait(update)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
    return "OK", 200


# Health check (Choreo requires this)
@app.get("/")
def home():
    return "Bot running via webhook", 200


# ----------------------------
# ENTRY POINT
# ----------------------------
if __name__ == "__main__":
    # Ensure temp directory exists
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    # Start Telegram async core
    telegram_app.initialize()
    telegram_app.start()

    # Start Flask server (Choreo exposes this)
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
