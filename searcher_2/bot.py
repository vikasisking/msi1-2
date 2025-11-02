import os
import re
import time
import random
import logging
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import requests
import shutil

from telegram import Update, File
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# --- Fix Windows asyncio event loop ---
if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# --- Load environment ---
load_dotenv()

# === Logging ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("AutoScanBot")

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "8564767791:AAHO_kiAmBenFW84c0sgGLkztBsUyiOQI_w")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8093935563"))
CHAT_ID = int(os.getenv("CHAT_ID", "-1003193018523"))
PRIVATE_LOG_CHAT_ID = int(os.getenv("PRIVATE_LOG_CHAT_ID", str(ADMIN_ID)))

DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "./files"))
DOWNLOAD_DIR.mkdir(exist_ok=True)
NOT_FOUND_DIR = DOWNLOAD_DIR / "not_found"
NOT_FOUND_DIR.mkdir(exist_ok=True)

# === PANEL CONFIG ===
LOGIN_URL = "http://51.83.103.80/ints/signin"
USERNAME = os.getenv("PANEL_USER", "Partner473vr")
PASSWORD = os.getenv("PANEL_PASS", "112233")
HEADERS = {"User-Agent": "Mozilla/5.0"}
AJAX_HEADERS = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}
session = requests.Session()

# --- Helpers ---
def clean_number(s: str) -> str:
    return re.sub(r"\D", "", s.strip())

def is_logged_in() -> bool:
    try:
        r = session.get("http://51.83.103.80/ints/agent/SMSCDRStats", headers=HEADERS, timeout=8)
        return "SMSCDRStats" in r.text
    except:
        return False

def login() -> bool:
    try:
        res = session.get("http://51.83.103.80/ints/login", headers=HEADERS)
        soup = BeautifulSoup(res.text, "html.parser")

        captcha_text = None
        for string in soup.stripped_strings:
            if "What is" in string and "+" in string:
                captcha_text = string.strip()
                break

        match = re.search(r"What is\s*(\d+)\s*\+\s*(\d+)", captcha_text or "")
        if not match:
            print("❌ Captcha not found.")
            return False

        a, b = int(match.group(1)), int(match.group(2))
        captcha_answer = str(a + b)

        payload = {"username": USERNAME, "password": PASSWORD, "capt": captcha_answer}
        res = session.post(LOGIN_URL, data=payload, headers=HEADERS)
        if "SMSCDRStats" not in res.text and "MySMSNumbers" not in res.text:
            print("❌ Login failed.")
            return False

        print("✅ Logged in successfully.")
        return True
    except Exception as e:
        print(f"Login error: {e}")
        return False

def search_number_on_site(number: str, timeout: int = 10) -> bool:
    try:
        if not is_logged_in():
            if not login():
                return False

        params = {
            "sEcho": 1,
            "iColumns": 8,
            "sColumns": ",,,,,,,",
            "iDisplayStart": 0,
            "iDisplayLength": 100,
            "sSearch": number,
            "bRegex": "false",
        }

        r = session.get("http://51.83.103.80/ints/agent/res/data_smsnumbers.php",
                        headers=AJAX_HEADERS, params=params, timeout=timeout)
        text = r.text.strip()

        import json
        try:
            data = json.loads(text)
        except Exception:
            return number in re.sub(r"\D", "", text)

        total = int(data.get("iTotalRecords", 0))
        if total == 0:
            return False

        for row in data.get("aaData", []):
            if isinstance(row, (list, tuple)):
                for cell in row:
                    if isinstance(cell, str) and number in re.sub(r"\D", "", cell):
                        return True
        return False
    except Exception as e:
        print(f"Search error: {e}")
        return False

# === Number extract ===
def extract_numbers(text: str):
    return [clean_number(x) for x in re.findall(r"\d{6,20}", text)]

def pick_random_number_from_file(path: Path):
    try:
        txt = path.read_text(encoding="utf-8", errors="ignore")
        nums = extract_numbers(txt)
        if not nums:
            return None
        return random.choice(nums)
    except:
        return None

