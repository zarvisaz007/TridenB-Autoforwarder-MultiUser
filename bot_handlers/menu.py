import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

logger = logging.getLogger("bot.menu")
router = Router()


def get_main_menu_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="1. Get Channel ID", callback_data="m_get_id")
    builder.button(text="2. Create Task", callback_data="m_create")
    builder.button(text="3. List Tasks", callback_data="m_list")
    builder.button(text="4. Toggle Task", callback_data="m_toggle")
    builder.button(text="5. Edit Task", callback_data="m_edit")
    builder.button(text="6. Delete Task", callback_data="m_delete")
    builder.button(text="7. Duplicate Task", callback_data="m_duplicate")
    builder.button(text="─── Forwarder ───", callback_data="m_noop")
    builder.button(text="8. Start Forwarder", callback_data="m_start_fwd")
    builder.button(text="9. Stop Forwarder", callback_data="m_stop_fwd")
    builder.button(text="10. Pause/Resume", callback_data="m_pause")
    builder.button(text="─── Filters & AI ───", callback_data="m_noop")
    builder.button(text="11. Edit Filters", callback_data="m_filters")
    builder.button(text="12. AI Rewrite Config", callback_data="m_rewrite")
    builder.button(text="─── Analytics ───", callback_data="m_noop")
    builder.button(text="13. Statistics", callback_data="m_stats")
    builder.button(text="14. Message Threads", callback_data="m_threads")
    builder.button(text="15. View Logs", callback_data="m_logs")
    builder.button(text="16. AI Finance Reports", callback_data="m_reports")
    builder.button(text="─── Import/Export ───", callback_data="m_noop")
    builder.button(text="17. Export Tasks", callback_data="m_export")
    builder.button(text="18. Import Tasks", callback_data="m_import")
    builder.button(text="X Close Menu", callback_data="m_close")
    builder.adjust(1)
    return builder.as_markup()


async def show_main_menu(target):
    """Send main menu. target can be Message or CallbackQuery."""
    text = "**TridenB Autoforwarder** — Main Menu\nSelect an option:"
    kb = get_main_menu_kb()
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            await target.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await target.answer(text, reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data == "m_main")
async def cb_main(callback: CallbackQuery):
    await show_main_menu(callback)
    await callback.answer()


@router.callback_query(F.data == "m_noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data == "m_close")
async def cb_close(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer("Menu closed. Type /start to open again.")


async def show_tasks_submenu(callback: CallbackQuery, action_prefix: str, text: str, back_to="m_main"):
    from bot_database import get_tasks
    tasks = await get_tasks(callback.from_user.id)
    if not tasks:
        await callback.message.answer("You have no tasks yet. Create one first.")
        await callback.answer()
        return
    builder = InlineKeyboardBuilder()
    for t in tasks:
        status = "ON" if t["enabled"] else "OFF"
        pause = " [P]" if t["paused"] else ""
        builder.button(text=f"{t['name']} ({status}{pause})", callback_data=f"{action_prefix}_{t['id']}")
    builder.button(text="<< Back", callback_data=back_to)
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()
