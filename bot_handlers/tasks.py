import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot_database import (
    create_task,
    get_tasks,
    get_task,
    update_task_status,
    delete_task,
    update_task_field,
    DEFAULT_FILTERS,
)
from bot_handlers.menu import show_tasks_submenu, show_main_menu

logger = logging.getLogger("bot.tasks")
router = Router()


# ─── FSM States ───


class TaskCreateStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_source = State()
    waiting_for_destinations = State()


class TaskEditStates(StatesGroup):
    choosing_field = State()
    waiting_for_name = State()
    waiting_for_source = State()
    waiting_for_add_dests = State()
    waiting_for_remove_dests = State()


# ─── Helpers ───


def _parse_channel_id(text: str):
    """Parse a channel ID from user input. Accepts plain int or -100 prefixed."""
    text = text.strip()
    try:
        return int(text)
    except ValueError:
        return None


def _parse_channel_ids(text: str):
    """Parse comma/space/newline separated channel IDs."""
    raw = text.replace(",", " ").replace("\n", " ").split()
    ids = []
    for token in raw:
        cid = _parse_channel_id(token)
        if cid is None:
            return None
        ids.append(cid)
    return ids if ids else None


def _format_filter_tags(filters: dict) -> str:
    """Build a compact string of active filter indicators."""
    tags = []
    if filters.get("blacklist_words"):
        tags.append("BL")
    if filters.get("whitelist_words"):
        tags.append("WL")
    if filters.get("regex_blacklist"):
        tags.append("RX")
    if filters.get("clean_words"):
        tags.append("CW")
    if filters.get("regex_clean"):
        tags.append("RC")
    if filters.get("clean_urls"):
        tags.append("NoURL")
    if filters.get("clean_usernames"):
        tags.append("NoUser")
    if filters.get("skip_images"):
        tags.append("NoImg")
    if filters.get("skip_audio"):
        tags.append("NoAud")
    if filters.get("skip_videos"):
        tags.append("NoVid")
    if filters.get("delay_seconds"):
        tags.append(f"D:{filters['delay_seconds']}s")
    if filters.get("image_delete_days"):
        tags.append(f"ImgDel:{filters['image_delete_days']}d")
    if filters.get("rewrite_enabled"):
        tags.append("AI")
    return " ".join(tags) if tags else "none"


def _cancel_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Cancel", callback_data="m_main")
    builder.adjust(1)
    return builder.as_markup()


# ─── Create Task ───


