import time
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

import bot_forwarder
from bot_database import get_tasks, get_task, get_statistics, update_task_status
from bot_handlers.menu import show_tasks_submenu, safe_edit

logger = logging.getLogger("bot.forwarder_ctl")
router = Router()


# ─── Channel ID Picker ───


@router.callback_query(F.data == "m_get_id")
async def cb_get_id(callback: CallbackQuery):
    user_id = callback.from_user.id
    client = bot_forwarder.user_clients.get(user_id)

    if not client or not client.is_connected():
        builder = InlineKeyboardBuilder()
        builder.button(text="▶️ Start Forwarder", callback_data="m_start_fwd")
        builder.button(text="⬅️ Back", callback_data="m_main")
        builder.adjust(1)
        await safe_edit(
            callback,
            "📡  *Channel Tools*\n"
            "━━━━━━━━━━━━━━━\n\n"
            "⚠️ Your Telegram client is not connected.\n"
            "Start the forwarder first to fetch channels.",
            parse_mode="Markdown",
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        return

    await callback.message.edit_text("📡  Fetching your channels...")
    await callback.answer()

    channels = []
    groups = []
    try:
        async for dialog in client.iter_dialogs():
            if dialog.is_channel or dialog.is_group:
                name = dialog.name or "(no name)"
                cid = dialog.entity.id
                if dialog.is_channel:
                    full_id = int("-100{}".format(cid))
                    channels.append((name, full_id))
                else:
                    full_id = -cid if cid > 0 else cid
                    groups.append((name, full_id))
    except Exception as e:
        logger.error("Error fetching dialogs for {}: {}".format(user_id, e))
        await callback.message.edit_text("❌ Failed to fetch: `{}`".format(e), parse_mode="Markdown")
        return

    if not channels and not groups:
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Back", callback_data="m_main")
        await callback.message.edit_text(
            "📡 No channels or groups found.",
            reply_markup=builder.as_markup(),
        )
        return

    channels.sort(key=lambda r: r[0].lower())
    groups.sort(key=lambda r: r[0].lower())

    # Build pages - show channels with inline buttons
    all_items = []
    if channels:
        all_items.append(("header", "📡  *Channels* ({})".format(len(channels))))
        all_items.extend(channels)
    if groups:
        all_items.append(("header", "👥  *Groups* ({})".format(len(groups))))
        all_items.extend(groups)

    text_parts = ["📡  *Your Channels & Groups*\n━━━━━━━━━━━━━━━━━━━━━━━━\n"]
    builder = InlineKeyboardBuilder()
    count = 0

    for item in all_items:
        if item[0] == "header":
            text_parts.append("\n{}\n".format(item[1]))
            continue

        name, full_id = item
        count += 1
        text_parts.append("{}. *{}*\n     `{}`\n".format(count, name, full_id))

        if count <= 30:
            builder.button(
                text="📋 {} → Copy ID".format(name[:25]),
                callback_data="cpid_{}".format(full_id),
            )

    builder.button(text="⬅️ Back", callback_data="m_main")
    builder.adjust(1)

    text = "\n".join(text_parts)
    if len(text) > 4000:
        text = text[:3950] + "\n\n_...more channels not shown_"

    await callback.message.edit_text(
        text,
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("cpid_"))
async def cb_copy_id(callback: CallbackQuery):
    """Send channel ID as a separate copyable message."""
    channel_id = callback.data.split("_", 1)[1]
    await callback.message.answer(
        "`{}`\n\n☝️ Tap to copy this channel ID".format(channel_id),
        parse_mode="Markdown",
    )
    await callback.answer("ID sent below!")


# ─── Start Forwarder ───


@router.callback_query(F.data == "m_start_fwd")
async def cb_start_fwd(callback: CallbackQuery):
    user_id = callback.from_user.id

    # Check if already running
    if user_id in bot_forwarder.user_clients:
        client = bot_forwarder.user_clients[user_id]
        if client.is_connected():
            await callback.answer("Forwarder is already running!", show_alert=True)
            return

    result = await bot_forwarder.start_client_for_user(user_id)
    if not result:
        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 Reconnect", callback_data="m_start_fwd")
        builder.button(text="⬅️ Back", callback_data="m_main")
        builder.adjust(2)
        await safe_edit(
            callback,
            "❌  *Failed to Start*\n\n"
            "Session may be expired.\n"
            "Use /start to re-authenticate.",
            parse_mode="Markdown",
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        return

    # Get task info for status display
    tasks = await get_tasks(user_id)
    enabled = sum(1 for t in tasks if t["enabled"])
    paused = sum(1 for t in tasks if t["paused"])

    builder = InlineKeyboardBuilder()
    builder.button(text="📡 Status", callback_data="m_fwd_status")
    builder.button(text="🏠 Menu", callback_data="m_main")
    builder.adjust(2)

    await safe_edit(
        callback,
        "▶️  *Forwarder Started!*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "✅ Session connected\n"
        "📋 {} task(s) active\n"
        "{}"
        "👂 Listening for messages...\n\n"
        "💡 Messages will be forwarded automatically.".format(
            enabled,
            "⏸ {} task(s) paused\n".format(paused) if paused else "",
        ),
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


# ─── Stop Forwarder ───


@router.callback_query(F.data == "m_stop_fwd")
async def cb_stop_fwd(callback: CallbackQuery):
    user_id = callback.from_user.id

    if user_id not in bot_forwarder.user_clients:
        await callback.answer("Forwarder is not running.", show_alert=True)
        return

    await bot_forwarder.stop_client_for_user(user_id)

    builder = InlineKeyboardBuilder()
    builder.button(text="▶️ Start Again", callback_data="m_start_fwd")
    builder.button(text="🏠 Menu", callback_data="m_main")
    builder.adjust(2)

    await safe_edit(
        callback,
        "⏹  *Forwarder Stopped*\n\n"
        "Your session is disconnected.\n"
        "Messages will not be forwarded.",
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


# ─── Forwarder Status ───


@router.callback_query(F.data == "m_fwd_status")
async def cb_fwd_status(callback: CallbackQuery):
    user_id = callback.from_user.id
    client = bot_forwarder.user_clients.get(user_id)
    connected = client is not None and client.is_connected()

    tasks = await get_tasks(user_id)
    enabled = [t for t in tasks if t["enabled"]]
    paused = [t for t in tasks if t["paused"]]

    stats = await get_statistics(user_id)
    total_msgs = sum(s.get("total_messages", 0) for s in stats)
    today_msgs = sum(s.get("today_count", 0) for s in stats)
    total_imgs = sum(s.get("total_images", 0) for s in stats)

    logs = bot_forwarder.get_user_logs(user_id, 5)
    recent_log = "\n".join("  `{}`".format(l) for l in logs) if logs else "  _No recent activity_"

    conn_icon = "🟢 Connected" if connected else "🔴 Disconnected"

    builder = InlineKeyboardBuilder()
    if connected:
        builder.button(text="⏹ Stop", callback_data="m_stop_fwd")
    else:
        builder.button(text="▶️ Start", callback_data="m_start_fwd")
    builder.button(text="🔄 Refresh", callback_data="m_fwd_status")
    builder.button(text="⬅️ Back", callback_data="cat_forwarder")
    builder.adjust(2, 1)

    await safe_edit(
        callback,
        "📡  *Forwarder Status*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "{conn}\n\n"
        "📋 Tasks: {enabled} active / {total} total\n"
        "{paused_line}"
        "📨 Today: {today} messages\n"
        "📊 All time: {all_time} messages, {imgs} images\n\n"
        "📝 *Recent Activity:*\n{logs}".format(
            conn=conn_icon,
            enabled=len(enabled),
            total=len(tasks),
            paused_line="⏸ Paused: {}\n".format(len(paused)) if paused else "",
            today=today_msgs,
            all_time=total_msgs,
            imgs=total_imgs,
            logs=recent_log,
        ),
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


# ─── Pause/Resume ───


@router.callback_query(F.data == "m_pause")
async def cb_menu_pause(callback: CallbackQuery):
    await show_tasks_submenu(callback, "pau", "⏸  *Pause / Resume*\n\nSelect a task:")


@router.callback_query(F.data.startswith("pau_"))
async def cb_pau_task(callback: CallbackQuery):
    task_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    task = await get_task(task_id, user_id)
    if not task:
        await callback.answer("Task not found.", show_alert=True)
        return

    new_paused = not task["paused"]
    await update_task_status(task_id, user_id, paused=new_paused)

    if not new_paused:
        bot_forwarder.clear_loop_counter(user_id, task_id)
        state = bot_forwarder.user_state.get(user_id, {})
        state.get("paused_ids", set()).discard(task_id)

    icon = "⏸" if new_paused else "▶️"
    status = "PAUSED" if new_paused else "RESUMED"
    await callback.answer("{} Task '{}' {}".format(icon, task["name"], status), show_alert=True)
    await show_tasks_submenu(callback, "pau", "⏸  *Pause / Resume*\n\nSelect a task:")


# ─── Logs ───


@router.callback_query(F.data == "m_logs")
async def cb_logs(callback: CallbackQuery):
    user_id = callback.from_user.id
    logs = bot_forwarder.get_user_logs(user_id, 30)

    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Refresh", callback_data="m_logs")
    builder.button(text="⬅️ Back", callback_data="cat_analytics")
    builder.adjust(2)

    if not logs:
        await safe_edit(
            callback,
            "📝  *Forwarder Logs*\n"
            "━━━━━━━━━━━━━━━\n\n"
            "_No logs yet. Start the forwarder and forward some messages._",
            parse_mode="Markdown",
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        return

    text = "📝  *Forwarder Logs*\n━━━━━━━━━━━━━━━\n\n```\n"
    for entry in logs:
        text += entry + "\n"
    text += "```"

    if len(text) > 4000:
        text = text[:3980] + "\n...```"

    await safe_edit(callback, text, parse_mode="Markdown", reply_markup=builder.as_markup())
    await callback.answer()
