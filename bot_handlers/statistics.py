import time
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot_database import get_statistics, get_tasks, get_threads

logger = logging.getLogger("bot.statistics")
router = Router()


@router.callback_query(F.data == "m_stats")
async def cb_stats(callback: CallbackQuery):
    user_id = callback.from_user.id
    stats = await get_statistics(user_id)
    tasks = await get_tasks(user_id)
    tasks_by_id = {t["id"]: t for t in tasks}

    if not stats:
        await callback.message.answer("No statistics yet. Start forwarding messages first.")
        await callback.answer()
        return

    lines = ["**Forwarding Statistics**\n"]
    lines.append("```")
    lines.append(f"{'Task':<20} {'Total':>6} {'Imgs':>5} {'Today':>6} {'Week':>5} {'Last Active'}")
    lines.append("-" * 70)

    total_msgs = 0
    total_imgs = 0

    for row in stats:
        tname = tasks_by_id.get(row["task_id"], {}).get("name", f"Task {row['task_id']}")
        if len(tname) > 18:
            tname = tname[:17] + "."
        total = row["total_messages"] or 0
        images = row["total_images"] or 0
        today = row["today_count"] or 0
        week = row["week_count"] or 0
        last_ts = row["last_active"]
        last_act = time.strftime("%m-%d %H:%M", time.localtime(last_ts)) if last_ts else "Never"

        total_msgs += total
        total_imgs += images

        lines.append(f"{tname:<20} {total:>6} {images:>5} {today:>6} {week:>5} {last_act}")

    lines.append("-" * 70)
    lines.append(f"{'TOTAL':<20} {total_msgs:>6} {total_imgs:>5}")
    lines.append("```")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n...```"

    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "m_threads")
async def cb_threads(callback: CallbackQuery):
    user_id = callback.from_user.id
    threads = await get_threads(user_id, limit=30)
    tasks = await get_tasks(user_id)
    tasks_by_id = {t["id"]: t for t in tasks}

    if not threads:
        await callback.message.answer("No reply threads recorded yet.")
        await callback.answer()
        return

    lines = ["**Message Threads (Replies)**\n"]

    for row in threads:
        tname = tasks_by_id.get(row["task_id"], {}).get("name", f"Task {row['task_id']}")
        ptime = time.strftime("%m-%d %H:%M", time.localtime(row["parent_time"]))
        rtime = time.strftime("%m-%d %H:%M", time.localtime(row["latest_reply_time"])) if row["latest_reply_time"] else "?"
        preview = (row["text_content"] or "")[:40].replace("\n", " ")
        if preview:
            preview += "..."
        else:
            preview = "[Media/Empty]"

        lines.append(f"**{tname}** | Msg {row['dest_message_id']} ({ptime})")
        lines.append(f"  `{preview}`")
        lines.append(f"  Replies: {row['reply_count']} (latest: {rtime})\n")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "..."

    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()
