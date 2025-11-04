import os
import re
import time
import json
import random
import logging
import threading
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import sqlite3
import pycountry

try:
    import telebot
    from telebot import types
except Exception:
    raise SystemExit("telebot (pyTelegramBotAPI) required. pip install pytelegrambotapi")

# ---------- Config ----------
LOG_FORMAT = "%(asctime)s %(levelname)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("h2i_v2")

BOT_TOKEN = os.getenv("BOT_TOKEN", "8512258086:AAHbUwCMEOJbk4H3F4XZ2jbm3G94yrgZHtc")
BOT = telebot.TeleBot(BOT_TOKEN)

LOGIN_URL = "http://51.83.103.80/ints/signin"
LOGIN_PAGE = "http://51.83.103.80/ints/login"
USERNAME = os.getenv("PANEL_USER", "h2ideveloper898")
PASSWORD = os.getenv("PANEL_PASS", "112233")
ADMIN_ID = 8093935563
DEST_GROUP = os.getenv("DEST_GROUP", "-1002922952640")
try:
    DEST_GROUP_ID = int(DEST_GROUP)
except Exception:

    DEST_GROUP_ID = DEST_GROUP 
TOPIC_ID = int(os.getenv("TOPIC_ID", "5")) 
topicgroup = os.getenv("topicgroup", "https://t.me/+zLzE9PdovjhjYzFl")
CODE_GROUP = os.getenv("CODE_GROUP", os.getenv("CHANNEL_LINK", "https://t.me/+RLHEkgCBOe8xOWM1"))
PUBLIC_CHANNEL = "@freeotpss"
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "120"))
NUMBERS_DIR = "numbers"
os.makedirs(NUMBERS_DIR, exist_ok=True)
STATE_FILE = "v2_state.json"
PRIVATE_GROUP_ID = -1003297357915
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": LOGIN_PAGE}
AJAX_HEADERS = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest", "Referer": "http://51.83.103.80/ints/agent/SMSCDRStats"}

session = requests.Session()

# ---------- Utilities ----------
EXTRA_CODES = {"Kosovo": "XK"}

def country_to_flag(country_name: str) -> str:
    if not country_name:
        return ""
    country_name = re.sub(r"[^A-Za-z\s]", "", country_name).strip()
    code = EXTRA_CODES.get(country_name)
    if not code:
        try:
            country = pycountry.countries.lookup(country_name)
            code = country.alpha_2
        except Exception:
            code = (country_name[:2] if country_name else "XX").upper()
    return "".join(chr(127397 + ord(c)) for c in code.upper())

def sanitize_fname(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]", "_", s.strip())

def rand_file_code(country: str) -> str:
    prefix = re.sub(r"[^A-Za-z]", "", country)[:2].upper() or "XX"
    digits = f"{random.randint(0,9999):04d}"
    return f"{prefix}-{digits}"

def now_str():
    return datetime.now().strftime("%d %b %Y %H:%M:%S")

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to load state: %s", e)
        return {}

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error("Failed to save state: %s", e)

# ---------- Panel login + fetch helpers (lightly adapted from v1) ----------
def login(retries=3, delay=3):
    for attempt in range(1, retries+1):
        try:
            res = session.get(LOGIN_PAGE, headers=HEADERS, timeout=20)
        except Exception as e:
            logger.warning("Login page fetch failed (try %s): %s", attempt, e)
            time.sleep(delay)
            continue

        soup = BeautifulSoup(res.text or "", "html.parser")
        captcha_text = None
        for string in soup.stripped_strings:
            if "What is" in string and "+" in string:
                captcha_text = string.strip()
                break
        if not captcha_text:
            logger.warning("Captcha not found (try %s).", attempt)
            time.sleep(delay)
            continue

        m = re.search(r"What is\s*(\d+)\s*\+\s*(\d+)", captcha_text)
        if not m:
            logger.warning("Could not parse captcha text: %s", captcha_text)
            time.sleep(delay)
            continue

        a, b = int(m.group(1)), int(m.group(2))
        answer = str(a + b)
        payload = {"username": USERNAME, "password": PASSWORD, "capt": answer}
        try:
            r = session.post(LOGIN_URL, data=payload, headers=HEADERS, timeout=20, allow_redirects=True)
            if "SMSCDRStats" in (r.text or "") or "MySMSNumbers" in (r.text or ""):
                logger.info("Logged in to panel.")
                return True
            # fallback check
            test = session.get("http://51.83.103.80/ints/agent/MySMSNumbers", headers=HEADERS, timeout=10)
            if "SMSCDRStats" in (test.text or "") or "MySMSNumbers" in (test.text or ""):
                logger.info("Logged in (follow-up).")
                return True
        except Exception as e:
            logger.warning("Login attempt failed: %s", e)
            time.sleep(delay)
            continue
    logger.error("All login attempts failed.")
    return False

