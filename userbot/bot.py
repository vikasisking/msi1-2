from telethon import TelegramClient, events
import asyncio

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

@client.on(events.NewMessage)
async def forward_from_multiple_bots(event):
    sender = await event.get_sender()
    username = getattr(sender, "username", None)

    # skip if not a bot we are tracking
    if username not in BOT_GROUP_MAP:
        return

    try:
        target_group = BOT_GROUP_MAP[username]
        text = event.raw_text.strip()
        if not text:
            return

        msg_to_send = f"{text}\n\n/disconnect"
        await client.send_message(target_group, msg_to_send)
        print(f"[✔] From @{username} → {target_group} | Forwarded + /disconnect")
    except Exception as e:
        print(f"[❌] Error forwarding from @{username}: {e}")

async def main():
    print("🚀 Userbot started. Listening for bot messages...")
    await client.start()
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
