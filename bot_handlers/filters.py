import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot_database import get_task, update_task_filters
from bot_handlers.menu import show_tasks_submenu

logger = logging.getLogger("bot.filters")
router = Router()

BOOLEAN_FILTERS = ["clean_urls", "clean_usernames", "skip_images", "skip_audio", "skip_videos"]
LIST_FILTERS = ["blacklist_words", "whitelist_words", "regex_blacklist", "clean_words", "regex_clean"]
NUMBER_FILTERS = ["delay_seconds", "image_delete_days"]

FILTER_LABELS = {
    "blacklist_words": "Blacklist Words",
    "whitelist_words": "Whitelist Words",
    "regex_blacklist": "Regex Blacklist",
    "clean_words": "Clean Words",
    "regex_clean": "Regex Clean",
    "clean_urls": "Clean URLs",
    "clean_usernames": "Clean @Usernames",
    "skip_images": "Skip Images",
    "skip_audio": "Skip Audio",
    "skip_videos": "Skip Videos",
    "delay_seconds": "Delay (seconds)",
    "image_delete_days": "Image Delete (days)",
    "rewrite_enabled": "AI Rewrite",
}


class FilterEditStates(StatesGroup):
    waiting_for_list_value = State()
    waiting_for_number_value = State()


def _build_filter_keyboard(task_id: int, filters: dict) -> InlineKeyboardBuilder:
    """Build the inline keyboard showing all filter options with current values."""
    builder = InlineKeyboardBuilder()

    builder.button(text="─── Boolean Filters ───", callback_data="m_noop")
    for key in BOOLEAN_FILTERS:
        status = "ON" if filters.get(key, False) else "OFF"
        label = FILTER_LABELS[key]
        builder.button(text=f"{label}: {status}", callback_data=f"ft_{task_id}_{key}")

    builder.button(text="─── List Filters ───", callback_data="m_noop")
    for key in LIST_FILTERS:
        items = filters.get(key, [])
        count = len(items) if items else 0
        display = f"{count} item{'s' if count != 1 else ''}" if count > 0 else "none"
        label = FILTER_LABELS[key]
        builder.button(text=f"{label}: [{display}]", callback_data=f"fl_{task_id}_{key}")

    builder.button(text="─── Number Filters ───", callback_data="m_noop")
    for key in NUMBER_FILTERS:
        value = filters.get(key, 0)
        label = FILTER_LABELS[key]
        builder.button(text=f"{label}: {value}", callback_data=f"fn_{task_id}_{key}")

    builder.button(text="─── AI Rewrite ───", callback_data="m_noop")
    rewrite_status = "ON" if filters.get("rewrite_enabled", False) else "OFF"
    builder.button(text=f"AI Rewrite: {rewrite_status} (use AI Rewrite Config menu)", callback_data="m_rewrite")

    builder.button(text="<< Back", callback_data="m_filters")
    builder.adjust(1)
    return builder


async def _show_filter_menu(callback_or_message, task: dict):
    """Build and display the filter menu for a task."""
    filters = task["filters"]
    text = f"**Filters for: {task['name']}**\nTap to toggle or edit:"
    kb = _build_filter_keyboard(task["id"], filters).as_markup()

    if isinstance(callback_or_message, CallbackQuery):
        try:
            await callback_or_message.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            await callback_or_message.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    elif isinstance(callback_or_message, Message):
        await callback_or_message.answer(text, reply_markup=kb, parse_mode="Markdown")


# ─── Entry: show task submenu ───

@router.callback_query(F.data == "m_filters")
async def cb_filters_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_tasks_submenu(callback, action_prefix="flt", text="Select a task to edit filters:")


# ─── Task selected: show filter keyboard ───