def fetch_country_ranges_from_panel(max_pages=5, retries=3):
    """
    Fetch list of all active country ranges from panel.
    Auto-retries on RemoteDisconnected / Connection aborted errors.
    """
    url = "http://51.83.103.80/ints/agent/res/aj_smsranges.php"
    found = {}

    for attempt in range(1, retries + 1):
        try:
            for page in range(1, max_pages + 1):
                params = {"q": "", "max": 25, "page": page}
                r = session.get(url, headers=AJAX_HEADERS, params=params, timeout=20)
                try:
                    data = r.json()
                except Exception:
                    logger.warning(f"⚠️ Non-JSON response on page {page}, skipping.")
                    break

                for item in data.get("results", []):
                    raw_title = item.get("title", "").strip()
                    range_id = item.get("id")
                    if not raw_title or not range_id:
                        continue

                    clean_name = clean_country_name(raw_title)
                    if not clean_name or len(clean_name) < 2:
                        continue

                    found[clean_name] = {"range": range_id}

                if not data.get("pagination", {}).get("more"):
                    break

            # Add number counts
            for country, meta in list(found.items()):
                rid = meta.get("range")
                try:
                    num_url = "http://51.83.103.80/ints/agent/res/data_smsnumbers.php"
                    params = {"frange": rid, "fclient": "", "iDisplayLength": 1, "sEcho": 1}
                    res = session.get(num_url, headers=AJAX_HEADERS, params=params, timeout=10)
                    j = res.json()
                    meta["count"] = int(j.get("iTotalRecords", 0))
                    meta["flag"] = country_to_flag(country)
                except Exception:
                    meta["count"] = 0
                    meta["flag"] = country_to_flag(country)

            return found

        except requests.exceptions.ConnectionError as e:
            logger.warning(f"⚠️ Connection error on attempt {attempt}: {e}")
        except requests.exceptions.ChunkedEncodingError as e:
            logger.warning(f"⚠️ ChunkedEncodingError: {e}")
        except requests.exceptions.ReadTimeout:
            logger.warning(f"⚠️ Read timeout on attempt {attempt}")
        except requests.exceptions.RequestException as e:
            if "Remote end closed connection" in str(e):
                logger.warning(f"⚠️ RemoteDisconnected — retrying ({attempt}/{retries})...")
            else:
                logger.error(f"❌ Panel request failed: {e}")
        except Exception as e:
            logger.error(f"❌ Unexpected fetch error: {e}")

        # 🔁 Wait before retry
        time.sleep(5)

    # If all attempts failed
    logger.error("❌ All attempts to fetch country ranges failed after retries.")
    return {}

def fetch_numbers_from_panel(range_id):
    url = "http://51.83.103.80/ints/agent/res/data_smsnumbers.php"
    params = {
        "frange": range_id,
        "fclient": "",
        "sEcho": random.randint(1,9),
        "iColumns": 8,
        "sColumns": ",,,,,,,",
        "iDisplayStart": 0,
        "iDisplayLength": -1,
        "sSearch": "",
        "_": str(int(time.time()*1000))
    }
    headers = {**AJAX_HEADERS, "Referer": "http://51.83.103.80/ints/agent/MySMSNumbers"}
    try:
        r = session.get(url, headers=headers, params=params, timeout=20)
        txt = r.text or ""
        if txt.strip().startswith("<"):
            logger.warning("Panel returned HTML; cannot parse numbers.")
            return []
        data = r.json()
        rows = data.get("aaData", [])
        numbers = []
        for row in rows:
            if isinstance(row, list) and len(row) > 3:
                n = str(row[3]).strip()
                if n:
                    numbers.append(n.lstrip("+").strip())
        uniq = list(dict.fromkeys(numbers))
        return uniq
    except Exception as e:
        logger.error("Error fetching numbers for range %s: %s", range_id, e)
        return []

