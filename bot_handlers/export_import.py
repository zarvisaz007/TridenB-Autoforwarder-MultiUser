import json
import io
import logging
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

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


@router.callback_query(F.data == "m_import")
async def cb_import(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "Send me a `.json` file to import tasks from.\n\n"
        "Expected format:\n```json\n{\"tasks\": [{\"name\": \"...\", ...}]}\n```",
        parse_mode="Markdown"
    )
    await state.set_state(ImportStates.waiting_for_file)
    await callback.answer()


@router.message(ImportStates.waiting_for_file, F.document)
async def process_import_file(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    doc = message.document

    if not doc.file_name.endswith(".json"):
        await message.answer("Please send a `.json` file.")
        return

    try:
        file = await bot.download(doc)
        content = file.read()
        data = json.loads(content.decode("utf-8"))
    except Exception as e:
        await message.answer(f"Failed to read file: `{e}`")
        await state.clear()
        return

    imported_tasks = data.get("tasks", [])
    if not imported_tasks:
        await message.answer("No tasks found in the file.")
        await state.clear()
        return

    added = 0
    for t in imported_tasks:
        name = t.get("name", "Imported Task")
        source = t.get("source_channel_id", 0)
        dests = t.get("destination_channel_ids", [])
        filters = t.get("filters", {})
        if source and dests:
            await create_task(user_id, name, source, dests, filters)
            added += 1

    await state.clear()
    await message.answer(f"Imported {added} task(s) successfully!")

    from bot_handlers.menu import show_main_menu
    await show_main_menu(message)


@router.message(ImportStates.waiting_for_file, ~F.document)
async def process_import_no_file(message: Message, state: FSMContext):
    if message.text and message.text.startswith('/'):
        await state.clear()
        return
    await message.answer("Please send a `.json` file, or type /start to cancel.")
