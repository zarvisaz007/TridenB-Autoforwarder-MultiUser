import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot_database import get_task, update_task_filters
from bot_handlers.menu import show_tasks_submenu

logger = logging.getLogger("bot.rewriting")
router = Router()


class RewriteStates(StatesGroup):
    waiting_for_prompt = State()


@router.callback_query(F.data == "m_rewrite")
async def cb_menu_rewrite(callback: CallbackQuery):
    await show_tasks_submenu(callback, "rew", "🤖  *AI Rewrite Config*\n\nSelect a task:", back_to="cat_filters")


@router.callback_query(F.data.startswith("rew_") & ~F.data.startswith("rewt_") & ~F.data.startswith("rewp_"))
async def cb_rew_task(callback: CallbackQuery):
    task_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    task = await get_task(task_id, user_id)
    if not task:
        await callback.answer("Task not found.", show_alert=True)
        return
    await _show_rewrite_menu(callback, task)


async def _show_rewrite_menu(callback: CallbackQuery, task: dict):
    filters = task["filters"]
    enabled = filters.get("rewrite_enabled", False)
    prompt = filters.get("rewrite_prompt", "") or "Default"

    status = "ON" if enabled else "OFF"
    prompt_preview = prompt[:80] + "..." if len(prompt) > 80 else prompt

    text = (
        f"🤖  *AI Rewrite — {task['name']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Status: **{status}**\n"
        f"Prompt: `{prompt_preview}`"
    )

    builder = InlineKeyboardBuilder()
    toggle_text = "Turn OFF" if enabled else "Turn ON"
    builder.button(text=toggle_text, callback_data=f"rewt_{task['id']}")
    builder.button(text="Change Prompt", callback_data=f"rewp_{task['id']}")
    builder.button(text="⬅️ Back", callback_data="m_rewrite")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("rewt_"))
async def cb_rew_toggle(callback: CallbackQuery):
    task_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    task = await get_task(task_id, user_id)
    if not task:
        await callback.answer("Task not found.", show_alert=True)
        return

    filters = task["filters"]
    filters["rewrite_enabled"] = not filters.get("rewrite_enabled", False)
    await update_task_filters(task_id, user_id, filters)

    task["filters"] = filters
    await _show_rewrite_menu(callback, task)


@router.callback_query(F.data.startswith("rewp_"))
async def cb_rew_prompt(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.split("_")[1])
    await state.update_data(rewrite_task_id=task_id)
    await callback.message.answer(
        "Type your new rewrite prompt.\n\n"
        "Example: `Paraphrase to avoid copyright claims`\n\n"
        "Send `clear` to reset to default.",
        parse_mode="Markdown"
    )
    await state.set_state(RewriteStates.waiting_for_prompt)
    await callback.answer()


@router.message(RewriteStates.waiting_for_prompt, ~F.text.startswith('/'))
async def process_rewrite_prompt(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("rewrite_task_id")
    user_id = message.from_user.id

    task = await get_task(task_id, user_id)
    if not task:
        await message.answer("Task not found.")
        await state.clear()
        return

    prompt_text = message.text.strip()
    if prompt_text.lower() == "clear":
        prompt_text = ""

    filters = task["filters"]
    filters["rewrite_prompt"] = prompt_text
    await update_task_filters(task_id, user_id, filters)

    await state.clear()

    display = prompt_text or "Default"
    await message.answer(f"Rewrite prompt updated: `{display}`", parse_mode="Markdown")

    from bot_handlers.menu import show_main_menu
    await show_main_menu(message)