# Clean country name helper (from v1)
def clean_country_name(raw_name: str) -> str:
    if not raw_name:
        return "Unknown"
    name = str(raw_name).strip()
    name = re.sub(r"[\u200b\u200c\u200d\uFEFF\xa0]", " ", name)
    name = re.sub(r"[\(\[].*?[\)\]]", "", name)
    name = re.sub(
        r"[\|\-–_]+(New|Cn|Mobitel|Claro|Orange|Max|Range|Chinguitel|Telkom|D\d*|E\d*|Pn\d*|[A-Za-z]{1,4}\d*)\b.*",
        "",
        name,
        flags=re.IGNORECASE
    )
    name = re.sub(r"\d+", "", name)
    name = re.sub(r"[^A-Za-z\s]", " ", name)
    name = re.sub(r"\s+", " ", name)
    name = name.strip().title()
    mapping = {
        "Usa": "United States",
        "Uk": "United Kingdom",
        "Ksa": "Saudi Arabia",
        "Venezula": "Venezuela"
    }
    return mapping.get(name, name)

# ---------- File / send helpers ----------
def country_state_key(country):
    return country.replace(" ", "_").lower()

def ensure_country_file_and_state(state, country):
    """
    Ensure there is a tracked file entry for this country.
    Reuse same file_code for filename + caption.
    """
    key_prefix = country_state_key(country)

    # Reuse if already exists
    for k, v in state.items():
        if v.get("country") == country:
            return v

    # Create new entry only once
    file_code = rand_file_code(country)
    key = f"{key_prefix}_{file_code}"
    fname = f"{sanitize_fname(country)}_{file_code}.txt"
    fpath = os.path.join(NUMBERS_DIR, fname)

    state[key] = {
        "country": country,
        "file_code": file_code,   # 👈 keep same everywhere
        "filename": fname,
        "filepath": fpath,
        "last_sent_msg_id": None,
        "private_msg_id": None,
        "last_sent_telegram_file_id": None,
        "last_sent_time": None,
        "numbers": [],
        "is_disconnected": False
    }

    save_state(state)
    return state[key]

def write_country_file(fpath, country, numbers):
    try:
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(f"# {country} — live numbers (generated {now_str()})\n")
            for n in numbers:
                f.write(f"{n}\n")
    except Exception as e:
        logger.error("Failed to write file %s: %s", fpath, e)

def build_caption(country, file_code, total, code_group_link, status):
    flag = country_to_flag(country)
    color_icon = "🟢" if "✅" in status else "🔴"
    version = "v0.4.0"
    now = datetime.now().strftime('%d %b %Y')

    # Use Markdown link format for clickable "CLICK HERE"
    caption = (
        f"{color_icon} {flag} {country} | WhatsApp\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📦 TOTAL :: {total} Numbers\n"
        f"🧾 FILE ID :: {file_code}\n"
        f"🔗 CODE  :: [CLICK HERE]({code_group_link})\n\n"
        f"⚙️ STATUS:: {status}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💻 H2I Bot v{version} | {now}"
    )

    return caption

