import json
import io
import logging
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot_database import get_tasks, create_task

logger = logging.getLogger("bot.export_import")
router = Router()


class ImportStates(StatesGroup):
    waiting_for_file = State()


@router.callback_query(F.data == "m_export")
async def cb_export(callback: CallbackQuery):
    user_id = callback.from_user.id
    tasks = await get_tasks(user_id)

    if not tasks:
        await callback.message.answer("You have no tasks to export.")
        await callback.answer()
        return

    export_data = {"tasks": []}
    for t in tasks:
        export_data["tasks"].append({
            "name": t["name"],
            "source_channel_id": t["source_channel_id"],
            "destination_channel_ids": t["destination_channel_ids"],
            "enabled": t["enabled"],
            "filters": t["filters"],
        })

    json_bytes = json.dumps(export_data, indent=2).encode("utf-8")
    doc = BufferedInputFile(json_bytes, filename=f"tasks_export_{user_id}.json")
    await callback.message.answer_document(doc, caption=f"Exported {len(tasks)} task(s).")
    await callback.answer()


def _cancel_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Cancel", callback_data="m_impexp")
    return kb.as_markup()


@router.callback_query(F.data == "m_impexp")
async def cb_impexp_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    from bot_handlers.menu import show_main_menu
    await show_main_menu(callback.message)
    await callback.answer()


@router.callback_query(F.data == "m_import")
async def cb_import(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Send me a `.json` file to import tasks from.\n\n"
        "Expected format:\n```json\n{\"tasks\": [{\"name\": \"...\", ...}]}\n```",
        parse_mode="Markdown",
        reply_markup=_cancel_kb(),
    )
    await state.set_state(ImportStates.waiting_for_file)
    await callback.answer()


_MAX_FILE_SIZE = 524288  # 512 KB
_MAX_IMPORT_TASKS = 50


@router.message(ImportStates.waiting_for_file, F.document)
async def process_import_file(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    doc = message.document

    if not doc.file_name.endswith(".json"):
        await message.answer("Please send a `.json` file.")
        return

    # Fix 2: Reject oversized files before downloading
    if doc.file_size and doc.file_size > _MAX_FILE_SIZE:
        await message.answer(
            f"File is too large ({doc.file_size // 1024} KB). Maximum allowed size is 512 KB."
        )
        await state.clear()
        return

    try:
        file = await bot.download(doc)
        content = file.read()
        data = json.loads(content.decode("utf-8"))
    except Exception as e:
        logger.error(f"Import file error for user {user_id}: {e}")
        await message.answer("Failed to read file. Please ensure it is a valid JSON export and try again.")
        await state.clear()
        return

    imported_tasks = data.get("tasks", [])
    if not imported_tasks:
        await message.answer("No tasks found in the file.")
        await state.clear()
        return

    # Fix 2: Cap number of tasks to process
    imported_tasks = imported_tasks[:_MAX_IMPORT_TASKS]

    added = 0
    skipped = 0
    for t in imported_tasks:
        # Fix 3: Validate field types
        name = t.get("name", "Imported Task")
        source = t.get("source_channel_id")
        dests = t.get("destination_channel_ids")
        filters = t.get("filters", {})

        if not isinstance(name, str) or len(name) > 100:
            skipped += 1
            continue
        if not isinstance(source, int):
            skipped += 1
            continue
        if not isinstance(dests, list) or len(dests) == 0 or not all(isinstance(d, int) for d in dests):
            skipped += 1
            continue
        if not isinstance(filters, dict):
            skipped += 1
            continue

        await create_task(user_id, name, source, dests, filters)
        added += 1

    await state.clear()

    summary = f"Imported {added} task(s) successfully!"
    if skipped:
        summary += f" {skipped} task(s) were skipped due to invalid data."
    await message.answer(summary)

    from bot_handlers.menu import show_main_menu
    await show_main_menu(message)


@router.message(ImportStates.waiting_for_file, ~F.document)
async def process_import_no_file(message: Message, state: FSMContext):
    if message.text and message.text.startswith('/'):
        await state.clear()
        return
    await message.answer("Please send a `.json` file.", reply_markup=_cancel_kb())