def extract_file_id(filename: str) -> str:
    name = Path(filename).stem
    m = re.search(r"([A-Za-z]{2}-\d{3,6})", name)
    if m:
        return m.group(1).upper()

    m2 = re.search(r"_([A-Za-z]{2})[-_]?(\d{3,6})", name)
    if m2:
        return f"{m2.group(1).upper()}-{m2.group(2)}"

    if "_" in name:
        country = name.split("_", 1)[0]
    else:
        country = name.split()[0] if name.split() else "XX"

    letters = re.sub(r"[^A-Za-z]", "", country)[:2].upper()
    letters = (letters + "XX")[:2]
    rand_digits = f"{random.randint(0, 9999):04d}"
    return f"{letters}-{rand_digits}"

# === Core scanning ===
async def scan_file(file_path: Path, bot, source_chat_id: int = None):
    # ⛔ Safety guard: skip not_found files
    if str(file_path).startswith(str(NOT_FOUND_DIR)):
        print(f"⛔ Skipping not_found file: {file_path.name}")
        return

    number = pick_random_number_from_file(file_path)
    if not number:
        msg = f"⚠️ No valid number in {file_path.name}"
        await bot.send_message(chat_id=ADMIN_ID, text=msg)
        return

    loop = asyncio.get_event_loop()
    found = await loop.run_in_executor(None, search_number_on_site, number)
    result = "✅ Found" if found else "❌ Not Found"
    text = f"{result}: {number}\nFile: {file_path.name}"
    print(text)
    await bot.send_message(chat_id=ADMIN_ID, text=text)

    if not found:
        try:
            file_id = extract_file_id(file_path.name)
            await bot.send_message(chat_id=PRIVATE_LOG_CHAT_ID, text=file_id)
            if source_chat_id and source_chat_id != PRIVATE_LOG_CHAT_ID:
                await bot.send_message(chat_id=source_chat_id, text=file_id)
            dest_path = NOT_FOUND_DIR / file_path.name
            shutil.move(str(file_path), str(dest_path))
            print(f"📁 Moved not found file to: {dest_path}")
        except Exception as e:
            print(f"⚠️ Failed to move not found file: {e}")

async def scan_all_files(bot):
    files = sorted(DOWNLOAD_DIR.glob("*.txt"))
    if not files:
        print("No .txt files found to scan.")
        return
    await bot.send_message(chat_id=ADMIN_ID, text=f"🔍 Scanning {len(files)} files...")
    for f in files:
        if f.parent == NOT_FOUND_DIR:
            continue
        await scan_file(f, bot, source_chat_id=None)
        await asyncio.sleep(1)

# === Cleanup and Hourly Scan Tasks ===
async def daily_cleanup(bot):
    while True:
        now = datetime.now()
        target = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        wait_time = (target - now).total_seconds()
        print(f"🕘 Next cleanup scheduled at {target}")
        await asyncio.sleep(wait_time)
        deleted = 0
        for txt_file in NOT_FOUND_DIR.glob("*.txt"):
            try:
                txt_file.unlink()
                deleted += 1
            except Exception as e:
                print(f"❌ Error deleting {txt_file.name}: {e}")
        msg = f"🧹 Cleanup done. Deleted {deleted} files."
        await bot.send_message(chat_id=ADMIN_ID, text=msg)

async def auto_hourly_scan(bot):
    while True:
        print("⏱ Running hourly rescan...")
        await scan_all_files(bot)
        await bot.send_message(chat_id=ADMIN_ID, text="⏱ Hourly scan completed ✅")
        await asyncio.sleep(3600)

# === Handlers ===
async def handle_new_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith(".txt"):
        return
    local_path = DOWNLOAD_DIR / f"{int(time.time())}_{doc.file_name}"
    new_file: File = await context.bot.get_file(doc.file_id)
    await new_file.download_to_drive(str(local_path))
    print(f"📁 File downloaded: {local_path}")
    await scan_file(local_path, context.bot, source_chat_id=update.effective_chat.id)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot running and monitoring group for .txt files.")

async def rescan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("❌ Only admin can use this.")
    await scan_all_files(context.bot)

# === Main ===
def main():
    print("🤖 Bot initializing...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("rescan", rescan_cmd))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_new_file))

    async def on_startup(app):
        print("🔄 Logging in to panel...")
        await asyncio.get_event_loop().run_in_executor(None, login)
        print("✅ Startup scan starting...")
        await scan_all_files(app.bot)
        asyncio.create_task(daily_cleanup(app.bot))
        asyncio.create_task(auto_hourly_scan(app.bot))
        print("🟢 Ready & polling Telegram...")

    app.post_init = on_startup
    print("🚀 Running polling loop...")
    app.run_polling(close_loop=False, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
