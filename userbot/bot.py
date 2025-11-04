from telethon import TelegramClient, events
import asyncio
import os
import re

# -------- CONFIG --------
API_ID = 22922489
API_HASH = "c9188fc0a202b2b3941d02dc9cc0cc84"
SESSION_NAME = "userbot_session"

# --- Mapping: Bot → Group
BOT_GROUP_MAP = {
    "Seacherzsbot": -1003297357915,   # Bot1 → Private Group 1
    "Seacherzs2bot": -1003193018523   # Bot2 → Private Group 2
}
# -------------------------

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)


# === Helper: Extract clean country-code patterns (AF-6644 etc.) ===
def extract_country_codes(text):
    # Match pattern like "VE-3441", "AF-6644", "KY-6402"
    pattern = r"\b([A-Z]{2}-\d{4,})\b"
    found = re.findall(pattern, text)
    return list(dict.fromkeys(found))  # unique, preserve order


# === Handler 1: For bot messages ===
@client.on(events.NewMessage)
async def handle_bot_messages(event):
    sender = await event.get_sender()
    username = getattr(sender, "username", None)

    if username not in BOT_GROUP_MAP:
        return  # ignore non-tracked senders

    target_group = BOT_GROUP_MAP[username]
    text = event.raw_text.strip()
    if not text:
        return

    try:
        # Detect scanning or file result messages
        if any(k in text for k in ["Found:", "Not Found:", "File:", "Scanning", "scan completed", "⏱", "✅", "❌"]):
            codes = extract_country_codes(text)

            if codes:
                bot_name = "Searcher 1" if username == "Seacherzsbot" else "Searcher 2"
                summary = bot_name + ":\n" + "\n".join(codes)

                await client.send_message(target_group, summary)
                print(f"[📊] Sent summary ({len(codes)} codes) from @{username}")
            else:
                print(f"[ℹ️] No valid codes found in @{username} message.")
        else:
            # For normal text → forward as /disconnect message
            msg_to_send = f"/disconnect {text}"
            await client.send_message(target_group, msg_to_send)
            print(f"[✔] /disconnect forwarded from @{username}")

    except Exception as e:
        print(f"[❌] Error processing message from @{username}: {e}")


# === Handler 2: Auto resend any .txt file inside private groups ===
@client.on(events.NewMessage(chats=list(BOT_GROUP_MAP.values())))
async def resend_txt_file(event):
    try:
        if event.message.file and event.message.file.name and event.message.file.name.endswith(".txt"):
            file_name = event.message.file.name
            caption = event.message.text or ""
            chat_id = event.chat_id

            # download temp file
            path = await event.download_media(file=file_name)
            print(f"[📁] .txt file detected: {file_name}")

            # resend in same group
            await client.send_file(chat_id, path, caption=caption)
            print(f"[🔁] File re-sent to group {chat_id}")

            if os.path.exists(path):
                os.remove(path)

    except Exception as e:
        print(f"[❌] Error resending file: {e}")


# === MAIN ===
async def main():
    print("🚀 Userbot active — listening for bot messages & txt files...")
    await client.start()
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
