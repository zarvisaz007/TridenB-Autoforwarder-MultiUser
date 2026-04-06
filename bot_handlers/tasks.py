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


def _parse_channel_id(text):
    text = text.strip()
    try:
        return int(text)
    except ValueError:
        return None


def _parse_channel_ids(text):
    raw = text.replace(",", " ").replace("\n", " ").split()
    ids = []
    for token in raw:
        cid = _parse_channel_id(token)
        if cid is None:
            return None
        ids.append(cid)
    return ids if ids else None


def _format_filter_tags(filters):
    tags = []
    if filters.get("blacklist_words"):
        tags.append("🚫BL")
    if filters.get("whitelist_words"):
        tags.append("✅WL")
    if filters.get("regex_blacklist"):
        tags.append("🔤RX")
    if filters.get("clean_words"):
        tags.append("🧹CW")
    if filters.get("regex_clean"):
        tags.append("🧹RC")
    if filters.get("clean_urls"):
        tags.append("🔗NoURL")
    if filters.get("clean_usernames"):
        tags.append("👤NoUser")
    if filters.get("skip_images"):
        tags.append("🖼NoImg")
    if filters.get("skip_audio"):
        tags.append("🔊NoAud")
    if filters.get("skip_videos"):
        tags.append("🎬NoVid")
    if filters.get("delay_seconds"):
        tags.append("⏱{}s".format(filters["delay_seconds"]))
    if filters.get("image_delete_days"):
        tags.append("🗑{}d".format(filters["image_delete_days"]))
    if filters.get("rewrite_enabled"):
        tags.append("🤖AI")
    return "  ".join(tags) if tags else "None configured"


def _cancel_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel", callback_data="m_main")
    builder.adjust(1)
    return builder.as_markup()


# ─── Create Task ───


