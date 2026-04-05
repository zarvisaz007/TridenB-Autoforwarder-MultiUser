import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery

import bot_forwarder
from bot_database import update_task_status, get_task
from bot_handlers.menu import show_tasks_submenu

logger = logging.getLogger("bot.forwarder_ctl")
router = Router()


@router.callback_query(F.data == "m_get_id")
async def cb_get_id(callback: CallbackQuery):
    user_id = callback.from_user.id
    client = bot_forwarder.user_clients.get(user_id)

    if not client or not client.is_connected():
        await callback.message.answer("Your Telegram client is not connected. Start the forwarder first (option 8).")
        await callback.answer()
        return

    await callback.message.answer("Fetching your channels and groups...")
    await callback.answer()

    rows = []
    try:
        async for dialog in client.iter_dialogs():
            if dialog.is_channel or dialog.is_group:
                name = dialog.name or "(no name)"
                cid = dialog.entity.id
                if dialog.is_channel:
                    full_id = int(f"-100{cid}")
                else:
                    full_id = -cid if cid > 0 else cid
                rows.append((name, full_id))
    except Exception as e:
        logger.error(f"Error fetching dialogs for {user_id}: {e}")
        await callback.message.answer(f"Failed to fetch dialogs: `{e}`")
        return

    if not rows:
        await callback.message.answer("No channels or groups found.")
        return

    rows.sort(key=lambda r: r[0].lower())

    reply = "**Your Channels & Groups:**\n\n"
    for name, full_id in rows:
        line = f"**{name}**\n  ID: `{full_id}`\n\n"
        if len(reply) + len(line) > 4000:
            await callback.message.answer(reply, parse_mode="Markdown")
            reply = ""
        reply += line

    if reply:
        await callback.message.answer(reply, parse_mode="Markdown")


@router.callback_query(F.data == "m_start_fwd")
async def cb_start_fwd(callback: CallbackQuery):
    user_id = callback.from_user.id
    result = await bot_forwarder.start_client_for_user(user_id)
    if result:
        await callback.answer("Forwarder started!", show_alert=True)
    else:
        await callback.answer("Failed to start. Session may be expired — try /start to re-authenticate.", show_alert=True)


@router.callback_query(F.data == "m_stop_fwd")
async def cb_stop_fwd(callback: CallbackQuery):
    user_id = callback.from_user.id
    await bot_forwarder.stop_client_for_user(user_id)
    await callback.answer("Forwarder stopped!", show_alert=True)


@router.callback_query(F.data == "m_pause")
async def cb_menu_pause(callback: CallbackQuery):
    await show_tasks_submenu(callback, "pau", "Select a task to Pause/Resume:")


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

    status = "PAUSED" if new_paused else "RESUMED"
    await callback.answer(f"Task '{task['name']}' {status}.", show_alert=True)
    await show_tasks_submenu(callback, "pau", "Select a task to Pause/Resume:")


@router.callback_query(F.data == "m_logs")
async def cb_logs(callback: CallbackQuery):
    user_id = callback.from_user.id
    logs = bot_forwarder.get_user_logs(user_id, 30)

    if not logs:
        await callback.message.answer("No logs yet. Start the forwarder and forward some messages first.")
        await callback.answer()
        return

    text = "**Recent Logs:**\n```\n"
    for entry in logs:
        text += entry + "\n"
    text += "```"

    if len(text) > 4000:
        text = text[:3990] + "\n...```"

    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()
