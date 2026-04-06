import re
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
    waiting_for_replacement_pairs = State()


def _cancel_kb(task_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Cancel", callback_data=f"flt_{task_id}")
    return kb.as_markup()


def _build_filter_keyboard(task_id: int, filters: dict) -> InlineKeyboardBuilder:
    """Build the inline keyboard showing all filter options with current values."""
    builder = InlineKeyboardBuilder()

    builder.button(text="━━ Toggle Filters ━━", callback_data="m_noop")
    for key in BOOLEAN_FILTERS:
        status = "ON" if filters.get(key, False) else "OFF"
        label = FILTER_LABELS[key]
        builder.button(text=f"{label}: {status}", callback_data=f"ft_{task_id}_{key}")

    builder.button(text="━━ List Filters ━━", callback_data="m_noop")
    for key in LIST_FILTERS:
        items = filters.get(key, [])
        count = len(items) if items else 0
        display = f"{count} item{'s' if count != 1 else ''}" if count > 0 else "none"
        label = FILTER_LABELS[key]
        builder.button(text=f"{label}: [{display}]", callback_data=f"fl_{task_id}_{key}")

    builder.button(text="━━ Number Filters ━━", callback_data="m_noop")
    for key in NUMBER_FILTERS:
        value = filters.get(key, 0)
        label = FILTER_LABELS[key]
        builder.button(text=f"{label}: {value}", callback_data=f"fn_{task_id}_{key}")

    # Replacements section
    rep = filters.get("replacements", {})
    rep_enabled = rep.get("enabled", False)
    rep_status = "ON" if rep_enabled else "OFF"
    total_rules = (
        len(rep.get("usernames", {})) + len(rep.get("words", {}))
        + len(rep.get("urls", {}).get("domain_map", {}))
        + len(rep.get("phones", {})) + len(rep.get("channel_links", {}))
    )
    builder.button(text="━━ Replacements ━━", callback_data="m_noop")
    builder.button(text=f"Replacements: {rep_status} ({total_rules} rules)", callback_data=f"fr_{task_id}")

    builder.button(text="━━ AI Rewrite ━━", callback_data="m_noop")
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
    await show_tasks_submenu(callback, action_prefix="flt", text="🎛  *Edit Filters*\n\nSelect a task:", back_to="cat_filters")


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
        reply_markup=_cancel_kb(task_id),
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

    # Fix 4: cap entry count and per-entry length for all list filters
    MAX_LIST_ENTRIES = 100
    MAX_ENTRY_LEN = 200
    if len(new_values) > MAX_LIST_ENTRIES:
        await message.answer(
            f"Too many entries. Maximum allowed is {MAX_LIST_ENTRIES}. Please reduce the list and try again."
        )
        return
    for entry in new_values:
        if len(entry) > MAX_ENTRY_LEN:
            await message.answer(
                f"Entry too long: `{entry[:40]}...`\n"
                f"Maximum {MAX_ENTRY_LEN} characters per entry.",
                parse_mode="Markdown",
            )
            return

    # Fix 1: validate regex patterns for regex_* keys
    if filter_key.startswith("regex_") and new_values:
        MAX_REGEX_ENTRIES = 20
        if len(new_values) > MAX_REGEX_ENTRIES:
            await message.answer(
                f"Too many regex patterns. Maximum allowed is {MAX_REGEX_ENTRIES}."
            )
            return
        for pattern in new_values:
            if len(pattern) > MAX_ENTRY_LEN:
                await message.answer(
                    f"Regex pattern too long: `{pattern[:40]}...`\n"
                    f"Maximum {MAX_ENTRY_LEN} characters per pattern.",
                    parse_mode="Markdown",
                )
                return
            try:
                re.compile(pattern)
            except re.error as exc:
                await message.answer(
                    f"Invalid regex pattern: `{pattern}`\nError: {exc}\n\nPlease fix and try again.",
                    parse_mode="Markdown",
                )
                return

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
        reply_markup=_cancel_kb(task_id),
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

    # Fix 2: cap delay_seconds at 3600 (1 hour)
    if filter_key == "delay_seconds" and value > 3600:
        await message.answer(
            "Maximum delay is `3600` seconds (1 hour). Please enter a value between 0 and 3600.",
            parse_mode="Markdown",
        )
        return

    # Fix 3: cap image_delete_days at 365
    if filter_key == "image_delete_days" and value > 365:
        await message.answer(
            "Maximum is `365` days. Please enter a value between 0 and 365.",
            parse_mode="Markdown",
        )
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


# ─── Replacements Submenu ───

REPLACEMENT_CATEGORIES = {
    "usernames": ("@Username Mappings", "@old_name:@new_name"),
    "words": ("Word/Phrase Mappings", "OldBrand:NewBrand"),
    "url_domains": ("URL Domain Rules", "cosmofeed.com:https://mysite.com/page"),
    "phones": ("Phone Mappings", "+911234567890:+919876543210"),
    "channel_links": ("Channel Link Mappings", "old_group:new_group"),
}


def _build_replacement_keyboard(task_id: int, rep: dict) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    enabled = rep.get("enabled", False)
    builder.button(
        text=f"{'🟢' if enabled else '🔴'} Replacements: {'ON' if enabled else 'OFF'}",
        callback_data=f"frt_{task_id}",
    )
    builder.button(
        text=f"@Usernames ({len(rep.get('usernames', {}))})",
        callback_data=f"fre_{task_id}_usernames",
    )
    builder.button(
        text=f"Words/Phrases ({len(rep.get('words', {}))})",
        callback_data=f"fre_{task_id}_words",
    )
    dm = rep.get("urls", {}).get("domain_map", {})
    builder.button(
        text=f"URL Domains ({len(dm)})",
        callback_data=f"fre_{task_id}_url_domains",
    )
    rm_unmatched = rep.get("urls", {}).get("remove_unmatched", False)
    builder.button(
        text=f"Remove Unmatched URLs: {'ON' if rm_unmatched else 'OFF'}",
        callback_data=f"fru_{task_id}",
    )
    builder.button(
        text=f"Phones ({len(rep.get('phones', {}))})",
        callback_data=f"fre_{task_id}_phones",
    )
    builder.button(
        text=f"Channel Links ({len(rep.get('channel_links', {}))})",
        callback_data=f"fre_{task_id}_channel_links",
    )
    builder.button(text="🗑 Clear All Replacements", callback_data=f"frc_{task_id}")
    builder.button(text="<< Back to Filters", callback_data=f"flt_{task_id}")
    builder.adjust(1)
    return builder


async def _show_replacement_menu(target, task: dict):
    rep = task["filters"].get("replacements", {})
    text = (
        f"🔄  *Replacements — {task['name']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Swap usernames, words, URLs, phones, and\n"
        f"channel links before forwarding.\n\n"
        f"Replacements run *after* word cleaning but\n"
        f"*before* Remove URLs / Remove @Usernames."
    )
    kb = _build_replacement_keyboard(task["id"], rep).as_markup()
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            await target.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    elif isinstance(target, Message):
        await target.answer(text, reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data.regexp(r"^fr_\d+$"))
async def cb_replacement_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    task_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    task = await get_task(task_id, user_id)
    if not task:
        await callback.answer("Task not found.", show_alert=True)
        return
    await _show_replacement_menu(callback, task)
    await callback.answer()


@router.callback_query(F.data.regexp(r"^frt_\d+$"))
async def cb_toggle_replacements(callback: CallbackQuery):
    task_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    task = await get_task(task_id, user_id)
    if not task:
        await callback.answer("Task not found.", show_alert=True)
        return
    filters = task["filters"]
    rep = filters.setdefault("replacements", {"enabled": False, "usernames": {}, "words": {}, "urls": {"domain_map": {}, "remove_unmatched": False}, "phones": {}, "channel_links": {}})
    rep["enabled"] = not rep.get("enabled", False)
    await update_task_filters(task_id, user_id, filters)
    task["filters"] = filters
    status = "ON" if rep["enabled"] else "OFF"
    await _show_replacement_menu(callback, task)
    await callback.answer(f"Replacements: {status}")


@router.callback_query(F.data.regexp(r"^fru_\d+$"))
async def cb_toggle_remove_unmatched(callback: CallbackQuery):
    task_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    task = await get_task(task_id, user_id)
    if not task:
        await callback.answer("Task not found.", show_alert=True)
        return
    filters = task["filters"]
    rep = filters.setdefault("replacements", {"enabled": False, "usernames": {}, "words": {}, "urls": {"domain_map": {}, "remove_unmatched": False}, "phones": {}, "channel_links": {}})
    urls = rep.setdefault("urls", {"domain_map": {}, "remove_unmatched": False})
    urls["remove_unmatched"] = not urls.get("remove_unmatched", False)
    await update_task_filters(task_id, user_id, filters)
    task["filters"] = filters
    status = "ON" if urls["remove_unmatched"] else "OFF"
    await _show_replacement_menu(callback, task)
    await callback.answer(f"Remove Unmatched URLs: {status}")


@router.callback_query(F.data.regexp(r"^fre_\d+_.+$"))
async def cb_edit_replacement_category(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_", 2)
    task_id = int(parts[1])
    category = parts[2]
    user_id = callback.from_user.id

    if category not in REPLACEMENT_CATEGORIES:
        await callback.answer("Invalid category.", show_alert=True)
        return

    task = await get_task(task_id, user_id)
    if not task:
        await callback.answer("Task not found.", show_alert=True)
        return

    label, example = REPLACEMENT_CATEGORIES[category]
    rep = task["filters"].get("replacements", {})

    if category == "url_domains":
        current_map = rep.get("urls", {}).get("domain_map", {})
    else:
        current_map = rep.get(category, {})

    if current_map:
        current_display = "\n".join(f"  `{k}` → `{v}`" for k, v in current_map.items())
    else:
        current_display = "  _none_"

    await state.set_state(FilterEditStates.waiting_for_replacement_pairs)
    await state.update_data(task_id=task_id, category=category)

    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Cancel", callback_data=f"fr_{task_id}")

    await callback.message.edit_text(
        f"**Edit: {label}**\n\n"
        f"Current mappings:\n{current_display}\n\n"
        f"Send new mappings as comma-separated `old:new` pairs.\n"
        f"Example: `{example}`\n\n"
        f"Send `clear` to remove all.\n"
        f"Send `cancel` to go back.",
        parse_mode="Markdown",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.message(FilterEditStates.waiting_for_replacement_pairs, ~F.text.startswith("/"))
async def process_replacement_pairs(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data["task_id"]
    category = data["category"]
    user_id = message.from_user.id
    text = message.text.strip()

    if text.lower() == "cancel":
        await state.clear()
        task = await get_task(task_id, user_id)
        if task:
            await _show_replacement_menu(message, task)
        return

    task = await get_task(task_id, user_id)
    if not task:
        await state.clear()
        await message.answer("Task not found.")
        return

    filters = task["filters"]
    rep = filters.setdefault("replacements", {"enabled": False, "usernames": {}, "words": {}, "urls": {"domain_map": {}, "remove_unmatched": False}, "phones": {}, "channel_links": {}})

    if text.lower() == "clear":
        if category == "url_domains":
            rep.setdefault("urls", {})["domain_map"] = {}
        else:
            rep[category] = {}
        await update_task_filters(task_id, user_id, filters)
        await state.clear()
        label = REPLACEMENT_CATEGORIES[category][0]
        await message.answer(f"{label} cleared.")
        task["filters"] = filters
        await _show_replacement_menu(message, task)
        return

    # Parse old:new pairs
    pairs = [p.strip() for p in text.split(",") if p.strip()]
    if len(pairs) > 50:
        await message.answer("Too many pairs. Maximum 50 at a time.")
        return

    new_map = {}
    for pair in pairs:
        if ":" not in pair:
            await message.answer(
                f"Invalid format: `{pair}`\n\n"
                f"Use `old:new` format separated by commas.",
                parse_mode="Markdown",
            )
            return
        key, value = pair.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            await message.answer("Empty key in pair — please fix and resend.")
            return
        new_map[key] = value

    if category == "url_domains":
        rep.setdefault("urls", {})["domain_map"] = new_map
    else:
        rep[category] = new_map

    await update_task_filters(task_id, user_id, filters)
    await state.clear()

    label = REPLACEMENT_CATEGORIES[category][0]
    await message.answer(f"{label} updated: {len(new_map)} mapping{'s' if len(new_map) != 1 else ''}.")
    task["filters"] = filters
    await _show_replacement_menu(message, task)


@router.callback_query(F.data.regexp(r"^frc_\d+$"))
async def cb_clear_all_replacements(callback: CallbackQuery):
    task_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    task = await get_task(task_id, user_id)
    if not task:
        await callback.answer("Task not found.", show_alert=True)
        return
    filters = task["filters"]
    filters["replacements"] = {
        "enabled": False,
        "usernames": {},
        "words": {},
        "urls": {"domain_map": {}, "remove_unmatched": False},
        "phones": {},
        "channel_links": {},
    }
    await update_task_filters(task_id, user_id, filters)
    task["filters"] = filters
    await _show_replacement_menu(callback, task)
    await callback.answer("All replacements cleared.")
