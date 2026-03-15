import asyncio
import json
import os
import re
import sys
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.types import PeerChannel
from telethon.errors import FloodWaitError

TASKS_FILE = "tasks.json"
MESSAGE_MAP_FILE = "message_map.json"
SESSION_NAME = "tridenb_autoforwarder"


# ---------- Sync helpers ----------

def load_tasks():
    if not os.path.exists(TASKS_FILE):
        return {"tasks": []}
    try:
        with open(TASKS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"tasks": []}


def save_tasks(data):
    with open(TASKS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_message_map():
    if not os.path.exists(MESSAGE_MAP_FILE):
        return {}
    try:
        with open(MESSAGE_MAP_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_message_map(mmap):
    with open(MESSAGE_MAP_FILE, "w") as f:
        json.dump(mmap, f)


def mmap_key(src_channel_id, src_msg_id):
    return f"{src_channel_id}:{src_msg_id}"


def next_task_id(data):
    tasks = data.get("tasks", [])
    if not tasks:
        return 1
    return max(t["id"] for t in tasks) + 1


def apply_filters(message, filters):
    # Media checks
    if filters.get("skip_images") and message.photo:
        return (False, None)
    if filters.get("skip_audio") and (message.audio or message.voice):
        return (False, None)
    if filters.get("skip_videos") and message.video:
        return (False, None)

    text = message.text or ""

    # Blacklist check
    blacklist = filters.get("blacklist_words", [])
    text_lower = text.lower()
    for word in blacklist:
        if word.lower() in text_lower:
            return (False, None)

    # Clean pipeline
    modified = False

    clean_words = filters.get("clean_words", [])
    for w in clean_words:
        if w in text:
            text = text.replace(w, "")
            modified = True

    if filters.get("clean_urls"):
        new_text = re.sub(r"https?://\S+", "", text)
        if new_text != text:
            modified = True
            text = new_text

    if filters.get("clean_usernames"):
        new_text = re.sub(r"@\w+", "", text)
        if new_text != text:
            modified = True
            text = new_text

    if modified:
        return (True, text.strip())
    return (True, None)


# ---------- Async CLI functions ----------

async def get_channel_id(client):
    print("\n--- All Channels / Groups ---")
    print(f"{'Name':<40} {'Channel ID':<20}")
    print("-" * 60)
    async for dialog in client.iter_dialogs():
        if dialog.is_channel or dialog.is_group:
            name = dialog.name or "(no name)"
            cid = dialog.entity.id
            # Channels/supergroups use -100 prefix in bot API style
            if dialog.is_channel:
                full_id = int(f"-100{cid}")
            else:
                full_id = -cid if cid > 0 else cid
            print(f"{name:<40} {full_id:<20}")
    print()


async def create_task(client):
    data = load_tasks()
    print("\n--- Create Forwarding Task ---")
    name = input("Task name: ").strip()

    src_raw = input("Source channel ID (e.g. -1001234567890): ").strip()
    dst_raw = input("Destination channel IDs (comma-separated, e.g. -1001111111111,-1002222222222): ").strip()

    try:
        source_id = int(src_raw)
        dest_ids = [int(x.strip()) for x in dst_raw.split(",") if x.strip()]
    except ValueError:
        print("Invalid channel IDs.")
        return

    if not dest_ids:
        print("At least one destination ID required.")
        return

    print("\nFilters (press Enter to skip / use defaults):")

    def prompt_list(prompt):
        raw = input(f"  {prompt} (comma-separated, blank=none): ").strip()
        return [x.strip() for x in raw.split(",") if x.strip()] if raw else []

    def prompt_bool(prompt, default=False):
        val = input(f"  {prompt} [y/N]: ").strip().lower()
        return val in ("y", "yes")

    blacklist = prompt_list("Blacklist words")
    clean_words = prompt_list("Clean words (remove from text)")
    clean_urls = prompt_bool("Remove URLs?")
    clean_usernames = prompt_bool("Remove @usernames?")
    skip_images = prompt_bool("Skip image messages?")
    skip_audio = prompt_bool("Skip audio/voice messages?")
    skip_videos = prompt_bool("Skip video messages?")

    task = {
        "id": next_task_id(data),
        "name": name,
        "source_channel_id": source_id,
        "destination_channel_ids": dest_ids,
        "enabled": True,
        "filters": {
            "blacklist_words": blacklist,
            "clean_words": clean_words,
            "clean_urls": clean_urls,
            "clean_usernames": clean_usernames,
            "skip_images": skip_images,
            "skip_audio": skip_audio,
            "skip_videos": skip_videos,
        },
    }

    data["tasks"].append(task)
    save_tasks(data)
    print(f"\nTask '{name}' created with ID {task['id']}.")


async def list_tasks():
    data = load_tasks()
    tasks = data.get("tasks", [])
    if not tasks:
        print("No tasks found.")
        return

    print(f"\n{'ID':<5} {'Name':<20} {'Enabled':<8} {'Source':<22} {'Destinations'}")
    print("-" * 90)
    for t in tasks:
        status = "Yes" if t.get("enabled") else "No"
        dests = ", ".join(str(d) for d in t.get("destination_channel_ids", [t.get("destination_channel_id", "?")]))
        print(f"{t['id']:<5} {t['name']:<20} {status:<8} {t['source_channel_id']:<22} {dests}")


async def toggle_task():
    await list_tasks()
    try:
        tid = int(input("\nEnter task ID to toggle: ").strip())
    except ValueError:
        print("Invalid ID.")
        return

    data = load_tasks()
    for t in data["tasks"]:
        if t["id"] == tid:
            t["enabled"] = not t.get("enabled", True)
            save_tasks(data)
            state = "enabled" if t["enabled"] else "disabled"
            print(f"Task {tid} is now {state}.")
            return
    print(f"Task {tid} not found.")


async def edit_task_filters():
    await list_tasks()
    try:
        tid = int(input("\nEnter task ID to edit filters: ").strip())
    except ValueError:
        print("Invalid ID.")
        return

    data = load_tasks()
    task = next((t for t in data["tasks"] if t["id"] == tid), None)
    if not task:
        print(f"Task {tid} not found.")
        return

    filters = task["filters"]
    print(f"\nCurrent filters for task '{task['name']}':")
    for k, v in filters.items():
        print(f"  {k}: {v}")

    print("\nEdit filters (press Enter to keep current value):")

    def edit_list(key, prompt):
        current = filters.get(key, [])
        raw = input(f"  {prompt} [{', '.join(current) or 'none'}]: ").strip()
        if raw:
            filters[key] = [x.strip() for x in raw.split(",") if x.strip()]

    def edit_bool(key, prompt):
        current = filters.get(key, False)
        raw = input(f"  {prompt} [{'Y' if current else 'N'}]: ").strip().lower()
        if raw in ("y", "yes"):
            filters[key] = True
        elif raw in ("n", "no"):
            filters[key] = False

    edit_list("blacklist_words", "Blacklist words")
    edit_list("clean_words", "Clean words")
    edit_bool("clean_urls", "Remove URLs?")
    edit_bool("clean_usernames", "Remove @usernames?")
    edit_bool("skip_images", "Skip images?")
    edit_bool("skip_audio", "Skip audio?")
    edit_bool("skip_videos", "Skip videos?")

    save_tasks(data)
    print("Filters updated.")


async def delete_task():
    await list_tasks()
    try:
        tid = int(input("\nEnter task ID to delete: ").strip())
    except ValueError:
        print("Invalid ID.")
        return

    data = load_tasks()
    task = next((t for t in data["tasks"] if t["id"] == tid), None)
    if not task:
        print(f"Task {tid} not found.")
        return

    confirm = input(f"Delete task '{task['name']}' (ID {tid})? [y/N]: ").strip().lower()
    if confirm in ("y", "yes"):
        data["tasks"] = [t for t in data["tasks"] if t["id"] != tid]
        save_tasks(data)
        print(f"Task {tid} deleted.")
    else:
        print("Cancelled.")


async def send_copy(client, dest_id, message, modified_text):
    """Send message as a fresh copy — no 'Forwarded from' header."""
    if modified_text is not None:
        return await client.send_message(dest_id, modified_text)
    if message.media:
        return await client.send_file(dest_id, file=message.media, caption=message.text or "")
    return await client.send_message(dest_id, message.text or "")


async def run_forwarder(client):
    data = load_tasks()
    enabled = [t for t in data.get("tasks", []) if t.get("enabled")]
    tasks_by_id = {t["id"]: t for t in data.get("tasks", [])}

    if not enabled:
        print("No enabled tasks. Create and enable a task first.")
        return

    source_to_tasks = {}
    for t in enabled:
        sid = t["source_channel_id"]
        source_to_tasks.setdefault(sid, []).append(t)

    print("\nResolving source channels...")
    resolved_entities = []
    resolved_ids = {}  # raw entity.id (without -100) -> stored sid
    for sid in list(source_to_tasks.keys()):
        try:
            entity = await client.get_entity(sid)
            resolved_entities.append(entity)
            resolved_ids[entity.id] = sid
            print(f"  OK: {getattr(entity, 'title', sid)} (id={sid})")
        except Exception as e:
            print(f"  FAIL to resolve {sid}: {e}")

    if not resolved_entities:
        print("No source channels could be resolved. Check your channel IDs.")
        return

    print(f"\nForwarder running — watching {len(resolved_entities)} source(s) across {len(enabled)} task(s).")
    print("Press Ctrl+C to stop.\n")

    def get_sid(chat_id):
        if chat_id is None:
            return None
        abs_id = abs(chat_id) % (10 ** 12)
        return resolved_ids.get(abs_id) or resolved_ids.get(chat_id)

    @client.on(events.NewMessage(chats=resolved_entities))
    async def new_handler(event):
        sid = get_sid(event.chat_id)
        tasks_for_src = source_to_tasks.get(sid, [])
        text_preview = repr((event.message.text or "")[:60])
        print(f"[MSG] chat={event.chat_id} text={text_preview}")

        mmap = load_message_map()
        key = mmap_key(sid, event.message.id)
        mmap.setdefault(key, [])

        for task in tasks_for_src:
            should_forward, modified_text = apply_filters(event.message, task["filters"])
            if not should_forward:
                print(f"  [SKIP] '{task['name']}' — filtered")
                continue
            dest_ids = task.get("destination_channel_ids") or [task.get("destination_channel_id")]
            for dest_id in dest_ids:
                try:
                    sent = await send_copy(client, dest_id, event.message, modified_text)
                    mmap[key].append({"task_id": task["id"], "dest": dest_id, "msg_id": sent.id})
                    print(f"  [OK] '{task['name']}' → {dest_id} (msg {sent.id})")
                except FloodWaitError as e:
                    print(f"  [FLOOD] sleeping {e.seconds}s")
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    print(f"  [ERR] '{task['name']}' → {dest_id}: {e}")

        save_message_map(mmap)

    @client.on(events.MessageEdited(chats=resolved_entities))
    async def edit_handler(event):
        sid = get_sid(event.chat_id)
        key = mmap_key(sid, event.message.id)
        mmap = load_message_map()
        entries = mmap.get(key, [])
        if not entries:
            return
        print(f"[EDIT] chat={event.chat_id} msg={event.message.id}")
        for entry in entries:
            task = tasks_by_id.get(entry["task_id"])
            if not task:
                continue
            should_forward, modified_text = apply_filters(event.message, task["filters"])
            if not should_forward:
                continue
            new_text = modified_text if modified_text is not None else (event.message.text or "")
            try:
                await client.edit_message(entry["dest"], entry["msg_id"], text=new_text)
                print(f"  [EDIT OK] → {entry['dest']} msg {entry['msg_id']}")
            except Exception as e:
                print(f"  [EDIT ERR] {entry['dest']}: {e}")

    @client.on(events.MessageDeleted(chats=resolved_entities))
    async def delete_handler(event):
        sid = get_sid(event.chat_id)
        mmap = load_message_map()
        changed = False
        for deleted_id in event.deleted_ids:
            key = mmap_key(sid, deleted_id) if sid else None
            entries = mmap.get(key, []) if key else []
            if not entries:
                # Fallback: scan map for this msg_id
                for k, v in mmap.items():
                    if k.endswith(f":{deleted_id}"):
                        entries = v
                        key = k
                        break
            if not entries:
                continue
            print(f"[DEL] msg={deleted_id}")
            for entry in entries:
                try:
                    await client.delete_messages(entry["dest"], [entry["msg_id"]])
                    print(f"  [DEL OK] → {entry['dest']} msg {entry['msg_id']}")
                except Exception as e:
                    print(f"  [DEL ERR] {entry['dest']}: {e}")
            del mmap[key]
            changed = True
        if changed:
            save_message_map(mmap)

    await client.run_until_disconnected()


async def main_menu(client):
    while True:
        print("\n=== TridenB Autoforwarder ===")
        print("1. Get Channel ID")
        print("2. Create Forwarding Task")
        print("3. List Tasks")
        print("4. Toggle Task (enable/disable)")
        print("5. Edit Task Filters")
        print("6. Delete Task")
        print("7. Run Forwarder")
        print("0. Exit")

        choice = input("\nSelect option: ").strip()

        if choice == "1":
            await get_channel_id(client)
        elif choice == "2":
            await create_task(client)
        elif choice == "3":
            await list_tasks()
        elif choice == "4":
            await toggle_task()
        elif choice == "5":
            await edit_task_filters()
        elif choice == "6":
            await delete_task()
        elif choice == "7":
            await run_forwarder(client)
        elif choice == "0":
            print("Goodbye.")
            break
        else:
            print("Invalid option.")


async def main():
    load_dotenv()
    api_id = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")
    phone = os.getenv("PHONE")

    if not api_id or not api_hash or not phone:
        print("Error: API_ID, API_HASH, and PHONE must be set in .env")
        sys.exit(1)

    client = TelegramClient(SESSION_NAME, int(api_id), api_hash)
    await client.start(phone=phone)
    print("Authenticated successfully.")

    try:
        await main_menu(client)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
