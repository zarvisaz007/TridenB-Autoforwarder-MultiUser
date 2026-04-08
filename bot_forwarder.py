import os
import re
import time
import asyncio
import logging
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError

from bot_database import (
    get_tasks, update_task_status, add_message_map, get_message_map,
    get_reply_to_dest_id, delete_message_map, delete_message_map_by_src,
    get_old_image_messages, delete_message_record, get_all_connected_users,
    get_all_enabled_schedules, update_schedule_run, get_messages_by_date_range,
)

logger = logging.getLogger("bot.forwarder")

# ─── State ───

user_clients = {}       # user_id -> TelegramClient
user_state = {}         # user_id -> {paused_ids, loop_counter, cleanup_task, keepalive_task, ...}
SESSIONS_DIR = os.path.join(os.path.dirname(__file__), "sessions")
os.makedirs(SESSIONS_DIR, exist_ok=True)

LOOP_LIMIT = 10
LOOP_WINDOW = 10

# ─── Per-user log storage (last 200 entries per user) ───
user_logs = {}  # user_id -> [str]
MAX_LOG = 200


def add_user_log(user_id: int, msg: str):
    ts = time.strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    logs = user_logs.setdefault(user_id, [])
    logs.append(entry)
    if len(logs) > MAX_LOG:
        logs.pop(0)
    logger.info(f"[User {user_id}] {msg}")


def get_user_logs(user_id: int, count: int = 50):
    return (user_logs.get(user_id) or [])[-count:]


# ─── Helpers ───

def normalize_id(cid):
    if not cid:
        return 0
    cid_str = str(cid).replace("-100", "").replace("-", "")
    return int(cid_str) if cid_str.isdigit() else 0


def check_loop(user_id, task_id):
    state = user_state.get(user_id, {})
    counter = state.get("loop_counter", {})
    now = time.time()
    key = task_id
    times = counter.get(key, [])
    times = [t for t in times if now - t < LOOP_WINDOW]
    times.append(now)
    counter[key] = times
    state["loop_counter"] = counter
    user_state[user_id] = state
    return len(times) >= LOOP_LIMIT


def clear_loop_counter(user_id, task_id):
    state = user_state.get(user_id, {})
    counter = state.get("loop_counter", {})
    counter.pop(task_id, None)


_REGEX_TIMEOUT = 2.0  # seconds per regex operation before it is skipped


