import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

logger = logging.getLogger("bot.menu")
router = Router()


async def safe_edit(callback, text, **kwargs):
    """Edit the callback message, falling back to answer() if edit fails."""
    try:
        await callback.message.edit_text(text, **kwargs)
    except Exception:
        await callback.message.answer(text, **kwargs)


def get_main_menu_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="📡  Channels", callback_data="cat_channels")
    builder.button(text="📋  My Tasks", callback_data="cat_tasks")
    builder.button(text="🔄  Forwarder", callback_data="cat_forwarder")
    builder.button(text="🎛  Filters & AI", callback_data="cat_filters")
    builder.button(text="📊  Analytics", callback_data="cat_analytics")
    builder.button(text="📁  Import / Export", callback_data="cat_export")
    builder.button(text="📩  Contact Admin", callback_data="m_query")
    builder.button(text="🛡  Admin Panel", callback_data="m_admin")
    builder.button(text="❌  Close", callback_data="m_close")
    builder.adjust(2, 2, 2, 2)
    return builder.as_markup()


MAIN_MENU_TEXT = (
    "╔══════════════════════════════════╗\n"
    "║   ⚡ Ultimate Autoforwarder      ║\n"
    "╚══════════════════════════════════╝\n\n"
    "Welcome! Choose a category below:"
)


async def show_main_menu(target, state: FSMContext = None):
    """Send main menu. target can be Message or CallbackQuery.
    If state is provided, clear any stuck FSM state first."""
    if state is not None:
        await state.clear()
    kb = get_main_menu_kb()
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(MAIN_MENU_TEXT, reply_markup=kb)
        except Exception:
            await target.message.answer(MAIN_MENU_TEXT, reply_markup=kb)
    else:
        await target.answer(MAIN_MENU_TEXT, reply_markup=kb)


def _back_button(data="m_main"):
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Back", callback_data=data)
    return builder


# ─── Category: Channels ───

@router.callback_query(F.data == "cat_channels")
async def cat_channels(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="📡  Get Channel IDs", callback_data="m_get_id")
    builder.button(text="⬅️ Back", callback_data="m_main")
    builder.adjust(1)
    await safe_edit(
        callback,
        "📡  *Channel Tools*\n\n"
        "Fetch your Telegram channels and groups.\n"
        "Tap a channel to copy its ID instantly.",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )
    await callback.answer()


# ─── Category: Tasks ───

@router.callback_query(F.data == "cat_tasks")
async def cat_tasks(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="➕  Create Task", callback_data="m_create")
    builder.button(text="📋  List Tasks", callback_data="m_list")
    builder.button(text="✏️  Edit Task", callback_data="m_edit")
    builder.button(text="🔀  Toggle ON/OFF", callback_data="m_toggle")
    builder.button(text="📑  Duplicate Task", callback_data="m_duplicate")
    builder.button(text="🗑  Delete Task", callback_data="m_delete")
    builder.button(text="⬅️ Back", callback_data="m_main")
    builder.adjust(2, 2, 2, 1)
    await safe_edit(
        callback,
        "📋  *Task Management*\n\n"
        "Create and manage your forwarding tasks.\n"
        "Each task forwards from one source to one or more destinations.",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )
    await callback.answer()


# ─── Category: Forwarder ───

@router.callback_query(F.data == "cat_forwarder")
async def cat_forwarder(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="▶️  Start Forwarder", callback_data="m_start_fwd")
    builder.button(text="⏹  Stop Forwarder", callback_data="m_stop_fwd")
    builder.button(text="⏸  Pause / Resume Task", callback_data="m_pause")
    builder.button(text="📡  Forwarder Status", callback_data="m_fwd_status")
    builder.button(text="⬅️ Back", callback_data="m_main")
    builder.adjust(2, 2, 1)
    await safe_edit(
        callback,
        "🔄  *Forwarder Control*\n\n"
        "Start, stop or monitor your message forwarder.\n"
        "Pause individual tasks without stopping the whole engine.",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )
    await callback.answer()


# ─── Category: Filters & AI ───

@router.callback_query(F.data == "cat_filters")
async def cat_filters(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="🎛  Edit Filters", callback_data="m_filters")
    builder.button(text="🤖  AI Rewrite Config", callback_data="m_rewrite")
    builder.button(text="⬅️ Back", callback_data="m_main")
    builder.adjust(1)
    await safe_edit(
        callback,
        "🎛  *Filters & AI Rewriting*\n\n"
        "Configure per-task filters: blacklist, whitelist, regex,\n"
        "URL/username cleaning, media skipping, delays.\n\n"
        "Enable AI rewriting to transform messages before forwarding.",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )
    await callback.answer()


# ─── Category: Analytics ───

@router.callback_query(F.data == "cat_analytics")
async def cat_analytics(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="📊  Statistics", callback_data="m_stats")
    builder.button(text="🧵  Message Threads", callback_data="m_threads")
    builder.button(text="📝  View Logs", callback_data="m_logs")
    builder.button(text="📈  AI Finance Reports", callback_data="m_reports")
    builder.button(text="⬅️ Back", callback_data="m_main")
    builder.adjust(2, 2, 1)
    await safe_edit(
        callback,
        "📊  *Analytics & Reports*\n\n"
        "View forwarding statistics, message threads,\n"
        "live logs, and generate AI-powered reports.",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )
    await callback.answer()


# ─── Category: Import / Export ───

