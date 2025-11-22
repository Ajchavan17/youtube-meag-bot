import os
import re
import asyncio
import logging
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

from config import TELEGRAM_BOT_TOKEN, MEGA_EMAIL, MEGA_PASSWORD, DOWNLOAD_DIR


# ------------------------------------------------------------
# Logging Setup
# ------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

executor = ThreadPoolExecutor(max_workers=4)

USER_SESSIONS: Dict[int, Dict] = {}


# ------------------------------------------------------------
# MEGA LOGIN
# ------------------------------------------------------------

def mega_login():
    mega = Mega()
    return mega.login(MEGA_EMAIL, MEGA_PASSWORD)


# ------------------------------------------------------------
# MEGA FOLDER TREE — FULL & ACCURATE
# ------------------------------------------------------------

def build_folder_tree() -> List[Tuple[str, str]]:
    """
    Returns list of (full_path, node_id)
    Example:
        ("Music", "HKFDSf3")
        ("Music/Bollywood", "FDSF323")
    """

    try:
        m = mega_login()
    except Exception as e:
        logger.exception("MEGA login failed")
        return []

    try:
        files = m.get_files()
    except Exception as e:
        logger.exception("m.get_files() failed")
        return []

    # Extract only folders (t == 1)
    folder_nodes = {
        nid: meta
        for nid, meta in files.items()
        if meta.get("t") == 1
    }

    folder_paths = []

    for nid, meta in folder_nodes.items():
        name = meta.get("a", {}).get("n")
        parent = meta.get("p")

        if not name:
            continue

        # Build full folder path
        parts = [name]
        current_parent = parent

        while current_parent and current_parent in folder_nodes:
            pname = folder_nodes[current_parent].get("a", {}).get("n")
            if pname:
                parts.append(pname)
            current_parent = folder_nodes[current_parent].get("p")

        parts.reverse()
        full_path = "/".join(parts)
        folder_paths.append((full_path, nid))

    # Remove duplicates + sort
    folder_paths = sorted(list(set(folder_paths)), key=lambda x: x[0])

    return folder_paths


# ------------------------------------------------------------
# FIXED — RELIABLE MP3 OUTPUT DETECTION
# ------------------------------------------------------------

def download_mp3(url: str) -> str:
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
        "quiet": False,
        "noplaylist": True,
        "no_check_certificate": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }

    with YoutubeDL(ydl_opts) as ydl:
        ydl.extract_info(url, download=True)

    # RETURN NEWEST MP3 FILE (most reliable method)
    mp3_files = [
        os.path.join(DOWNLOAD_DIR, f)
        for f in os.listdir(DOWNLOAD_DIR)
        if f.lower().endswith(".mp3")
    ]

    if not mp3_files:
        raise RuntimeError("MP3 output not found.")

    mp3_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    return mp3_files[0]


# ------------------------------------------------------------
# Telegram: /start
# ------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Welcome!*\n\n"
        "Use `/uploadtomega <YouTube URL>` to download MP3 and upload to MEGA.",
        parse_mode="Markdown"
    )


# ------------------------------------------------------------
# Telegram: /uploadtomega
# ------------------------------------------------------------

async def uploadtomega(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id

    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/uploadtomega <YouTube URL>`", parse_mode="Markdown")
        return

    yt_url = context.args[0].strip()
    USER_SESSIONS[uid] = {"url": yt_url}

    msg = await update.message.reply_text("📂 Fetching MEGA folders... ⏳")

    loop = asyncio.get_event_loop()

    try:
        folders = await loop.run_in_executor(executor, build_folder_tree)

        if not folders:
            await msg.edit_text("⚠️ No folders found in MEGA account.")
            return

        USER_SESSIONS[uid]["folders"] = folders

        keyboard = []
        for path, nid in folders:
            keyboard.append([
                InlineKeyboardButton(
                    f"📁 {path}",
                    callback_data=f"choose|{uid}|{nid}|{path}"
                )
            ])

        await msg.edit_text(
            "📁 *Select MEGA Folder:*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ Error fetching MEGA folders:\n`{e}`", parse_mode="Markdown")


# ------------------------------------------------------------
# Telegram: Callback Handler
# ------------------------------------------------------------

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        action, uid, nodeid, folder_path = query.data.split("|")
        uid = int(uid)
    except ValueError:
        await query.edit_message_text("⚠️ Invalid selection data.")
        return

    sess = USER_SESSIONS.get(uid)
    if not sess:
        await query.edit_message_text("⚠️ Session expired. Run /uploadtomega again.")
        return

    yt_url = sess["url"]

    await query.edit_message_text("🎬 Downloading MP3... ⏳")

    loop = asyncio.get_event_loop()

    try:
        mp3_path = await loop.run_in_executor(executor, download_mp3, yt_url)
    except Exception as e:
        await query.edit_message_text(f"❌ YouTube download failed:\n`{e}`", parse_mode="Markdown")
        return

    await query.edit_message_text(f"☁️ Uploading to MEGA folder: `{folder_path}`... ⏳", parse_mode="Markdown")

    try:
        mega = mega_login()
        mega.upload(mp3_path, nodeid)

        await query.edit_message_text(
            f"✅ *Upload Complete!*\n\n"
            f"📄 File: `{os.path.basename(mp3_path)}`\n"
            f"📁 Folder: `{folder_path}`",
            parse_mode="Markdown"
        )

        # Delete local MP3 file
        os.remove(mp3_path)

    except Exception as e:
        logger.exception(e)
        await query.edit_message_text(f"❌ Upload failed:\n`{e}`", parse_mode="Markdown")

    USER_SESSIONS.pop(uid, None)


# ------------------------------------------------------------
# Run Bot
# ------------------------------------------------------------

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("uploadtomega", uploadtomega))
    app.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
