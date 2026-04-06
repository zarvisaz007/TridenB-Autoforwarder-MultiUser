import time
import datetime
import logging
import asyncio
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

import bot_forwarder
from bot_database import (
    get_tasks, get_report_schedules, create_report_schedule,
    toggle_report_schedule, delete_report_schedule, get_messages_by_date_range,
)
from reports.config import REPORT_CONFIG

logger = logging.getLogger("bot.reports")
router = Router()


def _cancel_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Cancel", callback_data="rep_cancel")
    return kb.as_markup()


class ReportOneTimeStates(StatesGroup):
    waiting_for_manual_channel = State()
    waiting_for_lookback = State()
    choosing_type = State()
    waiting_for_custom_prompt = State()


class ReportRecurringStates(StatesGroup):
    choosing_channel = State()
    choosing_frequency = State()
    waiting_for_time = State()
    waiting_for_day = State()
    waiting_for_lookback = State()
    choosing_type = State()
    waiting_for_custom_prompt = State()


# ─── Main Reports Menu ───

@router.callback_query(F.data == "m_reports")
async def cb_reports_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="One-Time Report", callback_data="rep_onetime")
    builder.button(text="Recurring Reports", callback_data="rep_recurring")
    builder.button(text="⬅️ Back", callback_data="cat_analytics")
    builder.adjust(1)
    await callback.message.edit_text(
        "📈  *AI Finance Reports*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Model: `{REPORT_CONFIG['ollama']['model']}` (local Ollama)",
        reply_markup=builder.as_markup(), parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "rep_cancel")
async def cb_rep_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    from bot_handlers.menu import show_main_menu
    await show_main_menu(callback)
    await callback.answer()


# ─── One-Time Report ───