@router.callback_query(F.data == "m_create")
async def cb_create_task(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(TaskCreateStates.waiting_for_name)
    await callback.message.edit_text(
        "**Create Task** (Step 1/3)\n\nSend the *task name*:",
        parse_mode="Markdown",
        reply_markup=_cancel_kb(),
    )
    await callback.answer()


@router.message(TaskCreateStates.waiting_for_name, ~F.text.startswith("/"))
async def fsm_create_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("Name cannot be empty. Try again:")
        return
    await state.update_data(task_name=name)
    await state.set_state(TaskCreateStates.waiting_for_source)
    await message.answer(
        "**Create Task** (Step 2/3)\n\n"
        f"Task name: `{name}`\n\n"
        "Send the *source channel ID* (e.g. `-1001234567890`):",
        parse_mode="Markdown",
        reply_markup=_cancel_kb(),
    )


@router.message(TaskCreateStates.waiting_for_source, ~F.text.startswith("/"))
async def fsm_create_source(message: Message, state: FSMContext):
    cid = _parse_channel_id(message.text)
    if cid is None:
        await message.answer("Invalid channel ID. Send a numeric ID:")
        return
    await state.update_data(source_id=cid)
    await state.set_state(TaskCreateStates.waiting_for_destinations)
    await message.answer(
        "**Create Task** (Step 3/3)\n\n"
        f"Source: `{cid}`\n\n"
        "Send *destination channel IDs* (comma or space separated).\n"
        "You can send multiple, e.g. `-1001111111111, -1002222222222`:",
        parse_mode="Markdown",
        reply_markup=_cancel_kb(),
    )


@router.message(TaskCreateStates.waiting_for_destinations, ~F.text.startswith("/"))
async def fsm_create_destinations(message: Message, state: FSMContext):
    dest_ids = _parse_channel_ids(message.text)
    if dest_ids is None:
        await message.answer("Invalid input. Send numeric channel IDs separated by commas or spaces:")
        return
    data = await state.get_data()
    task_name = data["task_name"]
    source_id = data["source_id"]

    task_id = await create_task(
        user_id=message.from_user.id,
        name=task_name,
        source=source_id,
        destinations=dest_ids,
        filters=dict(DEFAULT_FILTERS),
    )
    await state.clear()

    dest_str = ", ".join(f"`{d}`" for d in dest_ids)
    await message.answer(
        f"Task *{task_name}* created (ID: `{task_id}`)\n\n"
        f"Source: `{source_id}`\n"
        f"Destinations: {dest_str}\n"
        f"Status: Enabled\n\n"
        "Use the main menu to edit filters or start the forwarder.",
        parse_mode="Markdown",
    )
    await show_main_menu(message)


# ─── List Tasks ───


@router.callback_query(F.data == "m_list")
async def cb_list_tasks(callback: CallbackQuery):
    tasks = await get_tasks(callback.from_user.id)
    if not tasks:
        await callback.message.answer("You have no tasks. Create one first!")
        await callback.answer()
        return

    lines = ["**Your Tasks**\n"]
    for t in tasks:
        status_icon = "ON" if t["enabled"] else "OFF"
        pause_icon = " | PAUSED" if t["paused"] else ""
        dests = ", ".join(str(d) for d in t["destination_channel_ids"])
        filter_tags = _format_filter_tags(t["filters"])
        lines.append(
            f"*{t['id']}.* `{t['name']}`  [{status_icon}{pause_icon}]\n"
            f"   Src: `{t['source_channel_id']}`\n"
            f"   Dst: `{dests}`\n"
            f"   Filters: {filter_tags}\n"
        )

    builder = InlineKeyboardBuilder()
    builder.button(text="<< Back", callback_data="m_main")
    builder.adjust(1)

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


# ─── Toggle Task ───


@router.callback_query(F.data == "m_toggle")
async def cb_toggle_menu(callback: CallbackQuery):
    await show_tasks_submenu(callback, "tog", "**Toggle Task** — Select a task:")


@router.callback_query(F.data.startswith("tog_"))
async def cb_toggle_task(callback: CallbackQuery):
    task_id = int(callback.data.split("_", 1)[1])
    user_id = callback.from_user.id
    task = await get_task(task_id, user_id)
    if not task:
        await callback.answer("Task not found.", show_alert=True)
        return

    new_status = not task["enabled"]
    await update_task_status(task_id, user_id, enabled=new_status)
    label = "ENABLED" if new_status else "DISABLED"
    await callback.message.answer(
        f"Task *{task['name']}* is now *{label}*.",
        parse_mode="Markdown",
    )
    await callback.answer(f"Task {label}")
    await show_main_menu(callback)


# ─── Delete Task ───


@router.callback_query(F.data == "m_delete")
async def cb_delete_menu(callback: CallbackQuery):
    await show_tasks_submenu(callback, "del", "**Delete Task** — Select a task to delete:")


@router.callback_query(F.data.startswith("del_"))
async def cb_delete_task(callback: CallbackQuery):
    task_id = int(callback.data.split("_", 1)[1])
    user_id = callback.from_user.id
    task = await get_task(task_id, user_id)
    if not task:
        await callback.answer("Task not found.", show_alert=True)
        return

    await delete_task(task_id, user_id)
    await callback.message.answer(
        f"Task *{task['name']}* (ID: `{task_id}`) has been deleted.",
        parse_mode="Markdown",
    )
    await callback.answer("Task deleted")
    await show_main_menu(callback)


# ─── Duplicate Task ───


@router.callback_query(F.data == "m_duplicate")
async def cb_duplicate_menu(callback: CallbackQuery):
    await show_tasks_submenu(callback, "dup", "**Duplicate Task** — Select a task to duplicate:")


@router.callback_query(F.data.startswith("dup_"))
async def cb_duplicate_task(callback: CallbackQuery):
    task_id = int(callback.data.split("_", 1)[1])
    user_id = callback.from_user.id
    task = await get_task(task_id, user_id)
    if not task:
        await callback.answer("Task not found.", show_alert=True)
        return

    new_name = f"{task['name']} (copy)"
    new_id = await create_task(
        user_id=user_id,
        name=new_name,
        source=task["source_channel_id"],
        destinations=list(task["destination_channel_ids"]),
        filters=dict(task["filters"]),
    )
    await callback.message.answer(
        f"Task duplicated as *{new_name}* (ID: `{new_id}`).",
        parse_mode="Markdown",
    )
    await callback.answer("Task duplicated")
    await show_main_menu(callback)


# ─── Edit Task ───


@router.callback_query(F.data == "m_edit")
async def cb_edit_menu(callback: CallbackQuery):
    await show_tasks_submenu(callback, "edt", "**Edit Task** — Select a task to edit:")


@router.callback_query(F.data.startswith("edt_") & ~F.data.startswith("edtf_"))
async def cb_edit_task_choose_field(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.split("_", 1)[1])
    user_id = callback.from_user.id
    task = await get_task(task_id, user_id)
    if not task:
        await callback.answer("Task not found.", show_alert=True)
        return

    await state.clear()
    await state.update_data(edit_task_id=task_id)
    await state.set_state(TaskEditStates.choosing_field)

    dests = ", ".join(str(d) for d in task["destination_channel_ids"])
    builder = InlineKeyboardBuilder()
    builder.button(text="Edit Name", callback_data=f"edtf_{task_id}_name")
    builder.button(text="Edit Source", callback_data=f"edtf_{task_id}_source")
    builder.button(text="Add Destinations", callback_data=f"edtf_{task_id}_add_dest")
    builder.button(text="Remove Destinations", callback_data=f"edtf_{task_id}_rm_dest")
    builder.button(text="<< Back", callback_data="m_edit")
    builder.adjust(1)

    await callback.message.edit_text(
        f"**Edit Task:** `{task['name']}`\n\n"
        f"Name: `{task['name']}`\n"
        f"Source: `{task['source_channel_id']}`\n"
        f"Destinations: `{dests}`\n\n"
        "Choose what to edit:",
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


# ── Edit Name ──


@router.callback_query(F.data.regexp(r"^edtf_(\d+)_name$"))
async def cb_edit_name(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.split("_")[1])
    await state.update_data(edit_task_id=task_id)
    await state.set_state(TaskEditStates.waiting_for_name)
    await callback.message.edit_text(
        "Send the *new task name*:",
        parse_mode="Markdown",
        reply_markup=_cancel_kb(),
    )
    await callback.answer()


@router.message(TaskEditStates.waiting_for_name, ~F.text.startswith("/"))
async def fsm_edit_name(message: Message, state: FSMContext):
    new_name = message.text.strip()
    if not new_name:
        await message.answer("Name cannot be empty. Try again:")
        return
    data = await state.get_data()
    task_id = data["edit_task_id"]
    user_id = message.from_user.id

    await update_task_field(task_id, user_id, name=new_name)
    await state.clear()
    await message.answer(
        f"Task name updated to *{new_name}*.",
        parse_mode="Markdown",
    )
    await show_main_menu(message)


# ── Edit Source ──


@router.callback_query(F.data.regexp(r"^edtf_(\d+)_source$"))
async def cb_edit_source(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.split("_")[1])
    await state.update_data(edit_task_id=task_id)
    await state.set_state(TaskEditStates.waiting_for_source)
    await callback.message.edit_text(
        "Send the *new source channel ID*:",
        parse_mode="Markdown",
        reply_markup=_cancel_kb(),
    )
    await callback.answer()


@router.message(TaskEditStates.waiting_for_source, ~F.text.startswith("/"))
async def fsm_edit_source(message: Message, state: FSMContext):
    cid = _parse_channel_id(message.text)
    if cid is None:
        await message.answer("Invalid channel ID. Send a numeric ID:")
        return
    data = await state.get_data()
    task_id = data["edit_task_id"]
    user_id = message.from_user.id

    await update_task_field(task_id, user_id, source_channel_id=cid)
    await state.clear()
    await message.answer(
        f"Source channel updated to `{cid}`.",
        parse_mode="Markdown",
    )
    await show_main_menu(message)


# ── Add Destinations ──


@router.callback_query(F.data.regexp(r"^edtf_(\d+)_add_dest$"))
async def cb_edit_add_dest(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.split("_")[1])
    await state.update_data(edit_task_id=task_id)
    await state.set_state(TaskEditStates.waiting_for_add_dests)
    await callback.message.edit_text(
        "Send *destination channel IDs to add* (comma or space separated):",
        parse_mode="Markdown",
        reply_markup=_cancel_kb(),
    )
    await callback.answer()


@router.message(TaskEditStates.waiting_for_add_dests, ~F.text.startswith("/"))
async def fsm_edit_add_dests(message: Message, state: FSMContext):
    new_ids = _parse_channel_ids(message.text)
    if new_ids is None:
        await message.answer("Invalid input. Send numeric channel IDs separated by commas or spaces:")
        return
    data = await state.get_data()
    task_id = data["edit_task_id"]
    user_id = message.from_user.id

    task = await get_task(task_id, user_id)
    if not task:
        await state.clear()
        await message.answer("Task not found.")
        return

    existing = list(task["destination_channel_ids"])
    added = []
    for cid in new_ids:
        if cid not in existing:
            existing.append(cid)
            added.append(cid)

    await update_task_field(task_id, user_id, destination_channel_ids=existing)
    await state.clear()

    if added:
        added_str = ", ".join(f"`{d}`" for d in added)
        await message.answer(
            f"Added destinations: {added_str}\n"
            f"Total destinations: {len(existing)}",
            parse_mode="Markdown",
        )
    else:
        await message.answer("All provided IDs were already in the destination list. No changes made.")
    await show_main_menu(message)


# ── Remove Destinations ──


@router.callback_query(F.data.regexp(r"^edtf_(\d+)_rm_dest$"))
async def cb_edit_rm_dest(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    task = await get_task(task_id, user_id)
    if not task:
        await callback.answer("Task not found.", show_alert=True)
        return

    dests = task["destination_channel_ids"]
    if not dests:
        await callback.answer("No destinations to remove.", show_alert=True)
        return

    await state.update_data(edit_task_id=task_id)
    await state.set_state(TaskEditStates.waiting_for_remove_dests)

    dest_list = "\n".join(f"  `{d}`" for d in dests)
    await callback.message.edit_text(
        f"Current destinations:\n{dest_list}\n\n"
        "Send the *channel IDs to remove* (comma or space separated):",
        parse_mode="Markdown",
        reply_markup=_cancel_kb(),
    )
    await callback.answer()


@router.message(TaskEditStates.waiting_for_remove_dests, ~F.text.startswith("/"))
async def fsm_edit_rm_dests(message: Message, state: FSMContext):
    rm_ids = _parse_channel_ids(message.text)
    if rm_ids is None:
        await message.answer("Invalid input. Send numeric channel IDs separated by commas or spaces:")
        return
    data = await state.get_data()
    task_id = data["edit_task_id"]
    user_id = message.from_user.id

    task = await get_task(task_id, user_id)
    if not task:
        await state.clear()
        await message.answer("Task not found.")
        return

    existing = list(task["destination_channel_ids"])
    removed = []
    for cid in rm_ids:
        if cid in existing:
            existing.remove(cid)
            removed.append(cid)

    if not existing:
        await message.answer(
            "Cannot remove all destinations. A task must have at least one destination.\n"
            "Remove the task instead, or try again with fewer IDs."
        )
        return

    await update_task_field(task_id, user_id, destination_channel_ids=existing)
    await state.clear()

    if removed:
        removed_str = ", ".join(f"`{d}`" for d in removed)
        await message.answer(
            f"Removed destinations: {removed_str}\n"
            f"Remaining destinations: {len(existing)}",
            parse_mode="Markdown",
        )
    else:
        await message.answer("None of the provided IDs were in the destination list. No changes made.")
    await show_main_menu(message)