def send_file_to_group(state_entry):
    """
    Send generated file to both Topic Group and Private Group.
    Uses SAME file_code as in filename & caption.
    """
    country = state_entry["country"]
    fpath = state_entry["filepath"]
    file_code = state_entry["file_code"]  # 👈 No new random code here

    # Caption always ACTIVE on send
    caption = build_caption(
        country,
        file_code,
        len(state_entry.get("numbers", [])),
        CODE_GROUP,
        "✅ ACTIVE"
    )

    sent_success = False

    try:
        with open(fpath, "rb") as doc:
            # 🧩 1️⃣ Send to Topic Group (with or without topic thread)
            if "TOPIC_ID" in globals() and TOPIC_ID:
                msg_topic = BOT.send_document(
                    chat_id=DEST_GROUP_ID,
                    document=doc,
                    caption=caption,
                    parse_mode="Markdown",
                    message_thread_id=TOPIC_ID
                )
            else:
                msg_topic = BOT.send_document(
                    chat_id=DEST_GROUP_ID,
                    document=doc,
                    caption=caption,
                    parse_mode="Markdown"
                )

            # Save topic group message info
            state_entry["last_sent_msg_id"] = msg_topic.message_id
            state_entry["last_sent_telegram_file_id"] = (
                msg_topic.document.file_id if msg_topic.document else None
            )
            state_entry["last_sent_time"] = int(time.time())

            logger.info(f"✅ Sent file for {country} → Topic Group (msg_id={msg_topic.message_id})")
            sent_success = True

        # 🧩 2️⃣ Send to Private Group (if enabled)
        if PRIVATE_GROUP_ID:
            try:
                with open(fpath, "rb") as doc2:
                    msg_priv = BOT.send_document(
                        chat_id=int(PRIVATE_GROUP_ID),
                        document=doc2,
                        caption=caption,
                        parse_mode="Markdown"
                    )
                    # Save private message ID for later editing
                    state_entry["private_msg_id"] = msg_priv.message_id
                    logger.info(f"📤 Sent file for {country} → Private Group (msg_id={msg_priv.message_id})")
            except Exception as e:
                logger.warning(f"⚠️ Failed to send to private group for {country}: {e}")

        # 🧩 3️⃣ Announce in Public Channel
        try:
            flag = country_to_flag(country)
            BOT.send_message(
                chat_id=PUBLIC_CHANNEL,
                text=f"{flag} {country} uploaded ✅\n\n{topicgroup}",
                disable_web_page_preview=True
            )
            logger.info(f"📢 Announced upload for {country} in public channel.")
        except Exception as e:
            logger.warning(f"⚠️ Failed to send public notice for {country}: {e}")

        # Save updated state with both message IDs
        save_state(load_state() | {country_state_key(country): state_entry})

    except Exception as e:
        logger.error(f"❌ Failed to send file for {country}: {e}")
        alert_admin_message(f"❌ File send failed for {country}: {e}")
        sent_success = False

    return sent_success

def edit_caption_in_group(entry, new_status=None):
    country = entry["country"]
    file_code = entry["file_code"]
    total = len(entry.get("numbers", []))
    status = new_status or ("✅ ACTIVE" if total > 0 else "❌ DISCONNECTED")
    caption = build_caption(country, file_code, total, CODE_GROUP, status)

    edited_any = False

    # --- Topic group edit or resend ---
    try:
        if entry.get("last_sent_msg_id"):
            BOT.edit_message_caption(
                chat_id=DEST_GROUP_ID,
                message_id=entry["last_sent_msg_id"],
                caption=caption,
                parse_mode="Markdown"
            )
            logger.info(f"✏️ Topic group caption updated for {country}")
            edited_any = True
        else:
            with open(entry["filepath"], "rb") as doc:
                msg = BOT.send_document(
                    chat_id=DEST_GROUP_ID,
                    document=doc,
                    caption=caption,
                    parse_mode="Markdown",
                    message_thread_id=TOPIC_ID if TOPIC_ID else None
                )
                entry["last_sent_msg_id"] = msg.message_id
                logger.info(f"📥 Re-sent file to topic group for {country}")
                edited_any = True
    except Exception as e:
        logger.warning(f"⚠️ Topic edit/send failed for {country}: {e}")

    # --- Private group edit or resend ---
    try:
        if entry.get("private_msg_id"):
            BOT.edit_message_caption(
                chat_id=int(PRIVATE_GROUP_ID),
                message_id=entry["private_msg_id"],
                caption=caption,
                parse_mode="Markdown"
            )
            logger.info(f"✏️ Private group caption updated for {country}")
            edited_any = True
        else:
            with open(entry["filepath"], "rb") as doc:
                msg = BOT.send_document(
                    chat_id=int(PRIVATE_GROUP_ID),
                    document=doc,
                    caption=caption,
                    parse_mode="Markdown"
                )
                entry["private_msg_id"] = msg.message_id
                logger.info(f"📥 Re-sent file to private group for {country}")
                edited_any = True
    except Exception as e:
        logger.warning(f"⚠️ Private edit/send failed for {country}: {e}")

    save_state(load_state() | {country_state_key(country): entry})
    return edited_any