@router.callback_query(F.data == "rep_onetime")
async def cb_rep_onetime(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    tasks = await get_tasks(user_id)

    builder = InlineKeyboardBuilder()
    seen = set()
    for t in tasks:
        sid = t["source_channel_id"]
        if sid not in seen:
            builder.button(text=f"{t['name']} ({sid})", callback_data=f"rch_{sid}")
            seen.add(sid)
    builder.button(text="Enter ID manually", callback_data="rch_manual")
    builder.button(text="<< Back", callback_data="m_reports")
    builder.adjust(1)
    await callback.message.edit_text("Select source channel for the report:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("rch_"))
async def cb_rep_channel(callback: CallbackQuery, state: FSMContext):
    raw = callback.data[4:]
    if raw == "manual":
        try:
            await callback.message.edit_text("Enter the channel ID:", reply_markup=_cancel_kb())
        except Exception:
            await callback.message.answer("Enter the channel ID:", reply_markup=_cancel_kb())
        await state.set_state(ReportOneTimeStates.waiting_for_manual_channel)
        await callback.answer()
        return

    channel_id = int(raw)
    await state.update_data(rep_channel_id=channel_id)
    try:
        await callback.message.edit_text("How many days to look back? (e.g. `7`):", reply_markup=_cancel_kb())
    except Exception:
        await callback.message.answer("How many days to look back? (e.g. `7`):", reply_markup=_cancel_kb())
    await state.set_state(ReportOneTimeStates.waiting_for_lookback)
    await callback.answer()


@router.message(ReportOneTimeStates.waiting_for_manual_channel, ~F.text.startswith('/'))
async def process_rep_manual_channel(message: Message, state: FSMContext):
    try:
        channel_id = int(message.text.strip())
    except ValueError:
        await message.answer("Invalid ID. Enter a numeric channel ID:", reply_markup=_cancel_kb())
        return
    await state.update_data(rep_channel_id=channel_id)
    await message.answer("How many days to look back? (e.g. `7`):", reply_markup=_cancel_kb())
    await state.set_state(ReportOneTimeStates.waiting_for_lookback)


@router.message(ReportOneTimeStates.waiting_for_lookback, ~F.text.startswith('/'))
async def process_rep_lookback(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        await message.answer("Enter a positive number:", reply_markup=_cancel_kb())
        return

    lookback_val = int(text)
    if lookback_val > 90:
        await message.answer("Maximum lookback is 90 days. Please enter a value between 1 and 90:", reply_markup=_cancel_kb())
        return

    await state.update_data(rep_lookback=lookback_val)

    # Show report type selection
    types = REPORT_CONFIG["report_types"]
    builder = InlineKeyboardBuilder()
    for key, cfg in types.items():
        builder.button(text=cfg["name"], callback_data=f"rtp_{key}")
    builder.button(text="❌ Cancel", callback_data="rep_cancel")
    builder.adjust(1)
    await message.answer("Select report type:", reply_markup=builder.as_markup())
    await state.set_state(ReportOneTimeStates.choosing_type)


@router.callback_query(F.data.startswith("rtp_"), ReportOneTimeStates.choosing_type)
async def cb_rep_type(callback: CallbackQuery, state: FSMContext):
    report_type = callback.data[4:]
    allowed_types = REPORT_CONFIG["report_types"]
    if report_type not in allowed_types:
        await callback.answer("Invalid report type.", show_alert=True)
        return
    await state.update_data(rep_type=report_type)

    if report_type == "custom":
        try:
            await callback.message.edit_text("Enter your custom analysis prompt:", reply_markup=_cancel_kb())
        except Exception:
            await callback.message.answer("Enter your custom analysis prompt:", reply_markup=_cancel_kb())
        await state.set_state(ReportOneTimeStates.waiting_for_custom_prompt)
        await callback.answer()
        return

    await callback.answer()
    await _generate_onetime_report(callback.message, state, callback.from_user.id)


@router.message(ReportOneTimeStates.waiting_for_custom_prompt, ~F.text.startswith('/'))
async def process_rep_custom(message: Message, state: FSMContext):
    await state.update_data(rep_custom_prompt=message.text.strip())
    await _generate_onetime_report(message, state, message.from_user.id)


async def _generate_onetime_report(message: Message, state: FSMContext, user_id: int):
    data = await state.get_data()
    await state.clear()

    channel_id = data["rep_channel_id"]
    lookback = data["rep_lookback"]
    report_type = data["rep_type"]
    custom_prompt = data.get("rep_custom_prompt")

    progress_msg = await message.answer("Generating report... fetching messages...")

    # Try fetching from Telegram first
    messages = []
    client = bot_forwarder.user_clients.get(user_id)
    if client and client.is_connected():
        try:
            cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=lookback)
            async for msg in client.iter_messages(channel_id, offset_date=cutoff, reverse=True, limit=500):
                text = msg.text or ""
                if text.strip():
                    messages.append({
                        "text_content": text,
                        "timestamp": int(msg.date.timestamp()),
                        "has_image": 1 if msg.photo else 0,
                    })
        except Exception as e:
            logger.warning(f"Telegram fetch failed for {user_id}: {e}")

    # Fallback to DB
    if not messages:
        now = int(time.time())
        start_ts = now - (lookback * 86400)
        messages = await get_messages_by_date_range(user_id, channel_id, start_ts, now)

    if not messages:
        await progress_msg.edit_text(f"No messages found for last {lookback} day(s).")
        return

    await progress_msg.edit_text(f"Found {len(messages)} messages. Analyzing with Ollama...")

    try:
        from reports.engine import generate_report

        def progress(msg):
            bot_forwarder.add_user_log(user_id, f"[REPORTS] {msg}")

        report = await generate_report(
            messages, report_type=report_type,
            custom_prompt=custom_prompt, progress_cb=progress,
        )

        # Send report (split if needed)
        header = f"**Finance Report** — {len(messages)} messages analyzed\n\n"
        full_text = header + report

        if len(full_text) <= 4000:
            await progress_msg.edit_text(full_text, parse_mode="Markdown")
        else:
            await progress_msg.edit_text(header + "Report is long, sending in parts...")
            chunks = [report[i:i+3900] for i in range(0, len(report), 3900)]
            for i, chunk in enumerate(chunks):
                await message.answer(f"**Part {i+1}/{len(chunks)}**\n\n{chunk}", parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Report generation failed for user {user_id}: {e}", exc_info=True)
        await progress_msg.edit_text("Report generation failed. Please try again later.")


# ─── Recurring Reports ───

@router.callback_query(F.data == "rep_recurring")
async def cb_rep_recurring(callback: CallbackQuery):
    user_id = callback.from_user.id
    schedules = await get_report_schedules(user_id)

    text = "**Recurring Reports**\n\n"
    if schedules:
        for s in schedules:
            status = "ON" if s["enabled"] else "OFF"
            next_run = time.strftime("%m-%d %H:%M", time.localtime(s["next_run"])) if s.get("next_run") else "—"
            rtype = REPORT_CONFIG["report_types"].get(s.get("report_type", "summary"), {}).get("name", "?")
            text += f"ID {s['id']} | {s.get('channel_name', '?')} | {s['frequency']} | {rtype} | {status} | Next: {next_run}\n"
    else:
        text += "No recurring reports configured.\n"

    builder = InlineKeyboardBuilder()
    builder.button(text="Create Schedule", callback_data="rsc_create")
    if schedules:
        builder.button(text="Toggle Schedule", callback_data="rsc_toggle")
        builder.button(text="Delete Schedule", callback_data="rsc_delete")
        builder.button(text="View Last Report", callback_data="rsc_view")
    builder.button(text="<< Back", callback_data="m_reports")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()


# ─── Create Recurring Schedule ───

@router.callback_query(F.data == "rsc_create")
async def cb_rsc_create(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    tasks = await get_tasks(user_id)

    builder = InlineKeyboardBuilder()
    seen = set()
    for t in tasks:
        sid = t["source_channel_id"]
        if sid not in seen:
            builder.button(text=f"{t['name']} ({sid})", callback_data=f"rscch_{sid}_{t['name'][:20]}")
            seen.add(sid)
    builder.button(text="<< Back", callback_data="rep_recurring")
    builder.adjust(1)
    await callback.message.edit_text("Select source channel:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("rscch_"))
async def cb_rsc_channel(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_", 2)
    if len(parts) < 2:
        await callback.answer("Session expired. Please start again.", show_alert=True)
        return
    channel_id = int(parts[1])
    channel_name = parts[2] if len(parts) > 2 else str(channel_id)
    await state.update_data(rsc_channel_id=channel_id, rsc_channel_name=channel_name)

    builder = InlineKeyboardBuilder()
    builder.button(text="Daily", callback_data="rscf_daily")
    builder.button(text="Weekly", callback_data="rscf_weekly")
    builder.button(text="Monthly", callback_data="rscf_monthly")
    builder.button(text="❌ Cancel", callback_data="rep_cancel")
    builder.adjust(3, 1)
    await callback.message.edit_text("Select frequency:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("rscf_"))
async def cb_rsc_freq(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("rsc_channel_id"):
        await callback.answer("Session expired. Please start again.", show_alert=True)
        return
    freq = callback.data[5:]
    await state.update_data(rsc_frequency=freq)

    if freq == "weekly":
        try:
            await callback.message.edit_text("Day of week? (0=Mon, 1=Tue, ..., 6=Sun):", reply_markup=_cancel_kb())
        except Exception:
            await callback.message.answer("Day of week? (0=Mon, 1=Tue, ..., 6=Sun):", reply_markup=_cancel_kb())
        await state.set_state(ReportRecurringStates.waiting_for_day)
    elif freq == "monthly":
        try:
            await callback.message.edit_text("Day of month? (1-31):", reply_markup=_cancel_kb())
        except Exception:
            await callback.message.answer("Day of month? (1-31):", reply_markup=_cancel_kb())
        await state.set_state(ReportRecurringStates.waiting_for_day)
    else:
        try:
            await callback.message.edit_text("Time of day? (HH:MM, 24h format, e.g. `08:00`):", reply_markup=_cancel_kb())
        except Exception:
            await callback.message.answer("Time of day? (HH:MM, 24h format, e.g. `08:00`):", reply_markup=_cancel_kb())
        await state.set_state(ReportRecurringStates.waiting_for_time)
    await callback.answer()


@router.message(ReportRecurringStates.waiting_for_day, ~F.text.startswith('/'))
async def process_rsc_day(message: Message, state: FSMContext):
    data = await state.get_data()
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("Enter a number:", reply_markup=_cancel_kb())
        return

    val = int(text)
    if data["rsc_frequency"] == "weekly":
        if not (0 <= val <= 6):
            await message.answer("Enter 0-6:", reply_markup=_cancel_kb())
            return
        await state.update_data(rsc_day_of_week=val)
    else:
        if not (1 <= val <= 31):
            await message.answer("Enter 1-31:", reply_markup=_cancel_kb())
            return
        await state.update_data(rsc_day_of_month=val)

    await message.answer("Time of day? (HH:MM, 24h, e.g. `08:00`):", reply_markup=_cancel_kb())
    await state.set_state(ReportRecurringStates.waiting_for_time)


@router.message(ReportRecurringStates.waiting_for_time, ~F.text.startswith('/'))
async def process_rsc_time(message: Message, state: FSMContext):
    text = message.text.strip()
    parts = text.split(":")
    valid = False
    if len(parts) == 2:
        try:
            hour = int(parts[0])
            minute = int(parts[1])
            valid = (0 <= hour <= 23) and (0 <= minute <= 59)
        except ValueError:
            valid = False
    if not valid:
        await message.answer("Use HH:MM format (e.g. `08:00`). Hour must be 0-23 and minute 0-59:")
        return
    await state.update_data(rsc_time=text)

    lookback_map = {"daily": 1, "weekly": 7, "monthly": 30}
    data = await state.get_data()
    default = lookback_map.get(data["rsc_frequency"], 1)
    await message.answer(f"Days of data to analyze? (default: {default}):", reply_markup=_cancel_kb())
    await state.set_state(ReportRecurringStates.waiting_for_lookback)


@router.message(ReportRecurringStates.waiting_for_lookback, ~F.text.startswith('/'))
async def process_rsc_lookback(message: Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    lookback_map = {"daily": 1, "weekly": 7, "monthly": 30}
    default = lookback_map.get(data["rsc_frequency"], 1)
    lookback = int(text) if text.isdigit() and int(text) > 0 else default
    await state.update_data(rsc_lookback=lookback)

    types = REPORT_CONFIG["report_types"]
    builder = InlineKeyboardBuilder()
    for key, cfg in types.items():
        builder.button(text=cfg["name"], callback_data=f"rsct_{key}")
    builder.button(text="❌ Cancel", callback_data="rep_cancel")
    builder.adjust(1)
    await message.answer("Report type:", reply_markup=builder.as_markup())
    await state.set_state(ReportRecurringStates.choosing_type)


@router.callback_query(F.data.startswith("rsct_"), ReportRecurringStates.choosing_type)
async def cb_rsc_type(callback: CallbackQuery, state: FSMContext):
    report_type = callback.data[5:]
    allowed_types = REPORT_CONFIG["report_types"]
    if report_type not in allowed_types:
        await callback.answer("Invalid report type.", show_alert=True)
        return
    await state.update_data(rsc_report_type=report_type)

    if report_type == "custom":
        try:
            await callback.message.edit_text("Enter your custom prompt:", reply_markup=_cancel_kb())
        except Exception:
            await callback.message.answer("Enter your custom prompt:", reply_markup=_cancel_kb())
        await state.set_state(ReportRecurringStates.waiting_for_custom_prompt)
        await callback.answer()
        return

    await callback.answer()
    await _create_schedule(callback.message, state, callback.from_user.id)


@router.message(ReportRecurringStates.waiting_for_custom_prompt, ~F.text.startswith('/'))
async def process_rsc_custom(message: Message, state: FSMContext):
    await state.update_data(rsc_custom_prompt=message.text.strip())
    await _create_schedule(message, state, message.from_user.id)


async def _create_schedule(message: Message, state: FSMContext, user_id: int):
    data = await state.get_data()
    await state.clear()

    schedule_data = {
        "source_channel_id": data["rsc_channel_id"],
        "channel_name": data["rsc_channel_name"],
        "frequency": data["rsc_frequency"],
        "time_of_day": data["rsc_time"],
        "report_type": data["rsc_report_type"],
        "custom_prompt": data.get("rsc_custom_prompt"),
        "lookback_days": data.get("rsc_lookback", 1),
        "day_of_week": data.get("rsc_day_of_week"),
        "day_of_month": data.get("rsc_day_of_month"),
    }

    # Compute next run
    next_run = bot_forwarder._compute_next_run(schedule_data)
    schedule_data["next_run"] = next_run

    sid = await create_report_schedule(user_id, **schedule_data)

    next_run_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(next_run))
    await message.answer(f"Schedule created (ID {sid})!\nNext run: {next_run_str}")

    from bot_handlers.menu import show_main_menu
    await show_main_menu(message)


# ─── Toggle / Delete / View Schedule ───

@router.callback_query(F.data == "rsc_toggle")
async def cb_rsc_toggle(callback: CallbackQuery):
    user_id = callback.from_user.id
    schedules = await get_report_schedules(user_id)
    builder = InlineKeyboardBuilder()
    for s in schedules:
        status = "ON" if s["enabled"] else "OFF"
        builder.button(text=f"{s.get('channel_name', '?')} [{status}]", callback_data=f"rsctg_{s['id']}")
    builder.button(text="<< Back", callback_data="rep_recurring")
    builder.adjust(1)
    await callback.message.edit_text("Toggle which schedule?", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("rsctg_"))
async def cb_rsc_do_toggle(callback: CallbackQuery):
    sid = int(callback.data.split("_")[1])
    result = await toggle_report_schedule(sid, callback.from_user.id)
    if result:
        status = "ENABLED" if result["enabled"] else "DISABLED"
        await callback.answer(f"Schedule {status}.", show_alert=True)
    else:
        await callback.answer("Schedule not found.", show_alert=True)
    # Refresh
    await cb_rep_recurring(callback)


@router.callback_query(F.data == "rsc_delete")
async def cb_rsc_delete(callback: CallbackQuery):
    user_id = callback.from_user.id
    schedules = await get_report_schedules(user_id)
    builder = InlineKeyboardBuilder()
    for s in schedules:
        builder.button(text=f"{s.get('channel_name', '?')} ({s['frequency']})", callback_data=f"rscdl_{s['id']}")
    builder.button(text="<< Back", callback_data="rep_recurring")
    builder.adjust(1)
    await callback.message.edit_text("Delete which schedule?", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("rscdl_"))
async def cb_rsc_do_delete(callback: CallbackQuery):
    sid = int(callback.data.split("_")[1])
    await delete_report_schedule(sid, callback.from_user.id)
    await callback.answer("Schedule deleted.", show_alert=True)
    await cb_rep_recurring(callback)


@router.callback_query(F.data == "rsc_view")
async def cb_rsc_view(callback: CallbackQuery):
    user_id = callback.from_user.id
    schedules = await get_report_schedules(user_id)
    builder = InlineKeyboardBuilder()
    for s in schedules:
        builder.button(text=f"{s.get('channel_name', '?')}", callback_data=f"rscvw_{s['id']}")
    builder.button(text="<< Back", callback_data="rep_recurring")
    builder.adjust(1)
    await callback.message.edit_text("View last report for:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("rscvw_"))
async def cb_rsc_do_view(callback: CallbackQuery):
    sid = int(callback.data.split("_")[1])
    last = bot_forwarder.get_last_report(sid)
    if not last:
        await callback.answer("No report generated yet for this schedule.", show_alert=True)
        return

    gen_time = time.strftime("%Y-%m-%d %H:%M", time.localtime(last["generated_at"]))
    text = f"**Last Report** (generated {gen_time}, {last['message_count']} msgs)\n\n{last['text']}"
    if len(text) > 4000:
        text = text[:3990] + "..."
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()