@router.callback_query(F.data == "m_create")
async def cb_create_task(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(TaskCreateStates.waiting_for_name)
    await callback.message.edit_text(
        "➕  *Create New Task*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Step 1 of 3 — *Task Name*\n\n"
        "Send a name for this forwarding task:",
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
        "➕  *Create New Task*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Step 2 of 3 — *Source Channel*\n\n"
        "✅ Name: `{}`\n\n"
        "Send the *source channel ID*\n"
        "(e.g. `-1001234567890`)\n\n"
        "💡 Use 📡 Channels menu to find IDs".format(name),
        parse_mode="Markdown",
        reply_markup=_cancel_kb(),
    )


@router.message(TaskCreateStates.waiting_for_source, ~F.text.startswith("/"))
async def fsm_create_source(message: Message, state: FSMContext):
    cid = _parse_channel_id(message.text)
    if cid is None:
        await message.answer("❌ Invalid channel ID. Send a numeric ID:")
        return
    await state.update_data(source_id=cid)
    await state.set_state(TaskCreateStates.waiting_for_destinations)
    data = await state.get_data()
    await message.answer(
        "➕  *Create New Task*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Step 3 of 3 — *Destinations*\n\n"
        "✅ Name: `{}`\n"
        "✅ Source: `{}`\n\n"
        "Send *destination channel IDs*\n"
        "(comma or space separated)\n\n"
        "Example: `-1001111111111, -1002222222222`".format(data["task_name"], cid),
        parse_mode="Markdown",
        reply_markup=_cancel_kb(),
    )


@router.message(TaskCreateStates.waiting_for_destinations, ~F.text.startswith("/"))
async def fsm_create_destinations(message: Message, state: FSMContext):
    dest_ids = _parse_channel_ids(message.text)
    if dest_ids is None:
        await message.answer("❌ Invalid input. Send numeric channel IDs separated by commas or spaces:")
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

    dest_str = "\n".join("  → `{}`".format(d) for d in dest_ids)

    builder = InlineKeyboardBuilder()
    builder.button(text="🎛 Setup Filters", callback_data="flt_{}".format(task_id))
    builder.button(text="📋 View Tasks", callback_data="m_list")
    builder.button(text="🏠 Main Menu", callback_data="m_main")
    builder.adjust(1)

    await message.answer(
        "✅  *Task Created Successfully!*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 *{}*  (ID: `{}`)\n\n"
        "📥 Source:\n  `{}`\n\n"
        "📤 Destinations:\n{}\n\n"
        "🟢 Status: Enabled\n"
        "🎛 Filters: Default\n\n"
        "💡 Setup filters now or start forwarding!".format(task_name, task_id, source_id, dest_str),
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )


# ─── List Tasks ───


@router.callback_query(F.data == "m_list")
async def cb_list_tasks(callback: CallbackQuery):
    tasks = await get_tasks(callback.from_user.id)
    if not tasks:
        builder = InlineKeyboardBuilder()
        builder.button(text="➕ Create Task", callback_data="m_create")
        builder.button(text="⬅️ Back", callback_data="m_main")
        builder.adjust(1)
        await callback.message.edit_text(
            "📋  *My Tasks*\n"
            "━━━━━━━━━━━━\n\n"
            "You have no tasks yet.\n"
            "Create one to get started!",
            parse_mode="Markdown",
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        return

    lines = [
        "📋  *My Tasks*  ({} total)\n"
        "━━━━━━━━━━━━━━━━━━━━\n".format(len(tasks))
    ]

    for t in tasks:
        status_icon = "🟢" if t["enabled"] else "🔴"
        pause_icon = " ⏸" if t["paused"] else ""
        dests = ", ".join(str(d) for d in t["destination_channel_ids"])
        filter_tags = _format_filter_tags(t["filters"])

        lines.append(
            "{status} *{name}*{pause}  `(ID: {tid})`\n"
            "    📥 `{src}`\n"
            "    📤 `{dst}`\n"
            "    🎛 {filters}\n".format(
                status=status_icon,
                name=t["name"],
                pause=pause_icon,
                tid=t["id"],
                src=t["source_channel_id"],
                dst=dests,
                filters=filter_tags,
            )
        )

    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Create New", callback_data="m_create")
    builder.button(text="⬅️ Back", callback_data="m_main")
    builder.adjust(2)

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3950] + "\n\n_...truncated_"

    await callback.message.edit_text(
        text,
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


# ─── Toggle Task ───


@router.callback_query(F.data == "m_toggle")
async def cb_toggle_menu(callback: CallbackQuery):
    await show_tasks_submenu(callback, "tog", "🔀  *Toggle Task ON/OFF*\n\nSelect a task:")


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
    icon = "🟢" if new_status else "🔴"
    label = "ENABLED" if new_status else "DISABLED"

    builder = InlineKeyboardBuilder()
    builder.button(text="🔀 Toggle Another", callback_data="m_toggle")
    builder.button(text="🏠 Menu", callback_data="m_main")
    builder.adjust(2)

    await callback.message.edit_text(
        "{} Task *{}* is now *{}*".format(icon, task["name"], label),
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


# ─── Delete Task ───


@router.callback_query(F.data == "m_delete")
async def cb_delete_menu(callback: CallbackQuery):
    await show_tasks_submenu(callback, "del", "🗑  *Delete Task*\n\nSelect a task to delete:")


@router.callback_query(F.data.startswith("del_"))
async def cb_delete_confirm(callback: CallbackQuery):
    task_id = int(callback.data.split("_", 1)[1])
    user_id = callback.from_user.id
    task = await get_task(task_id, user_id)
    if not task:
        await callback.answer("Task not found.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Yes, Delete", callback_data="delconfirm_{}".format(task_id))
    builder.button(text="❌ Cancel", callback_data="m_main")
    builder.adjust(2)

    await callback.message.edit_text(
        "⚠️  *Are you sure?*\n\n"
        "Delete task *{}* (ID: `{}`)?\n"
        "This cannot be undone.".format(task["name"], task_id),
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delconfirm_"))
async def cb_delete_task(callback: CallbackQuery):
    task_id = int(callback.data.split("_", 1)[1])
    user_id = callback.from_user.id
    task = await get_task(task_id, user_id)
    if not task:
        await callback.answer("Task not found.", show_alert=True)
        return

    await delete_task(task_id, user_id)

    builder = InlineKeyboardBuilder()
    builder.button(text="📋 View Tasks", callback_data="m_list")
    builder.button(text="🏠 Menu", callback_data="m_main")
    builder.adjust(2)

    await callback.message.edit_text(
        "🗑  Task *{}* deleted.".format(task["name"]),
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


# ─── Duplicate Task ───


@router.callback_query(F.data == "m_duplicate")
async def cb_duplicate_menu(callback: CallbackQuery):
    await show_tasks_submenu(callback, "dup", "📑  *Duplicate Task*\n\nSelect a task to duplicate:")


@router.callback_query(F.data.startswith("dup_"))
async def cb_duplicate_task(callback: CallbackQuery):
    task_id = int(callback.data.split("_", 1)[1])
    user_id = callback.from_user.id
    task = await get_task(task_id, user_id)
    if not task:
        await callback.answer("Task not found.", show_alert=True)
        return

    new_name = "{} (copy)".format(task["name"])
    new_id = await create_task(
        user_id=user_id,
        name=new_name,
        source=task["source_channel_id"],
        destinations=list(task["destination_channel_ids"]),
        filters=dict(task["filters"]),
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🎛 Setup Filters", callback_data="flt_{}".format(new_id))
    builder.button(text="📋 View Tasks", callback_data="m_list")
    builder.button(text="🏠 Menu", callback_data="m_main")
    builder.adjust(1)

    await callback.message.edit_text(
        "📑  Task duplicated!\n\n"
        "New: *{}* (ID: `{}`)".format(new_name, new_id),
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


# ─── Edit Task ───


@router.callback_query(F.data == "m_edit")
async def cb_edit_menu(callback: CallbackQuery):
    await show_tasks_submenu(callback, "edt", "✏️  *Edit Task*\n\nSelect a task to edit:")


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

    dests = "\n".join("  → `{}`".format(d) for d in task["destination_channel_ids"])
    status_icon = "🟢" if task["enabled"] else "🔴"

    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Edit Name", callback_data="edtf_{}_name".format(task_id))
    builder.button(text="📥 Edit Source", callback_data="edtf_{}_source".format(task_id))
    builder.button(text="➕ Add Destinations", callback_data="edtf_{}_add_dest".format(task_id))
    builder.button(text="➖ Remove Destinations", callback_data="edtf_{}_rm_dest".format(task_id))
    builder.button(text="🎛 Edit Filters", callback_data="flt_{}".format(task_id))
    builder.button(text="⬅️ Back", callback_data="m_edit")
    builder.adjust(2, 2, 1, 1)

    await callback.message.edit_text(
        "✏️  *Edit Task*\n"
        "━━━━━━━━━━━━━━\n\n"
        "{status} *{name}*  `(ID: {tid})`\n\n"
        "📥 Source: `{src}`\n"
        "📤 Destinations:\n{dsts}\n\n"
        "Choose what to edit:".format(
            status=status_icon,
            name=task["name"],
            tid=task_id,
            src=task["source_channel_id"],
            dsts=dests,
        ),
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
        "📝  Send the *new task name*:",
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

    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Continue Editing", callback_data="edt_{}".format(task_id))
    builder.button(text="🏠 Menu", callback_data="m_main")
    builder.adjust(2)

    await message.answer(
        "✅ Task name updated to *{}*".format(new_name),
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )


# ── Edit Source ──


@router.callback_query(F.data.regexp(r"^edtf_(\d+)_source$"))
async def cb_edit_source(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.split("_")[1])
    await state.update_data(edit_task_id=task_id)
    await state.set_state(TaskEditStates.waiting_for_source)
    await callback.message.edit_text(
        "📥  Send the *new source channel ID*:\n\n"
        "💡 Use 📡 Channels to find IDs",
        parse_mode="Markdown",
        reply_markup=_cancel_kb(),
    )
    await callback.answer()


@router.message(TaskEditStates.waiting_for_source, ~F.text.startswith("/"))
async def fsm_edit_source(message: Message, state: FSMContext):
    cid = _parse_channel_id(message.text)
    if cid is None:
        await message.answer("❌ Invalid channel ID. Send a numeric ID:")
        return
    data = await state.get_data()
    task_id = data["edit_task_id"]
    user_id = message.from_user.id

    await update_task_field(task_id, user_id, source_channel_id=cid)
    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Continue Editing", callback_data="edt_{}".format(task_id))
    builder.button(text="🏠 Menu", callback_data="m_main")
    builder.adjust(2)

    await message.answer(
        "✅ Source channel updated to `{}`".format(cid),
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )


# ── Add Destinations ──


@router.callback_query(F.data.regexp(r"^edtf_(\d+)_add_dest$"))
async def cb_edit_add_dest(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.split("_")[1])
    await state.update_data(edit_task_id=task_id)
    await state.set_state(TaskEditStates.waiting_for_add_dests)
    await callback.message.edit_text(
        "➕  Send *destination channel IDs to add*\n"
        "(comma or space separated):",
        parse_mode="Markdown",
        reply_markup=_cancel_kb(),
    )
    await callback.answer()


@router.message(TaskEditStates.waiting_for_add_dests, ~F.text.startswith("/"))
async def fsm_edit_add_dests(message: Message, state: FSMContext):
    new_ids = _parse_channel_ids(message.text)
    if new_ids is None:
        await message.answer("❌ Invalid input. Send numeric channel IDs:")
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

    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Continue Editing", callback_data="edt_{}".format(task_id))
    builder.button(text="🏠 Menu", callback_data="m_main")
    builder.adjust(2)

    if added:
        added_str = ", ".join("`{}`".format(d) for d in added)
        await message.answer(
            "✅ Added: {}\nTotal destinations: {}".format(added_str, len(existing)),
            parse_mode="Markdown",
            reply_markup=builder.as_markup(),
        )
    else:
        await message.answer(
            "All IDs already in the list. No changes.",
            reply_markup=builder.as_markup(),
        )


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

    dest_list = "\n".join("  → `{}`".format(d) for d in dests)
    await callback.message.edit_text(
        "➖  *Remove Destinations*\n\n"
        "Current:\n{}\n\n"
        "Send the IDs to remove (comma or space separated):".format(dest_list),
        parse_mode="Markdown",
        reply_markup=_cancel_kb(),
    )
    await callback.answer()


@router.message(TaskEditStates.waiting_for_remove_dests, ~F.text.startswith("/"))
async def fsm_edit_rm_dests(message: Message, state: FSMContext):
    rm_ids = _parse_channel_ids(message.text)
    if rm_ids is None:
        await message.answer("❌ Invalid input. Send numeric channel IDs:")
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
            "⚠️ Cannot remove all destinations.\n"
            "A task needs at least one destination."
        )
        return

    await update_task_field(task_id, user_id, destination_channel_ids=existing)
    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Continue Editing", callback_data="edt_{}".format(task_id))
    builder.button(text="🏠 Menu", callback_data="m_main")
    builder.adjust(2)

    if removed:
        removed_str = ", ".join("`{}`".format(d) for d in removed)
        await message.answer(
            "✅ Removed: {}\nRemaining: {}".format(removed_str, len(existing)),
            parse_mode="Markdown",
            reply_markup=builder.as_markup(),
        )
    else:
        await message.answer(
            "None of those IDs were in the list. No changes.",
            reply_markup=builder.as_markup(),
        )