def alert_admin_message(msg):
    """Send direct alert message to admin."""
    try:
        BOT.send_message(ADMIN_ID, msg)
        logger.info(f"📨 Admin alerted: {msg}")
    except Exception as e:
        logger.warning(f"⚠️ Failed to alert admin: {e}")

# ----------------------------
# 🧠 Sent Numbers Memory
# ----------------------------
SENT_FILE = "sent_numbers.json"

def load_sent_numbers():
    if not os.path.exists(SENT_FILE):
        return set()
    try:
        with open(SENT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data)
    except Exception as e:
        logger.error(f"Failed to load sent numbers: {e}")
        return set()

def save_sent_numbers(numbers):
    try:
        with open(SENT_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(list(numbers)), f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save sent numbers: {e}")

# ================================
# 🧠 SQLite Number Storage Helpers
# ================================
def init_country_db(country):
    db_dir = os.path.join(NUMBERS_DIR, "db")
    os.makedirs(db_dir, exist_ok=True)
    db_path = os.path.join(db_dir, f"{sanitize_fname(country)}.db")

    conn = sqlite3.connect(db_path, timeout=30)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS numbers (num TEXT PRIMARY KEY, added_at INTEGER)")
    conn.commit()
    conn.close()
    return db_path

def db_get_all_numbers(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    cur = conn.cursor()
    try:
        cur.execute("SELECT num FROM numbers")
        rows = cur.fetchall()
        return [r[0] for r in rows]
    except Exception as e:
        logger.error(f"db_get_all_numbers error {db_path}: {e}")
        return []
    finally:
        conn.close()

def db_add_numbers(db_path, numbers):
    if not numbers:
        return
    conn = sqlite3.connect(db_path, timeout=30)
    cur = conn.cursor()
    now_ts = int(time.time())
    try:
        cur.executemany(
            "INSERT OR IGNORE INTO numbers (num, added_at) VALUES (?, ?)",
            ((n, now_ts) for n in numbers)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"db_add_numbers error {db_path}: {e}")
    finally:
        conn.close()

def db_remove_numbers(db_path, numbers):
    if not numbers:
        return
    conn = sqlite3.connect(db_path, timeout=30)
    cur = conn.cursor()
    try:
        cur.executemany("DELETE FROM numbers WHERE num = ?", ((n,) for n in numbers))
        conn.commit()
    except Exception as e:
        logger.error(f"db_remove_numbers error {db_path}: {e}")
    finally:
        conn.close()

def db_export_to_txt(db_path, out_path, country):
    nums = db_get_all_numbers(db_path)
    try:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# {country} — exported {now_str()}\n")
            for n in nums:
                f.write(n + "\n")
    except Exception as e:
        logger.error(f"db_export_to_txt error for {out_path}: {e}")


def sqlite_diff_and_update_strict(entry, live_norm, sent_numbers):
    """
    STRONG MODE:
    Disconnect file if even ONE number from this file is missing in live panel data.
    Supports multiple files per same country.
    """
    country = entry["country"]
    db_path = init_country_db(country)

    # Read DB stored numbers (per file scope)
    prev_numbers = set(db_get_all_numbers(db_path))
    live_set = set(live_norm)

    # Compare strictly
    missing_numbers = [n for n in prev_numbers if n not in live_set]

    result = {
        "country": country,
        "db_path": db_path,
        "removed": missing_numbers,
        "disconnected": False
    }

    # If even ONE number missing → mark file as disconnected
    if missing_numbers:
        entry["is_disconnected"] = True
        result["disconnected"] = True
        logger.warning(
            f"⚠️ STRICT DISCONNECT: {country} ({entry['file_code']}) — {len(missing_numbers)} missing from panel"
        )
        return result

    # If all present — still active
    entry["is_disconnected"] = False
    result["disconnected"] = False
    return result

def cleanup_old_disconnected(state, days=7):
    now = time.time()
    cutoff = days * 86400
    removed = []
    for key, entry in list(state.items()):
        if entry.get("is_disconnected", False):
            fpath = entry.get("filepath")
            if os.path.exists(fpath):
                mtime = os.path.getmtime(fpath)
                if now - mtime > cutoff:
                    try:
                        os.remove(fpath)
                        db_path = os.path.join(NUMBERS_DIR, "db", f"{sanitize_fname(entry['country'])}.db")
                        if os.path.exists(db_path):
                            os.remove(db_path)
                        removed.append(entry['country'])
                        del state[key]
                        logger.info(f"🧹 Cleaned up old disconnected country: {entry['country']}")
                    except Exception as e:
                        logger.warning(f"⚠️ Cleanup failed for {entry['country']}: {e}")
    if removed:
        save_state(state)
        alert_admin_message(f"🧹 Auto-cleanup done for: {', '.join(removed)}")

def ensure_login():
    while True:
        try:
            if not login():
                logger.warning("🔄 Relogin attempt failed, retrying in 2 min...")
                time.sleep(120)
            else:
                logger.info("✅ Panel session refreshed successfully.")
                time.sleep(600)  # refresh every 10 min
        except Exception as e:
            logger.error(f"ensure_login error: {e}")
            time.sleep(180)

# ========== 🔧 MANUAL DISCONNECT COMMAND ==========

@BOT.message_handler(commands=["disconnect"])
def manual_disconnect(message):
    """Admin command: /disconnect FILE_ID"""
    if str(message.from_user.id) != str(ADMIN_ID):
        BOT.reply_to(message, "⛔ Not authorized.")
        return

    parts = message.text.strip().split()
    if len(parts) < 2:
        BOT.reply_to(message, "⚠️ Usage: /disconnect FILE_ID")
        return

    file_id = parts[1].strip().upper()
    state = load_state()
    found = None

    for key, entry in state.items():
        if str(entry.get("file_code", "")).upper() == file_id:
            found = entry
            break

    if not found:
        BOT.reply_to(message, f"❌ File ID {file_id} not found.")
        return

    # mark disconnected
    found["is_disconnected"] = True
    save_state(state)

    # edit caption immediately
    if edit_caption_in_group(found, new_status="❌ DISCONNECTED"):
        flag = country_to_flag(found["country"])
        BOT.reply_to(
            message,
            f"{flag} {found['country']} ({file_id}) marked as ❌ DISCONNECTED manually."
        )
        logger.warning(f"⚠️ Admin manually disconnected {found['country']} ({file_id})")
        alert_admin_message(f"⚠️ Admin manually disconnected {found['country']} ({file_id})")
    else:
        BOT.reply_to(message, f"⚠️ Failed to update caption for {file_id}.")

@BOT.message_handler(commands=["reconnect"])
def manual_reconnect(message):
    """Admin command: /reconnect FILE_ID"""
    if str(message.from_user.id) != str(ADMIN_ID):
        BOT.reply_to(message, "⛔ Not authorized.")
        return

    parts = message.text.strip().split()
    if len(parts) < 2:
        BOT.reply_to(message, "⚠️ Usage: /reconnect FILE_ID")
        return

    file_id = parts[1].strip().upper()
    state = load_state()
    found = None

    for key, entry in state.items():
        if str(entry.get("file_code", "")).upper() == file_id:
            found = entry
            break

    if not found:
        BOT.reply_to(message, f"❌ File ID {file_id} not found.")
        return

    found["is_disconnected"] = False
    save_state(state)

    if edit_caption_in_group(found, new_status="✅ ACTIVE"):
        BOT.reply_to(
            message,
            f"{country_to_flag(found['country'])} {found['country']} ({file_id}) manually reactivated ✅"
        )
        logger.info(f"🟢 Admin manually reactivated {found['country']} ({file_id})")
        alert_admin_message(f"🟢 Admin manually reactivated {found['country']} ({file_id})")
    else:
        BOT.reply_to(message, f"⚠️ Failed to update caption for {file_id}.")

# ========== 📊 STATUS COMMAND ==========
@BOT.message_handler(commands=["status"])
def check_status(message):
    """Show summary of all ACTIVE / DISCONNECTED files."""
    if str(message.from_user.id) != str(ADMIN_ID):
        BOT.reply_to(message, "⛔ Not authorized.")
        return

    state = load_state()
    if not state:
        BOT.reply_to(message, "⚠️ No files found in state.")
        return

    active_files = []
    disconnected_files = []

    for entry in state.values():
        country = entry.get("country", "Unknown")
        file_id = entry.get("file_code", "N/A")
        flag = country_to_flag(country)
        status = "✅" if not entry.get("is_disconnected", False) else "❌"

        if status == "✅":
            active_files.append(f"{flag} {country} — {file_id} ✅")
        else:
            disconnected_files.append(f"{flag} {country} — {file_id} ❌")

    # Summary counts
    summary = (
        f"📊 *Current Status Summary*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Active Files: {len(active_files)}\n"
        f"❌ Disconnected Files: {len(disconnected_files)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    # Combine with details
    details = "\n".join(active_files + disconnected_files) or "No entries yet."

    BOT.reply_to(message, f"{summary}{details}", parse_mode="Markdown")

# ---------- Monitor logic ----------
def monitor_loop():
    """
    H2I NumberBot — Smart Panel Sync
    ✅ Adds only new unseen numbers
    ✅ Removes only those confirmed missing in panel
    ✅ Never writes 0-number file unless verified empty twice
    ✅ Handles temporary HTML/invalid responses safely
    """
    mode = "SQLite-SmartSync"
    logger.info(f"🚀 Monitor thread started in [{mode}] mode. Interval: {CHECK_INTERVAL}s")

    state = load_state()
    COOLDOWN_SECONDS = 60

    # Initial login
    if not login():
        logger.error("Cannot login to panel — retrying in background.")

    # Init DBs and states
    ranges = fetch_country_ranges_from_panel(max_pages=10) or {}
    for cname in ranges.keys():
        ensure_country_file_and_state(state, cname)
        init_country_db(cname)
    save_state(state)

    # Keep last good fetch memory
    last_good_panel = {}

    while True:
        try:
            ranges = fetch_country_ranges_from_panel(max_pages=10)
            if not ranges:
                logger.warning("⚠️ No country ranges fetched, sleeping...")
                time.sleep(CHECK_INTERVAL)
                continue

            state = load_state()

            for country, info in ranges.items():
                rid = info.get("range")
                if not rid:
                    continue

                entry = ensure_country_file_and_state(state, country)
                db_path = init_country_db(country)

                if entry.get("is_disconnected", False):
                    logger.info(f"[{country}] ⛔ Skipped (manual disconnect).")
                    continue

                # Fetch fresh numbers
                try:
                    live_numbers = fetch_numbers_from_panel(rid)
                    if not live_numbers:
                        logger.warning(f"[{country}] ⚠️ Panel gave empty list, retrying next loop.")
                        continue
                except Exception as e:
                    logger.warning(f"⚠️ Fetch failed for {country}: {e}")
                    continue

                # Normalize
                live_norm = [re.sub(r"\D", "", str(x)) for x in live_numbers if x]
                live_norm = [x for x in live_norm if len(x) > 4]
                live_set = set(live_norm)

                # Skip invalid or unstable response
                if len(live_set) == 0:
                    logger.debug(f"[{country}] Skipping update (no valid numbers).")
                    continue

                prev_nums = set(db_get_all_numbers(db_path))
                db_before = len(prev_nums)

                # 1️⃣ Identify changes
                new_nums = [n for n in live_set if n not in prev_nums]
                removed_nums = [n for n in prev_nums if n not in live_set]

                # 2️⃣ Add new ones only
                if new_nums:
                    db_add_numbers(db_path, new_nums)
                    logger.info(f"[{country}] ➕ Added {len(new_nums)} new numbers")

                # 3️⃣ Remove only if confirmed missing twice
                if removed_nums:
                    # confirm once more next cycle
                    if country in last_good_panel and removed_nums == last_good_panel[country].get("pending_remove"):
                        db_remove_numbers(db_path, removed_nums)
                        logger.info(f"[{country}] ➖ Confirmed {len(removed_nums)} numbers removed")
                        last_good_panel[country]["pending_remove"] = []
                    else:
                        last_good_panel.setdefault(country, {})["pending_remove"] = removed_nums
                        logger.debug(f"[{country}] 🕓 Pending remove ({len(removed_nums)}) until next confirmation.")
                        continue

                last_good_panel.setdefault(country, {})["pending_remove"] = []

                # 4️⃣ Update file and send if changed
                db_after = len(db_get_all_numbers(db_path))
                if not new_nums and not removed_nums:
                    logger.info(f"[{country}] ✅ No change (DB={db_after})")
                    continue

                entry["numbers"] = list(db_get_all_numbers(db_path))
                db_export_to_txt(db_path, entry["filepath"], country)

                # Avoid flood resend
                last_time = entry.get("last_sent_time", 0)
                if time.time() - last_time < COOLDOWN_SECONDS:
                    logger.debug(f"[{country}] ⏸️ Cooldown active, skipping re-send.")
                    continue

                send_file_to_group(entry)
                entry["last_sent_time"] = int(time.time())
                save_state(state)
                logger.info(f"📤 Updated file sent for {country} ({db_after} numbers)")
                time.sleep(0.5)

        except Exception as e:
            logger.error(f"❌ Monitor loop error: {e}")

        cleanup_old_disconnected(state, days=7)
        time.sleep(CHECK_INTERVAL)


# ---------- Flask health endpoint (simple) ----------
from flask import Flask, Response
app = Flask(__name__)
@app.route("/")
def index():
    return "H2I NumberBot V2 running"

@app.route("/health")
def health():
    return Response("OK", status=200)

def run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))

def print_startup_summary():
    logger.info("==========================================")
    logger.info("   🧩 H2I NumberBot V2 Startup Summary")
    logger.info("------------------------------------------")
    logger.info(" Mode         : SQLite (permanent)")
    logger.info(f" Interval     : {CHECK_INTERVAL}s")
    logger.info(f" Group ID     : {DEST_GROUP_ID}")
    logger.info(f" DB Directory : {os.path.join(NUMBERS_DIR, 'db')}")
    logger.info(f" File Storage : {NUMBERS_DIR}")
    logger.info("==========================================")

# ---------- Start everything ----------
# ---------- Start everything ----------
if __name__ == "__main__":
    print_startup_summary()
    logger.info("🚀 Starting H2I NumberBot V2...")

    # ✅ ensure state file ready
    s = load_state()
    save_state(s)

    # ✅ Start Flask server (for /health endpoint)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("🌐 Flask health endpoint started.")

    # ✅ Start panel auto login refresher
    login_thread = threading.Thread(target=ensure_login, daemon=True)
    login_thread.start()
    logger.info("🔑 Auto login refresher thread started.")

    # ✅ Start the monitor thread (country scanning)
    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()
    logger.info("🛰️ Monitor thread started successfully.")

    # ✅ Start Telegram bot polling (for /disconnect, /status, etc.)
    def start_bot_polling():
        try:
            logger.info("🤖 Telegram command listener started.")
            BOT.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logger.error(f"❌ Telegram polling crashed: {e}")
            time.sleep(10)
            start_bot_polling()  # restart automatically if crash

    bot_thread = threading.Thread(target=start_bot_polling, daemon=True)
    bot_thread.start()

    # 💤 Keep main thread alive cleanly
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down gracefully...")
        save_state(load_state())