async def _safe_regex_search(pattern: str, text: str) -> bool:
    """Run re.search in a thread with a timeout. Returns False on timeout or error."""
    def _run():
        return bool(re.search(pattern, text, re.IGNORECASE))
    try:
        return await asyncio.wait_for(asyncio.to_thread(_run), timeout=_REGEX_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning(f"[ReDoS] regex_blacklist pattern timed out (>={_REGEX_TIMEOUT}s), skipping: {pattern!r}")
        return False
    except re.error:
        return False


async def _safe_regex_sub(pattern: str, text: str) -> str:
    """Run re.sub in a thread with a timeout. Returns original text on timeout or error."""
    def _run():
        return re.sub(pattern, "", text)
    try:
        return await asyncio.wait_for(asyncio.to_thread(_run), timeout=_REGEX_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning(f"[ReDoS] regex_clean pattern timed out (>={_REGEX_TIMEOUT}s), skipping: {pattern!r}")
        return text
    except re.error:
        return text


async def apply_filters(message, filters):
    """Full filter chain — matches main.py logic exactly."""
    if filters.get("skip_images") and message.photo:
        return (False, None)
    if filters.get("skip_audio") and (message.audio or message.voice):
        return (False, None)
    if filters.get("skip_videos") and message.video:
        return (False, None)

    text = message.text or ""
    text_lower = text.lower()

    # Whitelist check
    whitelist = filters.get("whitelist_words", [])
    if whitelist:
        if not any(w.lower() in text_lower for w in whitelist):
            return (False, None)

    # Blacklist check
    for word in filters.get("blacklist_words", []):
        if word.lower() in text_lower:
            return (False, None)

    # Regex blacklist — Fix 5: timeout-guarded
    for pattern in filters.get("regex_blacklist", []):
        if await _safe_regex_search(pattern, text):
            return (False, None)

    modified = False

    for w in filters.get("clean_words", []):
        if w in text:
            text = text.replace(w, "")
            modified = True

    # Regex clean — Fix 5: timeout-guarded
    for pattern in filters.get("regex_clean", []):
        new_text = await _safe_regex_sub(pattern, text)
        if new_text != text:
            text = new_text
            modified = True

    # Replacer — targeted swaps (runs before clean_urls/clean_usernames)
    replace_cfg = filters.get("replacements")
    if replace_cfg and replace_cfg.get("enabled") and text:
        from replacer import apply_replacements
        replaced = apply_replacements(text, replace_cfg)
        if replaced is not None:
            text = replaced
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


async def send_copy(client, dest_id, message, modified_text, reply_to=None):
    if modified_text is not None:
        return await client.send_message(dest_id, modified_text, reply_to=reply_to)
    if message.media:
        return await client.send_file(dest_id, file=message.media, caption=message.text or "", reply_to=reply_to)
    return await client.send_message(dest_id, message.text or "", reply_to=reply_to)


# ─── Client Management ───

def create_client(user_id: int) -> TelegramClient:
    api_id = int(os.environ["API_ID"])
    api_hash = os.environ["API_HASH"]
    session_path = os.path.join(SESSIONS_DIR, f"user_{user_id}.session")
    client = TelegramClient(session_path, api_id, api_hash)

    @client.on(events.NewMessage())
    async def nm_handler(event):
        try:
            await handle_new_message(event, user_id, client)
        except Exception as e:
            logger.error(f"[User {user_id}] NewMessage handler error: {e}")

    @client.on(events.MessageEdited())
    async def me_handler(event):
        try:
            await handle_edit_message(event, user_id, client)
        except Exception as e:
            logger.error(f"[User {user_id}] EditMessage handler error: {e}")

    @client.on(events.MessageDeleted())
    async def md_handler(event):
        try:
            await handle_delete_message(event, user_id, client)
        except Exception as e:
            logger.error(f"[User {user_id}] DeleteMessage handler error: {e}")

    return client


async def start_client_for_user(user_id: int):
    if user_id in user_clients:
        return user_clients[user_id]

    client = create_client(user_id)
    await client.connect()

    if not await client.is_user_authorized():
        await client.disconnect()
        logger.warning(f"User {user_id} not authorized — session may be expired.")
        return None

    user_clients[user_id] = client
    user_state.setdefault(user_id, {"loop_counter": {}, "paused_ids": set()})

    # Start background loops
    state = user_state[user_id]
    state["cleanup_task"] = asyncio.create_task(_image_cleanup_loop(user_id, client))
    state["keepalive_task"] = asyncio.create_task(_keepalive_loop(user_id, client))

    logger.info(f"Started Telethon client for user {user_id}")
    add_user_log(user_id, "Forwarder STARTED")
    return client


async def stop_client_for_user(user_id: int):
    state = user_state.get(user_id, {})
    for key in ("cleanup_task", "keepalive_task"):
        task = state.get(key)
        if task:
            task.cancel()
            state[key] = None

    if user_id in user_clients:
        await user_clients[user_id].disconnect()
        del user_clients[user_id]
        add_user_log(user_id, "Forwarder STOPPED")
        logger.info(f"Stopped Telethon client for user {user_id}")


async def load_all_active_clients():
    users = await get_all_connected_users()
    started = 0
    for u in users:
        result = await start_client_for_user(u["id"])
        if result:
            started += 1
    logger.info(f"Loaded {started}/{len(users)} active clients.")
    return started


# ─── Event Handlers ───

async def handle_new_message(event, user_id, client):
    chat_id = event.chat_id
    tasks = await get_tasks(user_id)
    enabled_tasks = [t for t in tasks if t["enabled"] and not t["paused"]]
    if not enabled_tasks:
        return

    abs_id = normalize_id(chat_id)

    matched_tasks = [t for t in enabled_tasks if normalize_id(t["source_channel_id"]) == abs_id]
    if not matched_tasks:
        # Debug: log unmatched chats occasionally so user can see events ARE arriving
        logger.debug(f"[User {user_id}] No task matches chat {chat_id} (normalized={abs_id})")
        return

    text_preview = repr((event.message.text or "")[:60])
    add_user_log(user_id, f"MSG chat={chat_id} text={text_preview}")

    reply_to_src_id = None
    if event.message.reply_to and event.message.reply_to.reply_to_msg_id:
        reply_to_src_id = event.message.reply_to.reply_to_msg_id

    for task in matched_tasks:
        asyncio.create_task(_process_task(event, user_id, client, task, reply_to_src_id))


async def _process_task(event, user_id, client, task, reply_to_src_id):
    state = user_state.get(user_id, {})
    paused_ids = state.get("paused_ids", set())

    if task["id"] in paused_ids:
        add_user_log(user_id, f"  [PAUSED] '{task['name']}' skipped")
        return

    if check_loop(user_id, task["id"]):
        paused_ids.add(task["id"])
        await update_task_status(task["id"], user_id, paused=True)
        add_user_log(user_id, f"  [LOOP] '{task['name']}' fired {LOOP_LIMIT}x in {LOOP_WINDOW}s — auto-paused!")
        return

    should_forward, modified_text = await apply_filters(event.message, task["filters"])
    if not should_forward:
        add_user_log(user_id, f"  [SKIP] '{task['name']}' — filtered")
        return

    if task["filters"].get("rewrite_enabled"):
        asyncio.create_task(_rewrite_and_forward(event, user_id, client, task, modified_text, reply_to_src_id))
    else:
        await _do_forward(event, user_id, client, task, modified_text, reply_to_src_id)


async def _rewrite_and_forward(event, user_id, client, task, modified_text, reply_to_src_id):
    text_to_rewrite = modified_text if modified_text is not None else (event.message.text or "")
    if text_to_rewrite and text_to_rewrite.strip():
        try:
            from rewriter import rewrite_text
            prompt = task["filters"].get("rewrite_prompt")
            add_user_log(user_id, f"  [AI] '{task['name']}' rewriting...")
            rewritten = await rewrite_text(text_to_rewrite, prompt=prompt)
            if rewritten != text_to_rewrite:
                modified_text = rewritten
                add_user_log(user_id, f"  [AI OK] Rewrote {len(text_to_rewrite)} -> {len(rewritten)} chars")
            else:
                add_user_log(user_id, f"  [AI WARN] Rewrite returned original")
        except Exception as e:
            add_user_log(user_id, f"  [AI ERR] {e}")
    await _do_forward(event, user_id, client, task, modified_text, reply_to_src_id)


async def _do_forward(event, user_id, client, task, modified_text, reply_to_src_id):
    delay = task["filters"].get("delay_seconds", 0)
    if delay > 0:
        add_user_log(user_id, f"  [DELAY] '{task['name']}' waiting {delay}s")
        await asyncio.sleep(delay)

    dest_ids = task.get("destination_channel_ids", [])

    async def send_to_dest(dest_id):
        reply_to_dest_id = None
        if reply_to_src_id is not None:
            reply_to_dest_id = await get_reply_to_dest_id(
                user_id, task["id"], task["source_channel_id"], reply_to_src_id, dest_id
            )
        try:
            sent = await send_copy(client, dest_id, event.message, modified_text, reply_to=reply_to_dest_id)
            text_for_db = modified_text if modified_text is not None else (event.message.text or "")
            await add_message_map(
                user_id, task["id"], task["source_channel_id"], event.message.id,
                dest_id, sent.id, has_image=bool(event.message.photo),
                text_content=text_for_db, reply_to_dest_id=reply_to_dest_id
            )
            add_user_log(user_id, f"  [OK] '{task['name']}' -> {dest_id} (msg {sent.id})")
        except FloodWaitError as e:
            add_user_log(user_id, f"  [FLOOD] sleeping {e.seconds}s")
            await asyncio.sleep(e.seconds)
        except Exception as e:
            add_user_log(user_id, f"  [ERR] '{task['name']}' -> {dest_id}: {e}")

    await asyncio.gather(*[send_to_dest(d) for d in dest_ids])


async def handle_edit_message(event, user_id, client):
    chat_id = event.chat_id
    tasks = await get_tasks(user_id)
    enabled_tasks = [t for t in tasks if t["enabled"] and not t["paused"]]
    if not enabled_tasks:
        return

    abs_id = normalize_id(chat_id)

    for task in enabled_tasks:
        if normalize_id(task["source_channel_id"]) != abs_id:
            continue
        entries = await get_message_map(user_id, task["source_channel_id"], event.message.id)
        if not entries:
            continue

        should_forward, modified_text = await apply_filters(event.message, task["filters"])
        if not should_forward:
            continue

        new_text = modified_text if modified_text is not None else (event.message.text or "")
        for entry in entries:
            try:
                await client.edit_message(entry["dest_channel_id"], entry["dest_msg_id"], text=new_text)
                add_user_log(user_id, f"  [EDIT OK] -> {entry['dest_channel_id']} msg {entry['dest_msg_id']}")
            except Exception as e:
                add_user_log(user_id, f"  [EDIT ERR] {entry['dest_channel_id']}: {e}")


async def handle_delete_message(event, user_id, client):
    chat_id = event.chat_id
    abs_id = normalize_id(chat_id) if chat_id else 0
    tasks = await get_tasks(user_id)
    enabled_tasks = [t for t in tasks if t["enabled"] and not t["paused"]]

    for deleted_id in event.deleted_ids:
        for task in enabled_tasks:
            sid = task["source_channel_id"]
            if chat_id is None or normalize_id(sid) == abs_id:
                entries = await get_message_map(user_id, sid, deleted_id)
                for entry in entries:
                    try:
                        await client.delete_messages(entry["dest_channel_id"], [entry["dest_msg_id"]])
                        await delete_message_map(user_id, entry["dest_channel_id"], entry["dest_msg_id"])
                        add_user_log(user_id, f"  [DEL OK] -> {entry['dest_channel_id']} msg {entry['dest_msg_id']}")
                    except Exception as e:
                        add_user_log(user_id, f"  [DEL ERR] {entry['dest_channel_id']}: {e}")


# ─── Background Loops ───

async def _image_cleanup_loop(user_id, client):
    while True:
        try:
            tasks = await get_tasks(user_id)
            for task in tasks:
                days = task["filters"].get("image_delete_days", 0)
                if days <= 0 or not task["enabled"]:
                    continue
                age_seconds = days * 24 * 3600
                old_msgs = await get_old_image_messages(user_id, task["id"], age_seconds)
                for msg in old_msgs:
                    try:
                        await client.delete_messages(msg["dest_channel_id"], [msg["dest_msg_id"]])
                        await delete_message_record(user_id, msg["dest_channel_id"], msg["dest_msg_id"])
                        add_user_log(user_id, f"  [CLEANUP] Deleted old image from {msg['dest_channel_id']}")
                    except Exception:
                        await delete_message_record(user_id, msg["dest_channel_id"], msg["dest_msg_id"])
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            return
        except Exception as e:
            add_user_log(user_id, f"  [CLEANUP ERR] {e}")
        await asyncio.sleep(3600)


async def _keepalive_loop(user_id, client):
    consecutive_failures = 0
    while True:
        try:
            if not client.is_connected():
                add_user_log(user_id, "[KEEPALIVE] Client disconnected — reconnecting...")
                logger.warning(f"[User {user_id}] Telethon client disconnected, attempting reconnect")
                await client.connect()
                if client.is_connected():
                    add_user_log(user_id, "[KEEPALIVE] Reconnected successfully!")
                    logger.info(f"[User {user_id}] Telethon client reconnected")
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    add_user_log(user_id, f"[KEEPALIVE] Reconnect failed (attempt {consecutive_failures})")
            else:
                await client.catch_up()
                consecutive_failures = 0
        except asyncio.CancelledError:
            return
        except Exception as e:
            consecutive_failures += 1
            if consecutive_failures <= 5 or consecutive_failures % 10 == 0:
                add_user_log(user_id, f"[KEEPALIVE] Error (attempt {consecutive_failures}): {e}")
                logger.warning(f"[User {user_id}] Keepalive error #{consecutive_failures}: {e}")
        # Back off: 10s normally, up to 60s on repeated failures
        delay = min(10 + (consecutive_failures * 5), 60)
        await asyncio.sleep(delay)


# ─── Report Scheduler (multi-user) ───

_report_scheduler_task = None
_last_reports = {}  # schedule_id -> {text, generated_at, message_count}


async def start_report_scheduler():
    global _report_scheduler_task
    if _report_scheduler_task is not None:
        return
    _report_scheduler_task = asyncio.create_task(_report_scheduler_loop())
    logger.info("Report scheduler started.")


async def stop_report_scheduler():
    global _report_scheduler_task
    if _report_scheduler_task:
        _report_scheduler_task.cancel()
        _report_scheduler_task = None


def get_last_report(schedule_id: int):
    return _last_reports.get(schedule_id)


def _compute_next_run(schedule):
    now = time.time()
    tod_parts = schedule.get("time_of_day", "08:00").split(":")
    hour = int(tod_parts[0])
    minute = int(tod_parts[1]) if len(tod_parts) > 1 else 0

    lt = time.localtime(now)
    today_start = time.mktime(time.struct_time((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, lt.tm_isdst)))
    target_today = today_start + hour * 3600 + minute * 60

    freq = schedule.get("frequency", "daily")
    if freq == "daily":
        return int(target_today + 86400) if target_today <= now else int(target_today)
    elif freq == "weekly":
        day_of_week = schedule.get("day_of_week", 0)
        days_ahead = day_of_week - lt.tm_wday
        if days_ahead < 0 or (days_ahead == 0 and target_today <= now):
            days_ahead += 7
        return int(target_today + days_ahead * 86400)
    elif freq == "monthly":
        import calendar
        day_of_month = schedule.get("day_of_month", 1)
        year, month = lt.tm_year, lt.tm_mon
        if lt.tm_mday > day_of_month or (lt.tm_mday == day_of_month and target_today <= now):
            month += 1
            if month > 12:
                month = 1
                year += 1
        max_day = calendar.monthrange(year, month)[1]
        actual_day = min(day_of_month, max_day)
        next_start = time.mktime(time.struct_time((year, month, actual_day, 0, 0, 0, 0, 0, lt.tm_isdst)))
        return int(next_start + hour * 3600 + minute * 60)
    return int(now + 86400)


async def _report_scheduler_loop():
    while True:
        try:
            schedules = await get_all_enabled_schedules()
            now = int(time.time())
            for sched in schedules:
                next_run = sched.get("next_run")
                if next_run and next_run <= now:
                    await _run_scheduled_report(sched)
                    new_next = _compute_next_run(sched)
                    await update_schedule_run(sched["id"], now, new_next)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"[REPORTS ERR] {e}")
        await asyncio.sleep(60)


async def _run_scheduled_report(schedule):
    user_id = schedule["user_id"]
    logger.info(f"[User {user_id}] Running scheduled report '{schedule.get('channel_name', '?')}'")
    add_user_log(user_id, f"[REPORTS] Running '{schedule.get('channel_name', '?')}' ({schedule['frequency']})")

    lookback = schedule.get("lookback_days", 1)
    now = int(time.time())
    start_ts = now - (lookback * 86400)

    messages = await get_messages_by_date_range(user_id, schedule["source_channel_id"], start_ts, now)
    if not messages:
        add_user_log(user_id, f"[REPORTS] No messages for last {lookback} day(s)")
        return

    from reports.engine import generate_report
    report_type = schedule.get("report_type", "summary")
    custom_prompt = schedule.get("custom_prompt")

    def progress(msg):
        add_user_log(user_id, f"[REPORTS] {msg}")

    report = await generate_report(messages, report_type=report_type, custom_prompt=custom_prompt, progress_cb=progress)

    _last_reports[schedule["id"]] = {
        "text": report,
        "generated_at": int(time.time()),
        "message_count": len(messages),
    }
    add_user_log(user_id, f"[REPORTS] Done — {len(messages)} msgs analyzed")