@router.callback_query(F.data.startswith("flt_"))
async def cb_filter_task_selected(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    task_id = int(callback.data.split("_", 1)[1])
    user_id = callback.from_user.id
    task = await get_task(task_id, user_id)
    if not task:
        await callback.answer("Task not found.", show_alert=True)
        return
    await _show_filter_menu(callback, task)
    await callback.answer()


# ─── Boolean toggle ───

@router.callback_query(F.data.regexp(r"^ft_\d+_.+$"))
async def cb_toggle_boolean(callback: CallbackQuery):
    parts = callback.data.split("_", 2)
    task_id = int(parts[1])
    filter_key = parts[2]
    user_id = callback.from_user.id

    if filter_key not in BOOLEAN_FILTERS:
        await callback.answer("Invalid filter.", show_alert=True)
        return

    task = await get_task(task_id, user_id)
    if not task:
        await callback.answer("Task not found.", show_alert=True)
        return

    filters = task["filters"]
    filters[filter_key] = not filters.get(filter_key, False)
    await update_task_filters(task_id, user_id, filters)

    task["filters"] = filters
    await _show_filter_menu(callback, task)
    status = "ON" if filters[filter_key] else "OFF"
    await callback.answer(f"{FILTER_LABELS[filter_key]}: {status}")


# ─── List filter: enter FSM ───

@router.callback_query(F.data.regexp(r"^fl_\d+_.+$"))
async def cb_edit_list_filter(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_", 2)
    task_id = int(parts[1])
    filter_key = parts[2]
    user_id = callback.from_user.id

    if filter_key not in LIST_FILTERS:
        await callback.answer("Invalid filter.", show_alert=True)
        return

    task = await get_task(task_id, user_id)
    if not task:
        await callback.answer("Task not found.", show_alert=True)
        return

    current = task["filters"].get(filter_key, [])
    current_display = ", ".join(current) if current else "none"

    await state.set_state(FilterEditStates.waiting_for_list_value)
    await state.update_data(task_id=task_id, filter_key=filter_key)

    label = FILTER_LABELS[filter_key]
    await callback.message.edit_text(
        f"**Edit: {label}**\n\n"
        f"Current: `{current_display}`\n\n"
        f"Send new values as a **comma-separated** list.\n"
        f"Example: `word1, word2, word3`\n\n"
        f"Send `clear` to remove all entries.\n"
        f"Send `cancel` to go back.",
        parse_mode="Markdown",
    )
    await callback.answer()


@router.message(FilterEditStates.waiting_for_list_value, ~F.text.startswith("/"))
async def process_list_value(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data["task_id"]
    filter_key = data["filter_key"]
    user_id = message.from_user.id

    text = message.text.strip()

    if text.lower() == "cancel":
        await state.clear()
        task = await get_task(task_id, user_id)
        if task:
            await _show_filter_menu(message, task)
        else:
            await message.answer("Task not found.")
        return

    if text.lower() == "clear":
        new_values = []
    else:
        new_values = [v.strip() for v in text.split(",") if v.strip()]

    task = await get_task(task_id, user_id)
    if not task:
        await state.clear()
        await message.answer("Task not found.")
        return

    filters = task["filters"]
    filters[filter_key] = new_values
    await update_task_filters(task_id, user_id, filters)
    await state.clear()

    task["filters"] = filters
    label = FILTER_LABELS[filter_key]
    count = len(new_values)
    if count > 0:
        await message.answer(f"{label} updated: {count} item{'s' if count != 1 else ''}.")
    else:
        await message.answer(f"{label} cleared.")

    await _show_filter_menu(message, task)


# ─── Number filter: enter FSM ───

@router.callback_query(F.data.regexp(r"^fn_\d+_.+$"))
async def cb_edit_number_filter(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_", 2)
    task_id = int(parts[1])
    filter_key = parts[2]
    user_id = callback.from_user.id

    if filter_key not in NUMBER_FILTERS:
        await callback.answer("Invalid filter.", show_alert=True)
        return

    task = await get_task(task_id, user_id)
    if not task:
        await callback.answer("Task not found.", show_alert=True)
        return

    current = task["filters"].get(filter_key, 0)

    await state.set_state(FilterEditStates.waiting_for_number_value)
    await state.update_data(task_id=task_id, filter_key=filter_key)

    label = FILTER_LABELS[filter_key]
    await callback.message.edit_text(
        f"**Edit: {label}**\n\n"
        f"Current value: `{current}`\n\n"
        f"Send a new number (integer, 0 or above).\n"
        f"Send `cancel` to go back.",
        parse_mode="Markdown",
    )
    await callback.answer()


@router.message(FilterEditStates.waiting_for_number_value, ~F.text.startswith("/"))
async def process_number_value(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data["task_id"]
    filter_key = data["filter_key"]
    user_id = message.from_user.id

    text = message.text.strip()

    if text.lower() == "cancel":
        await state.clear()
        task = await get_task(task_id, user_id)
        if task:
            await _show_filter_menu(message, task)
        else:
            await message.answer("Task not found.")
        return

    try:
        value = int(text)
        if value < 0:
            raise ValueError
    except ValueError:
        await message.answer("Please enter a valid non-negative integer, or `cancel` to go back.", parse_mode="Markdown")
        return

    task = await get_task(task_id, user_id)
    if not task:
        await state.clear()
        await message.answer("Task not found.")
        return

    filters = task["filters"]
    filters[filter_key] = value
    await update_task_filters(task_id, user_id, filters)
    await state.clear()

    task["filters"] = filters
    label = FILTER_LABELS[filter_key]
    await message.answer(f"{label} set to `{value}`.", parse_mode="Markdown")
    await _show_filter_menu(message, task)
