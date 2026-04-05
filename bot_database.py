import json
import time
import logging
import aiosqlite

logger = logging.getLogger(__name__)

DB_FILE = "bot_data.db"


async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                phone TEXT,
                auth_state TEXT DEFAULT 'PENDING',
                created_at INTEGER,
                last_active INTEGER
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT,
                source_channel_id INTEGER,
                destination_channel_ids TEXT,
                enabled BOOLEAN DEFAULT 1,
                paused BOOLEAN DEFAULT 0,
                filters TEXT,
                created_at INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS message_map (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                task_id INTEGER,
                src_channel_id INTEGER,
                src_msg_id INTEGER,
                dest_channel_id INTEGER,
                dest_msg_id INTEGER,
                has_image BOOLEAN DEFAULT 0,
                text_content TEXT DEFAULT '',
                timestamp INTEGER,
                reply_to_dest_id INTEGER,
                UNIQUE(user_id, src_channel_id, src_msg_id, dest_channel_id, dest_msg_id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS report_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                source_channel_id INTEGER,
                channel_name TEXT,
                frequency TEXT,
                time_of_day TEXT,
                report_type TEXT DEFAULT 'summary',
                custom_prompt TEXT,
                lookback_days INTEGER DEFAULT 1,
                day_of_week INTEGER,
                day_of_month INTEGER,
                enabled BOOLEAN DEFAULT 1,
                last_run INTEGER,
                next_run INTEGER,
                created_at INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS queries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                phone TEXT DEFAULT '',
                message TEXT,
                reply TEXT,
                created_at INTEGER,
                replied_at INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')
        await db.execute("CREATE INDEX IF NOT EXISTS idx_msg_src ON message_map(user_id, src_channel_id, src_msg_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_msg_src_only ON message_map(src_msg_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_msg_task ON message_map(task_id, user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_msg_timestamp ON message_map(timestamp)")
        await db.commit()
    logger.info("Bot database initialized.")


# ─── Default Filters ───

DEFAULT_FILTERS = {
    "blacklist_words": [],
    "whitelist_words": [],
    "regex_blacklist": [],
    "clean_words": [],
    "regex_clean": [],
    "clean_urls": False,
    "clean_usernames": False,
    "skip_images": False,
    "skip_audio": False,
    "skip_videos": False,
    "delay_seconds": 0,
    "image_delete_days": 0,
    "rewrite_enabled": False,
    "rewrite_prompt": "",
}


# ─── Users ───

async def add_or_update_user(user_id: int, phone: str = None, auth_state: str = None):
    now = int(time.time())
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT phone, auth_state FROM users WHERE id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            _phone = phone or ""
            _auth_state = auth_state or "PENDING"
            await db.execute("INSERT INTO users (id, phone, auth_state, created_at, last_active) VALUES (?, ?, ?, ?, ?)",
                             (user_id, _phone, _auth_state, now, now))
        else:
            _phone = phone if phone is not None else row[0]
            _auth_state = auth_state if auth_state is not None else row[1]
            await db.execute("UPDATE users SET phone = ?, auth_state = ?, last_active = ? WHERE id = ?",
                             (_phone, _auth_state, now, user_id))
        await db.commit()


async def get_user(user_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT id, phone, auth_state, created_at, last_active FROM users WHERE id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {"id": row[0], "phone": row[1], "auth_state": row[2], "created_at": row[3], "last_active": row[4]}
            return None


async def get_all_users():
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT id, phone, auth_state, created_at, last_active FROM users ORDER BY last_active DESC") as cursor:
            rows = await cursor.fetchall()
            return [{"id": r[0], "phone": r[1], "auth_state": r[2], "created_at": r[3], "last_active": r[4]} for r in rows]


async def get_all_connected_users():
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT id, phone FROM users WHERE auth_state = 'CONNECTED'") as cursor:
            rows = await cursor.fetchall()
            return [{"id": r[0], "phone": r[1]} for r in rows]


async def delete_user(user_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await db.execute("DELETE FROM tasks WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM message_map WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM report_schedules WHERE user_id = ?", (user_id,))
        await db.commit()


async def update_user_activity(user_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("UPDATE users SET last_active = ? WHERE id = ?", (int(time.time()), user_id))
        await db.commit()


# ─── Tasks ───

def _parse_task(row: dict) -> dict:
    t = dict(row)
    t["destination_channel_ids"] = json.loads(t["destination_channel_ids"] or "[]")
    raw_filters = json.loads(t["filters"] or "{}")
    # Merge with defaults so all keys exist
    merged = dict(DEFAULT_FILTERS)
    merged.update(raw_filters)
    t["filters"] = merged
    t["enabled"] = bool(t["enabled"])
    t["paused"] = bool(t["paused"])
    return t


async def create_task(user_id: int, name: str, source: int, destinations: list, filters: dict = None):
    now = int(time.time())
    if filters is None:
        filters = dict(DEFAULT_FILTERS)
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute('''
            INSERT INTO tasks (user_id, name, source_channel_id, destination_channel_ids, enabled, filters, paused, created_at)
            VALUES (?, ?, ?, ?, 1, ?, 0, ?)
        ''', (user_id, name, source, json.dumps(destinations), json.dumps(filters), now))
        await db.commit()
        return cursor.lastrowid


async def get_tasks(user_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE user_id = ?", (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return [_parse_task(row) for row in rows]


async def get_all_tasks():
    """Admin: get all tasks across all users."""
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks ORDER BY user_id") as cursor:
            rows = await cursor.fetchall()
            return [_parse_task(row) for row in rows]


async def get_task(task_id: int, user_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id)) as cursor:
            row = await cursor.fetchone()
            if row:
                return _parse_task(row)
            return None


async def update_task_status(task_id: int, user_id: int, enabled: bool = None, paused: bool = None):
    async with aiosqlite.connect(DB_FILE) as db:
        if enabled is not None:
            await db.execute("UPDATE tasks SET enabled = ? WHERE id = ? AND user_id = ?", (int(enabled), task_id, user_id))
        if paused is not None:
            await db.execute("UPDATE tasks SET paused = ? WHERE id = ? AND user_id = ?", (int(paused), task_id, user_id))
        await db.commit()


async def update_task_filters(task_id: int, user_id: int, filters: dict):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("UPDATE tasks SET filters = ? WHERE id = ? AND user_id = ?",
                         (json.dumps(filters), task_id, user_id))
        await db.commit()


async def update_task_field(task_id: int, user_id: int, **kwargs):
    """Update arbitrary task fields (name, source_channel_id, destination_channel_ids)."""
    async with aiosqlite.connect(DB_FILE) as db:
        for field, value in kwargs.items():
            if field == "destination_channel_ids":
                value = json.dumps(value)
            await db.execute(f"UPDATE tasks SET {field} = ? WHERE id = ? AND user_id = ?",
                             (value, task_id, user_id))
        await db.commit()


async def delete_task(task_id: int, user_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
        await db.execute("DELETE FROM message_map WHERE task_id = ? AND user_id = ?", (task_id, user_id))
        await db.commit()


# ─── Message Map ───

async def add_message_map(user_id: int, task_id: int, src_channel: int, src_msg: int,
                          dest_channel: int, dest_msg: int, has_image: bool = False,
                          text_content: str = "", reply_to_dest_id: int = None):
    now = int(time.time())
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute('''
            INSERT OR IGNORE INTO message_map
            (user_id, task_id, src_channel_id, src_msg_id, dest_channel_id, dest_msg_id,
             has_image, text_content, timestamp, reply_to_dest_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, task_id, src_channel, src_msg, dest_channel, dest_msg,
              int(has_image), text_content, now, reply_to_dest_id))
        await db.commit()


async def get_message_map(user_id: int, src_channel: int, src_msg: int):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('''
            SELECT * FROM message_map
            WHERE user_id = ? AND src_channel_id = ? AND src_msg_id = ?
        ''', (user_id, src_channel, src_msg)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def get_reply_to_dest_id(user_id: int, task_id: int, src_channel: int, reply_to_src_id: int, dest_channel: int):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute('''
            SELECT dest_msg_id FROM message_map
            WHERE user_id = ? AND task_id = ? AND src_channel_id = ? AND src_msg_id = ? AND dest_channel_id = ?
            ORDER BY timestamp DESC LIMIT 1
        ''', (user_id, task_id, src_channel, reply_to_src_id, dest_channel)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def delete_message_map(user_id: int, dest_channel: int, dest_msg: int):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute('''
            DELETE FROM message_map
            WHERE user_id = ? AND dest_channel_id = ? AND dest_msg_id = ?
        ''', (user_id, dest_channel, dest_msg))
        await db.commit()


async def delete_message_map_by_src(user_id: int, src_channel: int, src_msg: int):
    """Delete all dest entries for a source message, returning them first."""
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('''
            SELECT * FROM message_map
            WHERE user_id = ? AND src_channel_id = ? AND src_msg_id = ?
        ''', (user_id, src_channel, src_msg)) as cursor:
            rows = [dict(r) for r in await cursor.fetchall()]
        if rows:
            await db.execute('''
                DELETE FROM message_map
                WHERE user_id = ? AND src_channel_id = ? AND src_msg_id = ?
            ''', (user_id, src_channel, src_msg))
            await db.commit()
        return rows


async def get_old_image_messages(user_id: int, task_id: int, age_seconds: int):
    cutoff = int(time.time()) - age_seconds
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('''
            SELECT dest_channel_id, dest_msg_id FROM message_map
            WHERE user_id = ? AND task_id = ? AND has_image = 1 AND timestamp < ?
        ''', (user_id, task_id, cutoff)) as cursor:
            return [dict(r) for r in await cursor.fetchall()]


async def delete_message_record(user_id: int, dest_channel: int, dest_msg: int):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute('''
            DELETE FROM message_map
            WHERE user_id = ? AND dest_channel_id = ? AND dest_msg_id = ?
        ''', (user_id, dest_channel, dest_msg))
        await db.commit()


# ─── Statistics ───

async def get_statistics(user_id: int):
    now = int(time.time())
    start_of_today = now - (now % 86400)
    start_of_week = now - (now % 604800)
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('''
            SELECT task_id,
                   count(id) as total_messages,
                   sum(has_image) as total_images,
                   max(timestamp) as last_active,
                   sum(CASE WHEN timestamp >= ? THEN 1 ELSE 0 END) as today_count,
                   sum(CASE WHEN timestamp >= ? THEN 1 ELSE 0 END) as week_count
            FROM message_map
            WHERE user_id = ?
            GROUP BY task_id
        ''', (start_of_today, start_of_week, user_id)) as cursor:
            return [dict(r) for r in await cursor.fetchall()]


async def get_all_statistics():
    """Admin: stats across all users."""
    now = int(time.time())
    start_of_today = now - (now % 86400)
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('''
            SELECT user_id,
                   count(id) as total_messages,
                   sum(has_image) as total_images,
                   max(timestamp) as last_active,
                   sum(CASE WHEN timestamp >= ? THEN 1 ELSE 0 END) as today_count
            FROM message_map
            GROUP BY user_id
        ''', (start_of_today,)) as cursor:
            return [dict(r) for r in await cursor.fetchall()]


async def get_threads(user_id: int, limit: int = 50):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('''
            SELECT a.task_id, a.dest_channel_id, a.dest_msg_id as dest_message_id,
                   a.text_content, a.timestamp as parent_time,
                   COUNT(b.id) as reply_count,
                   MAX(b.timestamp) as latest_reply_time
            FROM message_map a
            JOIN message_map b ON a.dest_msg_id = b.reply_to_dest_id
                AND a.dest_channel_id = b.dest_channel_id AND a.user_id = b.user_id
            WHERE a.user_id = ?
            GROUP BY a.id
            ORDER BY parent_time DESC
            LIMIT ?
        ''', (user_id, limit)) as cursor:
            return [dict(r) for r in await cursor.fetchall()]


async def get_messages_by_date_range(user_id: int, source_channel_id: int, start_ts: int, end_ts: int):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('''
            SELECT text_content, timestamp, has_image FROM message_map
            WHERE user_id = ? AND src_channel_id = ? AND timestamp >= ? AND timestamp <= ?
            AND text_content != ''
            ORDER BY timestamp ASC
        ''', (user_id, source_channel_id, start_ts, end_ts)) as cursor:
            return [dict(r) for r in await cursor.fetchall()]


async def get_source_channels(user_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('''
            SELECT DISTINCT src_channel_id as source_channel_id, count(id) as msg_count
            FROM message_map
            WHERE user_id = ? AND text_content != ''
            GROUP BY src_channel_id
        ''', (user_id,)) as cursor:
            return [dict(r) for r in await cursor.fetchall()]


# ─── Report Schedules ───

async def create_report_schedule(user_id: int, source_channel_id: int, channel_name: str,
                                  frequency: str, time_of_day: str, report_type: str = "summary",
                                  custom_prompt: str = None, lookback_days: int = 1,
                                  day_of_week: int = None, day_of_month: int = None, next_run: int = None):
    now = int(time.time())
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute('''
            INSERT INTO report_schedules
            (user_id, source_channel_id, channel_name, frequency, time_of_day, report_type,
             custom_prompt, lookback_days, day_of_week, day_of_month, enabled, next_run, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        ''', (user_id, source_channel_id, channel_name, frequency, time_of_day, report_type,
              custom_prompt, lookback_days, day_of_week, day_of_month, next_run, now))
        await db.commit()
        return cursor.lastrowid


async def get_report_schedules(user_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM report_schedules WHERE user_id = ?", (user_id,)) as cursor:
            return [dict(r) for r in await cursor.fetchall()]


async def get_all_enabled_schedules():
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM report_schedules WHERE enabled = 1") as cursor:
            return [dict(r) for r in await cursor.fetchall()]


async def update_schedule_run(schedule_id: int, last_run: int, next_run: int):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("UPDATE report_schedules SET last_run = ?, next_run = ? WHERE id = ?",
                         (last_run, next_run, schedule_id))
        await db.commit()


async def toggle_report_schedule(schedule_id: int, user_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM report_schedules WHERE id = ? AND user_id = ?",
                              (schedule_id, user_id)) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        new_enabled = not bool(row["enabled"])
        await db.execute("UPDATE report_schedules SET enabled = ? WHERE id = ?", (int(new_enabled), schedule_id))
        await db.commit()
        result = dict(row)
        result["enabled"] = new_enabled
        return result


async def delete_report_schedule(schedule_id: int, user_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("DELETE FROM report_schedules WHERE id = ? AND user_id = ?", (schedule_id, user_id))
        await db.commit()


# ─── Queries / Messages ───

async def add_query(user_id: int, phone: str, message: str):
    now = int(time.time())
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute(
            "INSERT INTO queries (user_id, phone, message, created_at) VALUES (?, ?, ?, ?)",
            (user_id, phone or "", message, now),
        )
        await db.commit()
        return cursor.lastrowid


async def get_all_queries(limit: int = 50):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM queries ORDER BY created_at DESC LIMIT ?", (limit,)
        ) as cursor:
            return [dict(r) for r in await cursor.fetchall()]


async def get_user_queries(user_id: int, limit: int = 20):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM queries WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ) as cursor:
            return [dict(r) for r in await cursor.fetchall()]


async def mark_query_replied(query_id: int, reply: str):
    now = int(time.time())
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "UPDATE queries SET reply = ?, replied_at = ? WHERE id = ?",
            (reply, now, query_id),
        )
        await db.commit()
