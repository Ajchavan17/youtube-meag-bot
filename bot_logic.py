import os
import sys
import shutil  # <--- NEW: To copy files
import asyncio
import logging
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, List, Tuple
from concurrent.futures import ThreadPoolExecutor

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from yt_dlp import YoutubeDL
from mega import Mega


DOWNLOAD_DIR = "/tmp"  # Choreo safe folder
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ------------------------------------------------------------
# LOGGING SETUP
# ------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MEGA_EMAIL = os.getenv("MEGA_EMAIL")
MEGA_PASSWORD = os.getenv("MEGA_PASSWORD")
DOWNLOAD_DIR = "/tmp"


# ------------------------------------------------------------
# HEALTH CHECK SERVER
# ------------------------------------------------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass


def start_health_check_server():
    port = int(os.getenv("PORT", 8080))
    try:
        server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)

        def run_server():
            logger.info(f"✅ Health check server listening on port {port}")
            server.serve_forever()

        t = Thread(target=run_server, daemon=True)
        t.start()
        return True
    except Exception as e:
        logger.error(f"❌ Failed to start health check server: {e}")
        return False


executor = ThreadPoolExecutor(max_workers=4)
USER_SESSIONS: Dict[int, Dict] = {}


# ------------------------------------------------------------
# LOGIC
# ------------------------------------------------------------
def mega_login():
    mega = Mega()
    return mega.login(MEGA_EMAIL, MEGA_PASSWORD)


def build_folder_tree() -> List[Tuple[str, str]]:
    try:
        m = mega_login()
        files = m.get_files()
    except Exception as e:
        logger.exception("MEGA Error")
        return []

    folder_nodes = {nid: meta for nid, meta in files.items() if meta.get("t") == 1}
    folder_paths = []

    for nid, meta in folder_nodes.items():
        name = meta.get("a", {}).get("n")
        parent = meta.get("p")
        if not name: continue

        parts = [name]
        current_parent = parent
        while current_parent and current_parent in folder_nodes:
            pname = folder_nodes[current_parent].get("a", {}).get("n")
            if pname: parts.append(pname)
            current_parent = folder_nodes[current_parent].get("p")

        parts.reverse()
        folder_paths.append(("/".join(parts), nid))

    return sorted(list(set(folder_paths)), key=lambda x: x[0])


def download_mp3(url: str) -> str:
    source_cookies = "cookies.txt"
    writable_cookies = os.path.join(DOWNLOAD_DIR, "cookies.txt")

    cookie_arg = None

    # ----------------------------
    # SAFE BINARY COPY (Choreo fix)
    # ----------------------------
    if os.path.exists(source_cookies):
        try:
            with open(source_cookies, "rb") as src, open(writable_cookies, "wb") as dst:
                dst.write(src.read())
            cookie_arg = writable_cookies
            logger.info(f"Cookies copied (binary) to {writable_cookies}")
        except Exception as e:
            logger.error(f"Failed to binary-copy cookies: {e}")
    else:
        logger.warning("⚠️ cookies.txt not found! Download may be limited.")

    # ----------------------------
    # YTDLP OPTIONS (Safe for cloud)
    # ----------------------------
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
        "quiet": False,
        "noplaylist": True,
        "no_check_certificate": True,

        # COOKIE FIXES
        "cookiefile": cookie_arg,
        "no_write_cookies": True,   # IMPORTANT: prevents yt-dlp from corrupting cookies
        "ignoreerrors": True,

        # AUDIO CONVERSION
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192"
        }],
    }

    # ----------------------------
    # DOWNLOAD
    # ----------------------------
    with YoutubeDL(ydl_opts) as ydl:
        ydl.extract_info(url, download=True)

    # ----------------------------
    # FIND THE DOWNLOADED MP3
    # ----------------------------
    mp3_files = [
        os.path.join(DOWNLOAD_DIR, f)
        for f in os.listdir(DOWNLOAD_DIR)
        if f.lower().endswith(".mp3")
    ]

    if not mp3_files:
        raise RuntimeError("MP3 output not found after yt-dlp download.")

    mp3_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    return mp3_files[0]


# ------------------------------------------------------------
# HANDLERS
# ------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 *Welcome!*\nUse `/uploadtomega <URL>`", parse_mode="Markdown")


async def uploadtomega(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/uploadtomega <YouTube URL>`")
        return

    USER_SESSIONS[user.id] = {"url": context.args[0].strip()}
    msg = await update.message.reply_text("📂 Fetching MEGA folders... ⏳")

    loop = asyncio.get_event_loop()
    try:
        folders = await loop.run_in_executor(executor, build_folder_tree)
        if not folders:
            await msg.edit_text("⚠️ No MEGA folders found.")
            return

        USER_SESSIONS[user.id]["folders"] = folders
        keyboard = [[InlineKeyboardButton(f"📁 {path}", callback_data=f"choose|{user.id}|{nid}|{path}")] for path, nid in
                    folders]
        await msg.edit_text("📁 *Select Folder:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        _, uid, nodeid, folder_path = query.data.split("|")
        uid = int(uid)
    except:
        return

    sess = USER_SESSIONS.get(uid)
    if not sess:
        await query.edit_message_text("⚠️ Session expired.")
        return

    await query.edit_message_text("🎬 Downloading MP3... ⏳")
    loop = asyncio.get_event_loop()

    try:
        mp3_path = await loop.run_in_executor(executor, download_mp3, sess["url"])

        await query.edit_message_text(f"☁️ Uploading to `{folder_path}`... ⏳", parse_mode="Markdown")
        mega = mega_login()
        mega.upload(mp3_path, nodeid)

        await query.edit_message_text(f"✅ *Done!*\nFile: `{os.path.basename(mp3_path)}`", parse_mode="Markdown")

        if os.path.exists(mp3_path): os.remove(mp3_path)
    except Exception as e:
        logger.exception("Task Failed")
        await query.edit_message_text(f"❌ Failed: {e}")

    USER_SESSIONS.pop(uid, None)


# ------------------------------------------------------------
# RUN
# ------------------------------------------------------------
def main():
    start_health_check_server()

    if not TELEGRAM_BOT_TOKEN:
        logger.error("Bot token missing!")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("uploadtomega", uploadtomega))
    app.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("Bot is polling...")
    app.run_polling()


if __name__ == "__main__":
    main()