@router.callback_query(F.data == "cat_export")
async def cat_export(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="📤  Export Tasks", callback_data="m_export")
    builder.button(text="📥  Import Tasks", callback_data="m_import")
    builder.button(text="⬅️ Back", callback_data="m_main")
    builder.adjust(2, 1)
    await safe_edit(
        callback,
        "📁  *Import / Export*\n\n"
        "Export your task configs as JSON backup.\n"
        "Import tasks from a previously exported file.",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )
    await callback.answer()


# ─── Core Navigation ───

@router.callback_query(F.data == "m_main")
async def cb_main(callback: CallbackQuery, state: FSMContext):
    await show_main_menu(callback, state=state)
    await callback.answer()


@router.callback_query(F.data == "m_noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data == "m_close")
async def cb_close(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Menu closed. Send /start to open again.")
    await callback.answer()


# ─── Slash Command Handlers ───

@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    await show_main_menu(message, state=state)


@router.message(Command("status"))
async def cmd_status(message: Message):
    import bot_forwarder
    from bot_database import get_tasks, get_statistics
    user_id = message.from_user.id
    client = bot_forwarder.user_clients.get(user_id)
    connected = client is not None and client.is_connected()
    tasks = await get_tasks(user_id)
    enabled = sum(1 for t in tasks if t["enabled"])
    stats = await get_statistics(user_id)
    today_msgs = sum(s.get("today_count", 0) for s in stats)
    total_msgs = sum(s.get("total_messages", 0) for s in stats)
    conn_icon = "🟢 Connected" if connected else "🔴 Disconnected"
    await message.answer(
        "📡  *Forwarder Status*\n━━━━━━━━━━━━━━━━━━\n\n"
        "{}\n📋 {} active task(s) / {} total\n"
        "📨 Today: {} | All time: {}".format(
            conn_icon, enabled, len(tasks), today_msgs, total_msgs
        ),
        parse_mode="Markdown",
    )


@router.message(Command("tasks"))
async def cmd_tasks(message: Message):
    from bot_database import get_tasks
    user_id = message.from_user.id
    tasks = await get_tasks(user_id)
    if not tasks:
        await message.answer("📋 You have no tasks yet. Use /menu to create one.")
        return
    lines = ["📋  *Your Tasks*\n━━━━━━━━━━━━━━━\n"]
    for t in tasks:
        icon = "🟢" if t["enabled"] else "🔴"
        pause = " ⏸" if t["paused"] else ""
        lines.append("{}  *{}*{}\n     Source: `{}`".format(icon, t["name"], pause, t["source_chat_id"]))
    await message.answer("\n".join(lines), parse_mode="Markdown")


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    from bot_database import get_statistics
    user_id = message.from_user.id
    stats = await get_statistics(user_id)
    if not stats:
        await message.answer("📊 No statistics yet. Start forwarding first.")
        return
    total_msgs = sum(s.get("total_messages", 0) for s in stats)
    total_imgs = sum(s.get("total_images", 0) for s in stats)
    today = sum(s.get("today_count", 0) for s in stats)
    week = sum(s.get("week_count", 0) for s in stats)
    await message.answer(
        "📊  *Statistics*\n━━━━━━━━━━━━━━━\n\n"
        "📨 Today: {}\n📅 This week: {}\n"
        "📊 All time: {} messages, {} images".format(today, week, total_msgs, total_imgs),
        parse_mode="Markdown",
    )


@router.message(Command("logs"))
async def cmd_logs(message: Message):
    import bot_forwarder
    user_id = message.from_user.id
    logs = bot_forwarder.get_user_logs(user_id, 15)
    if not logs:
        await message.answer("📝 No logs yet. Start the forwarder first.")
        return
    text = "📝  *Recent Logs*\n━━━━━━━━━━━━━━━\n\n```\n"
    for entry in logs:
        text += entry + "\n"
    text += "```"
    if len(text) > 4000:
        text = text[:3980] + "\n...```"
    await message.answer(text, parse_mode="Markdown")


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "⚡  *Ultimate Autoforwarder — Help*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 *Commands:*\n"
        "/start — Connect account & open menu\n"
        "/menu — Open main menu\n"
        "/status — Forwarder connection status\n"
        "/tasks — List your forwarding tasks\n"
        "/stats — View forwarding statistics\n"
        "/logs — View recent activity logs\n"
        "/help — Show this help message\n\n"
        "💡 Use the inline menu buttons for full control.\n"
        "📩 Use Contact Admin from the menu if you need help.",
        parse_mode="Markdown",
    )


async def show_tasks_submenu(callback, action_prefix, text, back_to="m_main"):
    from bot_database import get_tasks
    tasks = await get_tasks(callback.from_user.id)
    if not tasks:
        builder = InlineKeyboardBuilder()
        builder.button(text="➕ Create Task", callback_data="m_create")
        builder.button(text="⬅️ Back", callback_data=back_to)
        builder.adjust(1)
        await safe_edit(
            callback,
            "You have no tasks yet.\nCreate one to get started!",
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        return
    builder = InlineKeyboardBuilder()
    for t in tasks:
        icon = "🟢" if t["enabled"] else "🔴"
        pause = " ⏸" if t["paused"] else ""
        builder.button(
            text=f"{icon} {t['name']}{pause}",
            callback_data=f"{action_prefix}_{t['id']}",
        )
    builder.button(text="⬅️ Back", callback_data=back_to)
    builder.adjust(1)
    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception:
        await callback.message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()
