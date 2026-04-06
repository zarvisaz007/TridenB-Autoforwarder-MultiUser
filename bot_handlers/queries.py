"""
User query/message handler — lets users send questions to the admin.
Admin sees and replies from the CLI dashboard.
"""

import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

import time

from bot_database import get_user, add_query, get_user_queries

logger = logging.getLogger("bot.queries")
router = Router()

# Fix 5: Cooldown tracking — maps user_id -> timestamp of last query submission
_query_cooldowns: dict = {}
_QUERY_COOLDOWN_SECONDS = 60

# Fix 6: Max query message length
_MAX_QUERY_LENGTH = 1000


class QueryStates(StatesGroup):
    waiting_for_message = State()


@router.callback_query(F.data == "m_query")
async def cb_query_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = await get_user(user_id)
    if not user or user["auth_state"] != "CONNECTED":
        await callback.answer("Connect first with /start", show_alert=True)
        return

    # Show recent queries
    queries = await get_user_queries(user_id, 5)

    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Send New Query", callback_data="q_new")
    builder.button(text="⬅️ Back", callback_data="m_main")
    builder.adjust(1)

    lines = [
        "📩  *Contact Admin*\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "Send a message or question to the admin.\n"
        "They will reply from the control panel.\n"
    ]

    if queries:
        lines.append("\n*Recent queries:*\n")
        for q in queries[:5]:
            status = "✅ Replied" if q.get("replied_at") else "⏳ Pending"
            msg_preview = q["message"][:50]
            lines.append("  {} — _{}_".format(status, msg_preview))
            if q.get("reply"):
                lines.append("    ↪️ {}".format(q["reply"][:60]))
            lines.append("")

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "q_new")
async def cb_query_new(callback: CallbackQuery, state: FSMContext):
    # Fix 4: Auth check — only CONNECTED users may submit queries
    user_id = callback.from_user.id
    user = await get_user(user_id)
    if not user or user["auth_state"] != "CONNECTED":
        await callback.answer("Connect first with /start", show_alert=True)
        return

    cancel_kb = InlineKeyboardBuilder()
    cancel_kb.button(text="❌ Cancel", callback_data="m_main")
    await callback.message.edit_text(
        "📝  *Send a Query*\n\n"
        "Type your message below.\n"
        "The admin will see it on the dashboard and reply.",
        parse_mode="Markdown",
        reply_markup=cancel_kb.as_markup(),
    )
    await state.set_state(QueryStates.waiting_for_message)
    await callback.answer()


@router.message(QueryStates.waiting_for_message, ~F.text.startswith("/"))
async def process_query_message(message: Message, state: FSMContext):
    user_id = message.from_user.id
    text = message.text.strip()

    if not text:
        await message.answer("Please type a message.")
        return

    # Fix 5: Rate limit — one query per 60 seconds
    now = time.time()
    last_query_time = _query_cooldowns.get(user_id, 0)
    if now - last_query_time < _QUERY_COOLDOWN_SECONDS:
        remaining = int(_QUERY_COOLDOWN_SECONDS - (now - last_query_time))
        await message.answer(
            f"⏳ Please wait {remaining} second(s) before sending another query."
        )
        return

    # Fix 6: Cap message length at 1000 characters
    truncated = False
    if len(text) > _MAX_QUERY_LENGTH:
        text = text[:_MAX_QUERY_LENGTH]
        truncated = True

    user = await get_user(user_id)
    phone = user.get("phone", "") if user else ""

    query_id = await add_query(user_id, phone, text)

    # Update cooldown timestamp after successful submission
    _query_cooldowns[user_id] = now

    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.button(text="📩 Send Another", callback_data="q_new")
    builder.button(text="🏠 Main Menu", callback_data="m_main")
    builder.adjust(2)

    truncation_note = "\n\n_Note: Your message was truncated to 1000 characters._" if truncated else ""
    await message.answer(
        "✅  *Query Sent!*\n\n"
        "Your message has been delivered to the admin.\n"
        "Query ID: `#{}`\n\n"
        "You'll receive a reply here when the admin responds.{}".format(query_id, truncation_note),
        parse_mode="Markdown",
        reply_markup=builder.as_markup(),
    )
