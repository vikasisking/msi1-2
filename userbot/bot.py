from telethon import TelegramClient, events
import asyncio
import os

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


# === Handler 1: Forward message text from specific bots ===
@client.on(events.NewMessage)
async def forward_from_multiple_bots(event):
    sender = await event.get_sender()
    username = getattr(sender, "username", None)

    # skip if not from tracked bots
    if username not in BOT_GROUP_MAP:
        return

    try:
        target_group = BOT_GROUP_MAP[username]
        text = event.raw_text.strip()

        # skip empty text messages
        if not text:
            return

        msg_to_send = f"/disconnect {text}"
        await client.send_message(target_group, msg_to_send)
        print(f"[✔] From @{username} → {target_group} | Forwarded + /disconnect")

    except Exception as e:
        print(f"[❌] Error forwarding from @{username}: {e}")


# === Handler 2: Detect and resend .txt files in private groups ===
@client.on(events.NewMessage(chats=list(BOT_GROUP_MAP.values())))
async def resend_txt_file(event):
    try:
        # check if message contains a document
        if event.message.file and event.message.file.name and event.message.file.name.endswith(".txt"):
            file_name = event.message.file.name
            caption = event.message.text or ""
            chat_id = event.chat_id

            # download the .txt temporarily
            path = await event.download_media(file=file_name)
            print(f"[📁] .txt file received: {file_name}")

            # resend same file with same caption
            await client.send_file(chat_id, path, caption=caption)
            print(f"[🔁] Resent same .txt file back to group {chat_id}")

            # cleanup local file
            if os.path.exists(path):
                os.remove(path)

    except Exception as e:
        print(f"[❌] Error resending .txt file: {e}")


# === MAIN ===
async def main():
    print("🚀 Userbot started. Listening for bot messages & .txt files...")
    await client.start()
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
